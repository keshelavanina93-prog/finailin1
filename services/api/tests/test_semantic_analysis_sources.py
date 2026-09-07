"""Original construction cells stay scoped, hash-verified and formula-preserving."""

from contextlib import contextmanager
from hashlib import sha256
from types import SimpleNamespace

import pytest
from test_seg_expense_source import workbook

from finai_api.services import accounting_source_document, function_invocations
from finai_api.services.semantic_analysis_support import Resolver
from finai_api.services.workspace import WorkspaceError


@pytest.fixture
def source(monkeypatch):
    content = workbook()
    source_hash = sha256(content).hexdigest()
    scope = {"tenant_id": "tenant-test", "legal_entity": "company-test"}
    principal = SimpleNamespace(
        scope=SimpleNamespace(tenant_id=scope["tenant_id"], model_dump=lambda **_: scope)
    )
    resolver = Resolver(principal, {"function": {}, "static_dependencies": []})
    evidence = {"object_type": "SourceEvidence", "attributes": {"sha256": source_hash}}
    monkeypatch.setattr(resolver, "version", lambda _: evidence)
    state = {
        "receipt": {"receipt_id": "ir_original"},
        "queries": [],
        "reads": 0,
        "content": content,
        "metadata_hash": source_hash,
    }

    class Cursor:
        def execute(self, query, params=None):
            if query == "SET TRANSACTION READ ONLY":
                return self
            state["queries"].append((query, params))
            assert "tenant_id=%s" in query and "exact_scope=%s" in query
            assert params[0] == scope["tenant_id"] and params[1].obj == scope
            assert params[2] == source_hash
            return self

        def fetchall(self):
            return []

        def fetchone(self):
            return state["receipt"]

    @contextmanager
    def database(actual):
        assert actual is principal
        yield Cursor()

    def read(actual, receipt_id):
        assert actual is principal and receipt_id == "ir_original"
        state["reads"] += 1
        return {"document_id": receipt_id, "source_sha256": state["metadata_hash"]}, state[
            "content"
        ]

    monkeypatch.setattr(function_invocations, "_database", database)
    monkeypatch.setattr(accounting_source_document, "read_source", read)
    return resolver, state


def test_exact_source_cell_and_formula_cache_are_preserved(source):
    resolver, state = source
    original = resolver.source_cells({}, "Base!S2")
    formula = resolver.source_cells({}, "Base!AN2")
    assert original["document_id"] == "ir_original"
    assert original["cells"][0]["value"] == "731.97"
    assert original["cells"][0]["formula"] is None
    assert formula["cells"][0]["formula"] == "AD2-S2"
    assert formula["cells"][0]["value"] == "89.69000000000005"
    assert state["reads"] == 1
    assert len(state["queries"]) == 2


@pytest.mark.parametrize("changed", ["content", "metadata_hash"])
def test_changed_source_bytes_or_metadata_refused(source, changed):
    resolver, state = source
    state[changed] = b"changed" if changed == "content" else "a" * 64
    with pytest.raises(WorkspaceError, match="differ from original evidence"):
        resolver.source_cells({}, "Base!S2")


def test_no_visible_construction_is_unavailable_not_a_broader_lookup(source):
    resolver, state = source
    state["receipt"] = None
    assert resolver.source_cells({}, "Base!S2") is None
    assert state["reads"] == 0


def test_outside_coordinate_refused(source):
    resolver, _ = source
    with pytest.raises(WorkspaceError, match="outside the retained worksheet"):
        resolver.source_cells({}, "Base!Z999")


def test_unsupported_coordinate_is_not_guessed(source):
    resolver, state = source
    assert resolver.source_cells({}, "Sheet1!B189:C189") is None
    assert not state["queries"]
