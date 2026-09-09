"""Request-local discovery read controls leave ordinary storage callers unchanged."""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from finai_api import read_budget, storage
from finai_api.read_budget import ReadBudgetExceeded


def test_nested_deadline_cannot_extend_and_resets_on_failure(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(read_budget, "monotonic", lambda: clock[0])
    assert read_budget.remaining_ms() is None
    with read_budget.bounded_read(2):
        assert read_budget.remaining_ms() == 2000
        with pytest.raises(ReadBudgetExceeded), read_budget.bounded_read(100):
            clock[0] = 102.1
            read_budget.remaining_ms()
        clock[0] = 101
        assert read_budget.remaining_ms() == 1000
    assert read_budget.remaining_ms() is None


def test_context_isolated_and_storage_readonly_after_connect(monkeypatch):
    from contextvars import Context

    clock, calls = [100.0], []
    monkeypatch.setattr(read_budget, "monotonic", lambda: clock[0])

    class Conn:
        def execute(self, *args):
            calls.append(args)

    def connect(_dsn, **options):
        assert options == {"connect_timeout": 3}
        clock[0] += 1
        return nullcontext(Conn())

    monkeypatch.setattr(storage.psycopg, "connect", connect)
    monkeypatch.setattr(
        storage, "get_settings", lambda: SimpleNamespace(database_url=SecretStr("private-test-dsn"))
    )
    scope = SimpleNamespace(tenant_id="tenant")
    with read_budget.bounded_read(2):
        assert Context().run(read_budget.remaining_ms) is None
        with storage.connection(scope):
            pass
    assert ("SET TRANSACTION READ ONLY",) in calls
    assert ("SELECT set_config('statement_timeout',%s,true)", ("1000",)) in calls
    calls.clear()
    with storage.connection(scope):
        pass
    assert len(calls) == 1 and "finai.tenant_id" in calls[0][0]


def test_connection_exhaustion_does_not_start_query(monkeypatch):
    clock, calls = [100.0], []
    monkeypatch.setattr(read_budget, "monotonic", lambda: clock[0])

    class Conn:
        def execute(self, *args):
            calls.append(args)

    def connect(*_a, **_kw):
        clock[0] += 3
        return nullcontext(Conn())

    monkeypatch.setattr(storage.psycopg, "connect", connect)
    monkeypatch.setattr(
        storage, "get_settings", lambda: SimpleNamespace(database_url=SecretStr("private-test-dsn"))
    )
    with (
        read_budget.bounded_read(1),
        pytest.raises(ReadBudgetExceeded),
        storage.connection(SimpleNamespace(tenant_id="tenant")),
    ):
        pytest.fail("Expired connection must not be yielded")
    assert calls == []


def test_shared_resolver_rechecks_deadline_before_each_read(monkeypatch):
    from finai_api.services.semantic_analysis_support import Resolver

    clock, calls = [100.0], []
    monkeypatch.setattr(read_budget, "monotonic", lambda: clock[0])
    resolver = Resolver(None, {"static_dependencies": [], "function": {}})
    resolver._cursor = SimpleNamespace(execute=lambda *args: calls.append(args))
    with read_budget.bounded_read(2):
        with resolver.database():
            pass
        clock[0] = 101.5
        with resolver.database():
            pass
        clock[0] = 103
        with pytest.raises(ReadBudgetExceeded), resolver.database():
            pytest.fail("Expired resolver must not issue another query")
    assert [args[1] for args in calls] == [("2000",), ("500",)]
    calls.clear()
    with resolver.database():
        pass
    assert calls == []
