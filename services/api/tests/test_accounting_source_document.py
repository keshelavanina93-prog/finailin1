from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest
from fastapi import HTTPException

from finai_api.domain.authority import ExactScope
from finai_api.domain.review import Principal
from finai_api.evidence_objects import EvidenceStoreUnavailable
from finai_api.services import accounting_source_document as bridge
from finai_api.services.workspace import WorkspaceError


@pytest.fixture
def source(monkeypatch):
    principal = Principal(
        actor_id="source-observer",
        display_name="Source observer",
        scope=ExactScope(
            tenant_id=uuid4(), legal_entity_id="source-scope", period="2025-01", currency="GEL"
        ),
        permissions=("ontology_read",),
    )
    content = b"retained source bytes"
    row = {
        "source_bytes": content,
        "source_sha256": sha256(content).hexdigest(),
        "exact_scope": principal.scope.model_dump(mode="json"),
        "request": {
            "filename": "Original.xlsx",
            "source_use": "HISTORICAL_REFERENCE",
            "source_encoding": "OOXML_XLSX",
        },
        "receipt": {"source_profile": {"sheets": [{"sheet": "Base"}]}},
        "ingested_at": datetime.now(UTC),
    }

    @contextmanager
    def connection(scope):
        yield object()

    monkeypatch.setattr(bridge, "connection", connection)
    monkeypatch.setattr(bridge, "_run", lambda *_: row)
    return principal, row, content


def test_hydration_bridge_preserves_receipt_identity_and_original_source_semantics(source):
    principal, row, content = source
    metadata, actual = bridge.read_source(principal, "ir_retained")
    assert actual == content
    assert metadata["document_id"] == metadata["construction_receipt_id"] == "ir_retained"
    assert metadata["source_sha256"] == row["source_sha256"]
    assert metadata["source_snapshot"]["source_use"] == "HISTORICAL_REFERENCE"
    assert metadata["source_snapshot"]["exact_scope"] == row["exact_scope"]
    assert metadata["source_snapshot"]["source_profile"] == row["receipt"]["source_profile"]


def test_existing_scope_and_byte_integrity_checks_remain_in_force(source):
    principal, row, _ = source
    original = row["source_bytes"]
    row["source_bytes"] = b"changed bytes"
    with pytest.raises(EvidenceStoreUnavailable, match="integrity"):
        bridge.read_source(principal, "ir_retained")
    row["source_bytes"] = original
    row["exact_scope"] = {**row["exact_scope"], "period": "2025-02"}
    with pytest.raises(EvidenceStoreUnavailable, match="scope"):
        bridge.read_source(principal, "ir_retained")


def test_document_path_delegates_without_new_identity_or_changed_metadata(source, monkeypatch):
    principal, _, _ = source
    retained = ({"document_id": "doc_original", "storage": {"version": "original"}}, b"original")
    calls = []

    def document_bytes(actor, identity):
        calls.append((actor, identity))
        return retained

    monkeypatch.setattr(bridge, "document_bytes", document_bytes)
    assert bridge.read_source(principal, "doc_original") is retained
    assert calls == [(principal, "doc_original")]


def test_permission_missing_source_and_unknown_identity_refuse_reads(source, monkeypatch):
    principal, _, _ = source
    with pytest.raises(HTTPException) as denied:
        bridge.read_source(principal.model_copy(update={"permissions": ()}), "ir_retained")
    assert denied.value.status_code == 403
    with pytest.raises(WorkspaceError, match="existing retained"):
        bridge.read_source(principal, "new-file.xlsx")

    def missing(*_):
        raise WorkspaceError(404, "Construction not found in authorized scope")

    monkeypatch.setattr(bridge, "_run", missing)
    with pytest.raises(WorkspaceError, match="authorized scope"):
        bridge.read_source(principal, "ir_missing")
