"""Source-linked calculation runs fail closed when retained bytes drift."""

from contextlib import contextmanager
from hashlib import sha256
from uuid import uuid4

import pytest

from finai_api.domain.authority import ExactScope
from finai_api.domain.review import Principal
from finai_api.services import fact_runs
from finai_api.services.workspace import WorkspaceError


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, *_args):
        return self

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self, **_kwargs):
        return _Cursor(self.rows)


def _principal() -> Principal:
    return Principal(
        actor_id="lineage-test",
        display_name="Lineage test",
        scope=ExactScope(
            tenant_id=uuid4(), legal_entity_id="entity", period="2025-01", currency="GEL"
        ),
        permissions=("ontology_read",),
    )


def _payload(content: bytes) -> dict:
    return {
        "lineage": {
            "receipt_ids": ["receipt-1"],
            "source_hashes": [sha256(content).hexdigest()],
        }
    }


def test_source_lineage_replays_the_exact_retained_bytes(monkeypatch):
    principal = _principal()
    content = b"retained-source"
    digest = sha256(content).hexdigest()
    rows = [
        {
            "receipt_id": "receipt-1",
            "exact_scope": principal.scope.model_dump(mode="json"),
            "source_bytes": content,
            "source_storage": None,
            "source_sha256": digest,
        }
    ]

    @contextmanager
    def connection(*_args, **_kwargs):
        yield _Connection(rows)

    monkeypatch.setattr(fact_runs, "connection", connection)
    monkeypatch.setattr(fact_runs, "retained_source", lambda _scope, row: row["source_bytes"])

    fact_runs._verify_source_lineage(principal, _payload(content))


def test_source_lineage_invalidates_a_changed_byte(monkeypatch):
    principal = _principal()
    original = b"retained-source"
    rows = [
        {
            "receipt_id": "receipt-1",
            "exact_scope": principal.scope.model_dump(mode="json"),
            "source_bytes": original,
            "source_storage": None,
            "source_sha256": sha256(original).hexdigest(),
        }
    ]

    @contextmanager
    def connection(*_args, **_kwargs):
        yield _Connection(rows)

    monkeypatch.setattr(fact_runs, "connection", connection)
    monkeypatch.setattr(fact_runs, "retained_source", lambda _scope, _row: b"one-byte-change")

    with pytest.raises(WorkspaceError, match=r"integrity verification|bytes changed"):
        fact_runs._verify_source_lineage(principal, _payload(original))


def test_source_lineage_missing_receipt_invalidates_run(monkeypatch):
    principal = _principal()

    @contextmanager
    def connection(*_args, **_kwargs):
        yield _Connection([])

    monkeypatch.setattr(fact_runs, "connection", connection)

    with pytest.raises(WorkspaceError, match="evidence is unavailable"):
        fact_runs._verify_source_lineage(principal, _payload(b"retained-source"))
