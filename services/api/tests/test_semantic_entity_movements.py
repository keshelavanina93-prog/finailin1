from contextlib import nullcontext
from copy import deepcopy
from uuid import uuid4

import pytest
from test_entity_movement_review import fixture

from finai_api.domain.semantic_analysis import ProjectionRequest
from finai_api.services import semantic_analysis
from finai_api.services.entity_movement_review import review
from finai_api.services.posted_movements_function import calculate
from finai_api.services.semantic_analysis_support import digest, pin
from finai_api.services.workspace import WorkspaceError


@pytest.fixture
def case(monkeypatch):
    parsed, source, targets, ids = fixture()
    for ref in source["accounts"].values():
        old = targets.pop(ref["resource_id"])
        ref.update(resource_id=str(uuid4()), version_id=str(uuid4()))
        old.update(ref)
        targets[ref["resource_id"]] = old
    targets[ids["company"]] = {"object_type": "LegalEntity", "attributes": {}}
    evidence_id, function_id = str(uuid4()), str(uuid4())
    targets[evidence_id] = {
        "object_type": "SourceEvidence",
        "attributes": {"sha256": source["sha256"]},
    }
    targets[function_id] = {
        "object_type": "FunctionDefinition",
        "attributes": {"definition": {"entity_movement_review": True}},
    }
    targets[ids["scope"]]["object_type"] = "SourceAccountingScope"
    for identity, row in targets.items():
        row.setdefault("resource_id", identity)
        row.setdefault("version_id", str(uuid4()))
        row.setdefault("display_name", row["object_type"])
        row["content_hash"] = digest(row["attributes"])
    for key in ("binding", "scope"):
        source[key] = pin(targets[source[key]["resource_id"]]).model_dump(mode="json")
    source["evidence"] = pin(targets[evidence_id]).model_dump(mode="json")
    source["document_id"] = "ir_" + "1" * 64
    source["entity_movement_review"] = {"policies": {}}
    output = {
        "source_document": source,
        "source_rows": parsed["rows"],
        "source_headers": parsed["headers"],
        "posted_movements": calculate(parsed, source),
        "entity_movement_review": review(parsed, source, targets, {}),
        "run_id": "fcr_" + "2" * 64,
        "authority": "GUARDED_POSTED_MOVEMENT_ANALYSIS",
        "coverage": "RETAINED_SOURCE_POSTINGS_WITH_EXPLICIT_EXCLUSIONS",
        "query": {"valid_at": "2026-09-08T00:00:00Z", "known_at": "2026-09-08T00:00:00Z"},
    }
    history = {
        "invocation_id": str(uuid4()),
        "receipt_hash": "3" * 64,
        "receipt": {"recorded_at": "2026-09-08T00:00:01Z"},
        "output": output,
    }
    plan = {
        "source_document": deepcopy(source),
        "function": pin(targets[function_id]).model_dump(mode="json"),
        "static_dependencies": [pin(r).model_dump(mode="json") for r in targets.values()],
        "implementation": {"implementation_id": "accounting.retained-posted-movements/v1"},
    }

    class Resolver:
        def read_session(self):
            return nullcontext(self)

        def version(self, ref):
            return targets[str(ref["resource_id"])]

        def field(self, row, name):
            return targets[row["attributes"][name]]

    monkeypatch.setattr(semantic_analysis, "require_permission", lambda *_: None)
    monkeypatch.setattr(semantic_analysis, "load", lambda *_: (history, plan, Resolver()))
    return history, ProjectionRequest(
        invocation_id=history["invocation_id"], company_id=ids["company"]
    )


def test_same_workspace_exact_movement_selection_and_refusals(case):
    history, request = case
    result = semantic_analysis.project(None, request)
    assert result.descriptor.measure is None and len(result.rows) == 2
    assert result.descriptor.contract == "semantic-analysis/2"
    assert result.descriptor.visual == "NONE"
    assert result.descriptor.row_noun == "objects"
    assert all(field.aggregation == "NONE" for field in result.descriptor.fields)
    assert [field.role for field in result.descriptor.fields] == [
        "ATTRIBUTE",
        "DIMENSION",
        "ATTRIBUTE",
        "ATTRIBUTE",
        "ATTRIBUTE",
    ]
    assert {r.values["net_movement"].value for r in result.rows} == {"731.97", "-731.97"}
    selected = semantic_analysis.project(
        None,
        request.model_copy(
            update={
                "descriptor_sha256": result.descriptor_sha256,
                "selected_row": result.rows[0].key,
            }
        ),
    )
    assert selected.selection.contributor.coordinate == "Base!S2"
    assert any("not a trial balance" in text for text in result.descriptor.unavailable_operations)
    with pytest.raises(WorkspaceError):
        semantic_analysis.project(None, request.model_copy(update={"company_id": uuid4()}))
    with pytest.raises(WorkspaceError):
        semantic_analysis.project(None, request.model_copy(update={"descriptor_sha256": "0" * 64}))
    history["output"]["entity_movement_review"]["movements"][0]["net_movement"] = "999"
    with pytest.raises(WorkspaceError, match="reconciliation"):
        semantic_analysis.project(None, request)


def test_code_and_multilingual_retained_name_are_distinct_nonaggregating_columns(case):
    history, request = case
    _, plan, resolver = semantic_analysis.load(None, request.invocation_id)
    account_ref = history["output"]["source_document"]["accounts"]["0012.01"]
    account = resolver.version(account_ref)
    account["display_name"] = "0012.01 · მიმდინარე ანგარიში / Расчётный счёт"
    retained_history = deepcopy(history)
    retained_plan = deepcopy(plan)
    result = semantic_analysis.project(None, request)
    code, name = result.descriptor.fields[:2]
    assert (code.key, code.label, code.kind, code.role, code.aggregation) == (
        "account_code", "Account code", "identifier", "ATTRIBUTE", "NONE"
    )
    assert not code.filterable and not code.groupable
    assert (name.key, name.label, name.kind, name.role) == (
        "account", "Account name", "reference", "DIMENSION"
    )
    assert result.descriptor.grain == ["account"]
    row = next(row for row in result.rows if row.values["account_code"].value == "0012.01")
    assert row.values["account"].label == account["display_name"]
    assert row.values["account"].reference == pin(account)
    assert row.values["account"].value == account_ref["resource_id"]
    assert row.trace == pin(account)
    selected = semantic_analysis.project(None, ProjectionRequest.model_validate({
        **request.model_dump(),
        "descriptor_sha256": result.descriptor_sha256,
        "filters": [{"field": "account", "value": account_ref["resource_id"]}],
        "selected_row": row.key,
    }))
    assert selected.rows == [row]
    assert selected.selection.contributor.coordinate == "Base!S2"
    assert row.values["debit_movement"].value == "731.97"
    assert history == retained_history and plan == retained_plan


@pytest.mark.parametrize("code", [None, "", "12.01", 12])
def test_missing_or_altered_canonical_code_does_not_fall_back_to_display_name(case, code):
    history, request = case
    _, _, resolver = semantic_analysis.load(None, request.invocation_id)
    account = resolver.version(history["output"]["source_document"]["accounts"]["0012.01"])
    account["display_name"] = "0012.01 · Retained account name"
    if code is None:
        del account["attributes"]["account_code"]
    else:
        account["attributes"]["account_code"] = code
    with pytest.raises(WorkspaceError, match="exact chart membership") as refused:
        semantic_analysis.project(None, request)
    assert refused.value.status == 409


def test_old_column_descriptor_revision_is_refused_without_changing_retained_evidence(case):
    history, request = case
    retained = deepcopy(history)
    current = semantic_analysis.project(None, request)
    old_descriptor = current.descriptor.model_copy(update={
        "fields": [
            field.model_copy(update={"label": "Account"}) if field.key == "account" else field
            for field in current.descriptor.fields if field.key != "account_code"
        ]
    })
    old_rows = [row.model_copy(update={
        "values": {key: value for key, value in row.values.items() if key != "account_code"}
    }) for row in current.rows]
    old_revision = digest({
        "descriptor": old_descriptor.model_dump(mode="json"),
        "rows": [row.model_dump(mode="json") for row in old_rows],
    })
    assert old_revision != current.descriptor_sha256
    with pytest.raises(WorkspaceError, match="descriptor changed") as refused:
        semantic_analysis.project(None, request.model_copy(update={
            "descriptor_sha256": old_revision, "selected_row": current.rows[0].key,
        }))
    assert refused.value.status == 409
    assert history == retained
