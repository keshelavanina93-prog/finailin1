"""Semantic evidence reads preserve exact versions, scope, missingness and resource bounds."""

from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from finai_api.domain.authority import ExactScope
from finai_api.domain.semantic_analysis import Pin
from finai_api.services import function_invocations, source_document_preview
from finai_api.services.semantic_analysis_support import Resolver
from finai_api.services.workspace import WorkspaceError


@pytest.fixture
def repository(monkeypatch):
    principal = SimpleNamespace(
        scope=ExactScope(
            tenant_id=uuid4(),
            legal_entity_id="synthetic-resolver",
            period="2026-08",
            currency="GEL",
        )
    )
    identity, version = uuid4(), uuid4()
    row = {
        "resource_id": identity,
        "version_id": version,
        "content_hash": "a" * 64,
        "object_type": "SourceEvidence",
        "display_name": "Exact source evidence",
        "attributes": {"sha256": "b" * 64},
    }
    reference = Pin.model_validate(
        {
            key: row[key]
            for key in (
                "resource_id",
                "version_id",
                "content_hash",
            )
        }
    )
    fixture = SimpleNamespace(
        principal=principal,
        row=row,
        reference=reference,
        versions={(identity, version): row},
        dependencies=[],
        documents=[{"document_id": "doc_" + "c" * 64}],
        calls=[],
    )

    class Cursor:
        def execute(self, query, args=None):
            fixture.calls.append((query, args))
            assert "resource_heads" not in query
            if args:
                assert args[0] == principal.scope.tenant_id
            if "SELECT v.*" in query:
                self.one = fixture.versions.get((args[1], args[2]))
            elif "SELECT d.relation" in query:
                self.rows = fixture.dependencies
            elif "SELECT document_id" in query:
                assert args[1].obj == principal.scope.model_dump(mode="json")
                assert args[2] == row["attributes"]["sha256"]
                self.rows = fixture.documents
            return self

        def fetchone(self):
            return self.one

        def fetchall(self):
            return self.rows

    @contextmanager
    def database(actor):
        assert actor is principal
        yield Cursor()

    monkeypatch.setattr(function_invocations, "_database", database)
    fixture.resolver = Resolver(
        principal,
        {
            "static_dependencies": [],
            "function": reference.model_dump(mode="json"),
        },
    )
    return fixture


def test_exact_versions_cache_independently_and_ambiguous_identity_is_refused(repository):
    r = repository
    resolver = r.resolver
    assert resolver.version(r.reference)["version_id"] == r.row["version_id"]
    assert resolver.version(r.reference) is resolver.version(r.reference)
    changed = r.reference.model_copy(update={"content_hash": "0" * 64})
    with pytest.raises(WorkspaceError, match="differs from its retained version"):
        resolver.version(changed)
    second = {**r.row, "version_id": uuid4(), "content_hash": "d" * 64}
    r.versions[(second["resource_id"], second["version_id"])] = second
    ref2 = {key: second[key] for key in ("resource_id", "version_id", "content_hash")}
    assert resolver.version(ref2)["content_hash"] == "d" * 64
    assert resolver.reference_value(r.row["resource_id"]).label == "Exact source evidence"
    resolver.pins.append(ref2)
    with pytest.raises(WorkspaceError, match="one exact retained"):
        resolver.for_id(r.row["resource_id"])
    with pytest.raises(WorkspaceError, match="one exact retained"):
        resolver.for_id(uuid4())
    assert sum("SELECT v.*" in query for query, _ in r.calls) == 2


def test_invisible_and_over_budget_versions_never_fall_back_to_current(repository):
    r = repository
    with pytest.raises(WorkspaceError) as hidden:
        r.resolver.version({"resource_id": uuid4(), "version_id": uuid4()})
    assert hidden.value.status == 404
    r.resolver.cache = {(UUID(int=index), UUID(int=index)): {} for index in range(2000)}
    before = len(r.calls)
    with pytest.raises(WorkspaceError) as limited:
        r.resolver.version(r.reference)
    assert limited.value.status == 422 and len(r.calls) == before


def test_reference_fields_require_one_matching_retained_dependency(repository):
    r = repository
    target = uuid4()
    r.row["attributes"]["company_id"] = str(target)
    r.dependencies = [
        {"relation": "FIELD:company_id", "resource_id": target, "version_id": uuid4()}
    ]
    assert r.resolver.field(r.row, "company_id")["resource_id"] == target
    assert r.resolver.dependencies(r.reference) is r.resolver.dependencies(r.reference)
    with pytest.raises(WorkspaceError, match="exact retained reference"):
        r.resolver.field(r.row, "unavailable")
    r.dependencies.append(dict(r.dependencies[0]))
    with pytest.raises(WorkspaceError, match="exact retained reference"):
        r.resolver.field(r.row, "company_id")
    assert sum("SELECT d.relation" in query for query, _ in r.calls) == 1


def test_original_cells_preserve_formula_cached_value_and_coordinate(repository, monkeypatch):
    r = repository
    page = {
        "sha256": "b" * 64,
        "document_id": "doc_" + "c" * 64,
        "rows": [{"cells": [{"coordinate": "Base!S2", "value": 731.97, "formula": "SUM(A2:B2)"}]}],
    }
    calls = []

    def preview(actor, document, sheet, offset, limit):
        calls.append((actor, document, sheet, offset, limit))
        return page

    monkeypatch.setattr(source_document_preview, "preview", preview)
    cells = r.resolver.source_cells(r.reference, "Base!S2")
    assert cells["cells"][0]["value"] == "731.97"
    assert cells["cells"][0]["formula"] == "SUM(A2:B2)"
    assert cells["source_sha256"] == "b" * 64
    assert calls[0][2:] == ("Base", 1, 1)
    assert r.resolver.source_cells(r.reference, "Base!row:2")["cells"] == cells["cells"]
    assert len(calls) == 1
    with pytest.raises(WorkspaceError, match="outside the retained"):
        r.resolver.source_cells(r.reference, "Base!Z2")
    assert r.resolver.source_cells(r.reference, "not-a-coordinate") is None


@pytest.mark.parametrize("failure", ["ambiguous", "hash", "404", "422", "503", "type", "budget"])
def test_source_ambiguity_changed_hash_and_unavailable_evidence_are_explicit(
    repository, monkeypatch, failure
):
    r = repository
    if failure == "ambiguous":
        r.documents *= 2
    elif failure == "type":
        r.row["object_type"] = "Mapping"
    elif failure == "budget":
        r.resolver.source_cache = {(str(index), "Sheet", "1"): None for index in range(1000)}
    original = deepcopy(r.row)

    def preview(*_):
        if failure.isdigit():
            raise WorkspaceError(int(failure), "Controlled source unavailable")
        return {"sha256": "0" * 64}

    monkeypatch.setattr(source_document_preview, "preview", preview)
    if failure in {"404", "422"}:
        assert r.resolver.source_cells(r.reference, "Base!S2") is None
    else:
        with pytest.raises(WorkspaceError) as rejected:
            r.resolver.source_cells(r.reference, "Base!S2")
        assert rejected.value.status == (
            422 if failure == "budget" else 503 if failure == "503" else 409
        )
    assert r.row == original  # A refusal never proposes or mutates source evidence.
