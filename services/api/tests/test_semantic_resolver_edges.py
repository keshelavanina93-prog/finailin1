"""Semantic evidence reads preserve exact versions, scope, missingness and resource bounds."""

import json
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
    with fixture.resolver.read_session():
        yield fixture


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
        "rows": [
            {
                "row": 2,
                "cells": [{"coordinate": "Base!S2", "value": 731.97, "formula": "SUM(A2:B2)"}],
            }
        ],
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
    assert calls[0][2:] == ("Base", 0, 50)
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


def test_adjacent_rows_share_verified_pages_without_leaking_other_rows(repository, monkeypatch):
    r = repository
    calls = []

    def preview(actor, document, sheet, offset, limit):
        assert actor is r.principal
        calls.append((document, sheet, offset, limit))
        return {
            "sha256": "b" * 64,
            "document_id": document,
            "rows": [
                {
                    "row": number,
                    "cells": [
                        {"coordinate": f"{sheet}!A{number}", "value": f"000{number}"},
                        {"coordinate": f"{sheet}!B{number}", "value": "ქართული", "formula": "A1"},
                    ],
                }
                for number in range(offset + 1, offset + limit + 1)
            ],
        }

    monkeypatch.setattr(source_document_preview, "preview", preview)
    for number in range(1, 247):
        result = r.resolver.source_cells(r.reference, f"Base!row:{number}")
        assert [cell["coordinate"] for cell in result["cells"]] == [
            f"Base!A{number}",
            f"Base!B{number}",
        ]
        assert result["cells"][0]["value"] == f"000{number}"
        assert result["cells"][1]["value"] == "ქართული"
        assert result["cells"][1]["formula"] == "A1"
    assert [call[2:] for call in calls] == [(0, 50), (50, 50), (100, 50), (150, 50), (200, 50)]
    assert sum("SELECT document_id" in query for query, _ in r.calls) == 1
    assert r.resolver.source_cells(r.reference, "Base!B2")["cells"] == [
        {
            "coordinate": "Base!B2",
            "label": "Base!B2 · Original worksheet value",
            "value": "ქართული",
            "formula": "A1",
        }
    ]


def test_cached_pages_require_each_exact_evidence_pin_and_source_lookup(repository, monkeypatch):
    r = repository
    calls = []

    def preview(actor, document, sheet, offset, limit):
        calls.append(document)
        return {
            "sha256": "b" * 64,
            "document_id": document,
            "rows": [{"row": 2, "cells": [{"coordinate": "Base!A2", "value": "001"}]}],
        }

    monkeypatch.setattr(source_document_preview, "preview", preview)
    r.resolver.source_cells(r.reference, "Base!A2")
    changed = r.reference.model_copy(update={"content_hash": "0" * 64})
    with pytest.raises(WorkspaceError, match="differs from its retained version"):
        r.resolver.source_cells(changed, "Base!A2")
    second = {**r.row, "version_id": uuid4(), "content_hash": "d" * 64}
    r.versions[(second["resource_id"], second["version_id"])] = second
    reference = {key: second[key] for key in ("resource_id", "version_id", "content_hash")}
    assert r.resolver.source_cells(reference, "Base!A2")["cells"][0]["value"] == "001"
    assert sum("SELECT document_id" in query for query, _ in r.calls) == 2
    assert len(calls) == 1  # Same authorized document and verified hash, distinct evidence pins.
    r.documents *= 2
    third = {**second, "version_id": uuid4()}
    r.versions[(third["resource_id"], third["version_id"])] = third
    with pytest.raises(WorkspaceError, match="ambiguous"):
        r.resolver.source_cells(third, "Base!A2")


@pytest.mark.parametrize("status", [404, 422, 403, 409, 503])
def test_unavailable_page_reuse_preserves_refusal_classes(repository, monkeypatch, status):
    r = repository
    calls = []

    def preview(*args):
        calls.append(args)
        raise WorkspaceError(status, "Retained source refused")

    monkeypatch.setattr(source_document_preview, "preview", preview)
    for number in (1, 2):
        if status in (404, 422):
            assert r.resolver.source_cells(r.reference, f"Base!A{number}") is None
        else:
            with pytest.raises(WorkspaceError) as refusal:
                r.resolver.source_cells(r.reference, f"Base!A{number}")
            assert refusal.value.status == status
    assert len(calls) == (1 if status in (404, 422) else 2)


@pytest.mark.parametrize("budget", ["reads", "bytes"])
def test_read_and_requested_row_byte_budgets_refuse_cache_growth(repository, monkeypatch, budget):
    r = repository
    if budget == "reads":
        r.resolver.source_preview_calls = 1000
    else:
        r.resolver.source_row_bytes = 8 * 1024 * 1024
    calls = []

    def preview(actor, document, *args):
        calls.append(document)
        return {"sha256": "b" * 64, "document_id": document, "rows": []}

    monkeypatch.setattr(source_document_preview, "preview", preview)
    with pytest.raises(WorkspaceError) as refusal:
        r.resolver.source_cells(r.reference, "Base!A2")
    assert refusal.value.status == 422
    assert not r.resolver.source_pages and not r.resolver.source_cache
    assert len(calls) == (1 if budget == "bytes" else 0)


def test_preview_document_substitution_refused_even_with_same_hash(repository, monkeypatch):
    monkeypatch.setattr(
        source_document_preview,
        "preview",
        lambda *args: {"sha256": "b" * 64, "document_id": "another-document", "rows": []},
    )
    with pytest.raises(WorkspaceError, match="differ from their source evidence"):
        repository.resolver.source_cells(repository.reference, "Base!A2")
    assert not repository.resolver.source_pages


def test_read_session_clears_original_pages_and_bytes_even_after_failure(repository, monkeypatch):
    r = repository
    resolver = Resolver(r.principal, {"function": {}, "static_dependencies": []})
    calls = []

    def preview(actor, document, *args):
        calls.append(document)
        return {
            "sha256": "b" * 64,
            "document_id": document,
            "rows": [{"row": 2, "cells": [{"coordinate": "Base!A2", "value": "ქართული"}]}],
        }

    monkeypatch.setattr(source_document_preview, "preview", preview)
    with pytest.raises(ValueError, match="exit"), resolver.read_session():
        resolver.source_cells(r.reference, "Base!A2")
        assert resolver.source_pages and resolver.source_documents and resolver.source_cache
        assert resolver.source_page_bytes == sum(
            len(json.dumps(page, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            for page in resolver.source_pages.values()
        )
        raise ValueError("exit")
    assert not resolver.source_pages and not resolver.source_documents and not resolver.source_cache
    assert (
        resolver.source_page_bytes
        == resolver.source_row_bytes
        == resolver.source_preview_calls
        == 0
    )
    assert not resolver.source_page_sizes
    with resolver.read_session():
        resolver.source_cells(r.reference, "Base!A2")
    assert len(calls) == 2


def test_single_long_cell_cannot_exceed_aggregate_byte_budget(repository, monkeypatch):
    r = repository
    monkeypatch.setattr(
        source_document_preview,
        "preview",
        lambda actor, document, *args: {
            "sha256": "b" * 64,
            "document_id": document,
            "rows": [{"row": 2, "cells": [{"coordinate": "Base!A2", "value": "ა" * 3_000_000}]}],
        },
    )
    with pytest.raises(WorkspaceError, match="byte inspection budget"):
        r.resolver.source_cells(r.reference, "Base!A2")
    assert not r.resolver.source_pages and r.resolver.source_page_bytes == 0


def test_sparse_rows_evict_pages_but_keep_only_exact_requested_rows(repository, monkeypatch):
    r = repository
    calls = []

    def preview(actor, document, sheet, offset, limit):
        calls.append(offset)
        return {
            "sha256": "b" * 64,
            "document_id": document,
            "rows": [
                {"row": n, "cells": [{"coordinate": f"{sheet}!A{n}", "value": f"00{n}"}]}
                for n in range(offset + 1, offset + limit + 1)
            ],
        }

    monkeypatch.setattr(source_document_preview, "preview", preview)
    requested = [1 + index * 100 for index in range(25)]
    retained = []
    for number in requested:
        retained.append(r.resolver.source_cells(r.reference, f"Base!A{number}"))
        assert len(r.resolver.source_pages) <= 20
        assert r.resolver.source_page_bytes + r.resolver.source_row_bytes <= 8 * 1024 * 1024
    assert len(calls) == 25
    assert all(len(page["rows"]) == 1 for page in r.resolver.source_cache.values())
    assert sorted(page["rows"][0]["row"] for page in r.resolver.source_cache.values()) == requested
    assert all(page["rows"][0]["row"] > 1 for page in r.resolver.source_pages.values())
    assert r.resolver.source_cells(r.reference, "Base!A1") == retained[0]
    assert len(calls) == 25  # A previously requested row survives its full-page eviction.
    assert r.resolver.source_cells(r.reference, "Base!A2")["cells"][0]["value"] == "002"
    assert len(calls) == 26 and len(r.resolver.source_pages) == 20
    assert r.resolver.source_preview_calls == 26


def test_byte_eviction_does_not_drop_small_requested_rows(repository, monkeypatch):
    r = repository

    def preview(actor, document, sheet, offset, limit):
        return {
            "sha256": "b" * 64,
            "document_id": document,
            "rows": [
                {
                    "row": offset + 1,
                    "cells": [{"coordinate": f"{sheet}!A{offset + 1}", "value": "001"}],
                },
                {
                    "row": offset + 2,
                    "cells": [{"coordinate": f"{sheet}!A{offset + 2}", "value": "a" * 1_000_000}],
                },
            ],
        }

    monkeypatch.setattr(source_document_preview, "preview", preview)
    for index in range(12):
        number = 1 + index * 100
        assert r.resolver.source_cells(r.reference, f"Base!A{number}")["cells"][0]["value"] == "001"
        assert r.resolver.source_page_bytes + r.resolver.source_row_bytes <= 8 * 1024 * 1024
    assert len(r.resolver.source_pages) < 12
    assert len(r.resolver.source_cache) == 12
    assert r.resolver.source_row_bytes < 10_000


def test_oversized_neighbor_is_not_retained_or_substituted_for_requested_row(
    repository, monkeypatch
):
    r = repository
    monkeypatch.setattr(
        source_document_preview,
        "preview",
        lambda actor, document, *args: {
            "sha256": "b" * 64,
            "document_id": document,
            "rows": [
                {"row": 1, "cells": [{"coordinate": "Base!A1", "value": "001"}]},
                {"row": 2, "cells": [{"coordinate": "Base!A2", "value": "ა" * 3_000_000}]},
            ],
        },
    )
    assert r.resolver.source_cells(r.reference, "Base!A1")["cells"][0]["value"] == "001"
    assert not r.resolver.source_pages and r.resolver.source_page_bytes == 0
    assert len(next(iter(r.resolver.source_cache.values()))["rows"]) == 1
    assert r.resolver.source_row_bytes < 1000


def test_document_residency_limit_evicts_instead_of_refusing_sparse_sources(
    repository, monkeypatch
):
    r = repository
    monkeypatch.setattr(
        source_document_preview,
        "preview",
        lambda actor, document, *args: {
            "sha256": "b" * 64,
            "document_id": document,
            "rows": [{"row": 1, "cells": [{"coordinate": "Base!A1", "value": "001"}]}],
        },
    )
    for index in range(10):
        assert (
            r.resolver._source_page(f"doc{index}", "b" * 64, "Base", 1)["document_id"]
            == f"doc{index}"
        )
        assert len({(key[0], key[1]) for key in r.resolver.source_pages}) <= 8
    assert len(r.resolver.source_pages) == 8
