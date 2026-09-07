"""A projection reuses a scoped read transaction and closes it on every path."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from finai_api.services import function_invocations
from finai_api.services.semantic_analysis_support import Resolver


def test_single_scoped_transaction_is_reused_and_cleared_after_failure(monkeypatch):
    principal = object()
    events = []
    cursor = SimpleNamespace(execute=lambda sql: events.append(sql))

    @contextmanager
    def database(actual):
        assert actual is principal
        events.append("open")
        try:
            yield cursor
        finally:
            events.append("close")

    monkeypatch.setattr(function_invocations, "_database", database)
    resolver = Resolver(principal, {"function": {}, "static_dependencies": []})
    with pytest.raises(ValueError, match="failed projection"), resolver.read_session():
        for _ in range(20):
            with resolver.database() as selected:
                assert selected is cursor
        with pytest.raises(RuntimeError, match="already active"), resolver.read_session():
            pass
        raise ValueError("failed projection")
    assert resolver._cursor is None
    assert events == ["open", "SET TRANSACTION READ ONLY", "close"]


def test_different_requests_have_distinct_authorized_sessions(monkeypatch):
    opened = []

    @contextmanager
    def database(principal):
        cursor = SimpleNamespace(execute=lambda sql: None)
        opened.append((principal, cursor))
        yield cursor

    monkeypatch.setattr(function_invocations, "_database", database)
    first, second = object(), object()
    for principal in (first, second):
        resolver = Resolver(principal, {"function": {}, "static_dependencies": []})
        with resolver.read_session(), resolver.database() as cursor:
            assert cursor is opened[-1][1]
        assert resolver._cursor is None
    assert opened[0][0] is first and opened[1][0] is second
    assert opened[0][1] is not opened[1][1]
