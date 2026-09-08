"""Offline shared Function adapter guards and exact reuse of finance computation."""

# ruff: noqa: F811
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_company_financial_metrics import metric_case, run  # noqa: F401
from test_semantic_entity_movements import case as workspace_case  # noqa: F401

from finai_api.domain.authority import ExactScope
from finai_api.domain.function_execution import FunctionInvocation
from finai_api.domain.review import Principal
from finai_api.services import accepted_movements_function as adapter
from finai_api.services import function_execution as functions
from finai_api.services.workspace import WorkspaceError


@pytest.fixture
def accepted_case(metric_case, monkeypatch):
    original, _receipt, _projection = metric_case
    metric = run(metric_case)
    history, _, resolver = adapter.semantic_analysis.load(None, original.invocation_id)
    query = history["output"]["query"]
    request = FunctionInvocation(
        function={"resource_id": uuid4(), "version_id": uuid4()},
        valid_at=query["valid_at"],
        known_at=query["known_at"],
        accepted_movements={
            "source_invocation_id": original.invocation_id,
            "company_id": original.company_id,
            "journal_snapshot_at": original.snapshot_at,
            "expected_reconciliation_sha256": metric.reconciliation_receipt_hash,
            "expected_result_sha256": metric.result_sha256,
        },
    )
    original_version = resolver.version
    journals = {
        str(j.journal.resource_id): {**j.journal.model_dump(mode="json"), "content_hash": "a" * 64}
        for j in metric.journals
    }
    monkeypatch.setattr(
        resolver, "version", lambda ref: journals.get(ref["resource_id"]) or original_version(ref)
    )
    monkeypatch.setattr(adapter.semantic_analysis, "load", lambda *_: (history, {}, resolver))

    def produce(principal, selected):
        assert selected == original.model_copy(
            update={
                "expected_reconciliation_sha256": metric.reconciliation_receipt_hash,
                "expected_result_sha256": metric.result_sha256,
            }
        )
        return metric

    monkeypatch.setattr(adapter.company_financial_metrics, "produce", produce)
    principal = Principal(
        actor_id="adapter-test",
        display_name="Adapter test",
        permissions=("ontology_read",),
        scope=ExactScope(
            tenant_id=uuid4(),
            legal_entity_id=str(original.company_id),
            period="2025-01",
            currency="GEL",
        ),
    )
    company = metric.nodes[0].subject.model_dump(mode="json")
    return principal, request, metric, company, history


def test_input_plan_pins_source_and_journal_times_separately(accepted_case):
    principal, request, metric, company, history = accepted_case
    assert isinstance(principal, Principal) and isinstance(principal.scope, ExactScope)
    assert isinstance(principal.scope.legal_entity_id, str)
    plan = adapter.input_plan(principal, request, company)
    assert plan["source_invocation_receipt_hash"] == history["receipt_hash"]
    assert plan["source_receipt_hash"] == metric.source_receipt_hash
    assert plan["result_sha256"] == metric.result_sha256
    assert plan["source_valid_at"] == request.valid_at.isoformat()
    assert plan["journal_observed_at"] == metric.snapshot_at.isoformat()
    assert len(plan["contributors"]) == 5


@pytest.mark.parametrize("failure", ["company", "version", "time", "missing_time", "receipt"])
def test_adapter_refuses_mismatched_authority_and_time(accepted_case, failure):
    principal, request, _metric, company, history = accepted_case
    if failure == "company":
        principal = principal.model_copy(
            update={"scope": principal.scope.model_copy(update={"legal_entity_id": str(uuid4())})}
        )
    elif failure == "version":
        company["version_id"] = str(uuid4())
    elif failure == "time":
        request = request.model_copy(update={"valid_at": request.valid_at.replace(year=2025)})
    elif failure == "missing_time":
        history["output"]["query"] = {}
    else:
        history["output"]["entity_movement_review"]["reconciliation"]["receipt_hash"] = "0" * 64
    with pytest.raises(WorkspaceError):
        adapter.input_plan(principal, request, company)


@pytest.mark.parametrize("failure", ["caller_amount", "naive", "paging", "mixed", "self"])
def test_typed_input_forbids_numbers_paging_and_ambiguous_inputs(accepted_case, failure):
    request = accepted_case[1].model_dump(mode="json")
    if failure == "caller_amount":
        request["accepted_movements"]["amount"] = "1"
    elif failure == "naive":
        request["accepted_movements"]["journal_snapshot_at"] = "2025-01-01T00:00:00"
    elif failure == "paging":
        request["offset"] = 1
    elif failure == "mixed":
        request["input_result"] = {"invocation_id": str(uuid4())}
    else:
        request["accepted_movements"]["source_invocation_id"] = request["request_id"]
    with pytest.raises(ValidationError):
        FunctionInvocation.model_validate(request)


def test_output_reuses_root_values_and_preserves_full_drill(accepted_case):
    principal, request, metric, company, _ = accepted_case
    plan = {
        "accepted_movements": adapter.input_plan(principal, request, company),
        "function": request.function.model_dump(mode="json"),
        "implementation": {"implementation_id": functions.ACCEPTED_MOVEMENTS_IMPLEMENTATION_ID},
        "plan_hash": "f" * 64,
        "static_dependencies": [company],
    }
    result = adapter.execute(principal, request, plan)
    assert result["financial_metrics"] == metric.model_dump(mode="json")
    assert len(result["metric_outputs"]) == 3
    for output in result["metric_outputs"]:
        value = metric.nodes[0].metrics[output["key"]]
        assert (output["state"], output["value"]) == (value.state, value.value)
        assert output["company"] == company
        assert output["grain"] == "COMPANY_MOVEMENTS" and output["dimensions"] == []
    changed = deepcopy(plan)
    changed["accepted_movements"]["result_sha256"] = "0" * 64
    with pytest.raises(WorkspaceError, match="changed after planning"):
        adapter.execute(principal, request, changed)


@pytest.fixture
def registered_case(accepted_case, monkeypatch):
    from contextlib import nullcontext

    principal, request, metric, company, _history = accepted_case
    executable = functions.manifest(functions.ACCEPTED_MOVEMENTS_IMPLEMENTATION_ID)
    definition = {
        key: executable[key]
        for key in ("implementation_id", "determinism", "code_sha256", "dependency_sha256")
    }
    definition["company"] = {key: company[key] for key in ("resource_id", "version_id")}
    function = {
        **request.function.model_dump(mode="json"),
        "content_hash": "b" * 64,
        "object_type": "FunctionDefinition",
        "access_entity": str(request.accepted_movements.company_id),
        "attributes": {"definition": definition},
    }
    canonical_company = {**company, "object_type": "LegalEntity"}
    cursor = SimpleNamespace(
        execute=lambda *a: SimpleNamespace(fetchall=lambda: [canonical_company])
    )
    connection = SimpleNamespace(cursor=lambda **k: nullcontext(cursor))
    monkeypatch.setattr(functions, "resource_connection", lambda *_: nullcontext(connection))
    monkeypatch.setattr(functions, "_current", lambda *_: function)
    monkeypatch.setattr(functions, "require_permission", lambda *_: None)
    monkeypatch.setattr(functions, "upstream_authority", lambda *a, **k: [])
    return principal, request, metric, function, canonical_company


def test_registered_plan_dispatch_and_stale_code_historical_read(registered_case, monkeypatch):
    from finai_api.services import function_invocations

    principal, request, metric, function, _ = registered_case
    plan = functions.plan(principal, request)
    output = functions.execute_plan(principal, plan)
    assert output["financial_metrics"] == metric.model_dump(mode="json")
    assert output["plan_hash"] == plan["plan_hash"]
    function["attributes"]["definition"]["code_sha256"] = "0" * 64
    with pytest.raises(WorkspaceError, match="installed executable"):
        functions.execute_plan(principal, plan)
    historical = {"status": "SUCCEEDED", "output": output}
    monkeypatch.setattr(function_invocations, "require_permission", lambda *_: None)
    monkeypatch.setattr(function_invocations, "_terminal", lambda *_: historical)
    assert function_invocations.history(principal, request.request_id)["output"] == output


@pytest.mark.parametrize(
    "failure", ["company_version", "company_scope", "missing_input", "other_adapter"]
)
def test_shared_plan_refuses_wrong_company_or_adapter(registered_case, failure):
    principal, request, _, function, company = registered_case
    if failure == "company_version":
        company["version_id"] = str(uuid4())
    elif failure == "company_scope":
        principal = principal.model_copy(
            update={"scope": principal.scope.model_copy(update={"legal_entity_id": str(uuid4())})}
        )
    elif failure == "missing_input":
        request = request.model_copy(update={"accepted_movements": None})
    else:
        manifest = functions.manifest()
        function["attributes"] = {
            "object_set_id": str(uuid4()),
            "definition": {
                key: manifest[key]
                for key in ("implementation_id", "determinism", "code_sha256", "dependency_sha256")
            },
        }
    with pytest.raises(WorkspaceError):
        functions.plan(principal, request)


@pytest.mark.parametrize("state", ["PARTIAL", "UNAVAILABLE"])
def test_partial_and_missing_outputs_preserve_coverage_and_null(
    accepted_case, metric_case, monkeypatch, state
):
    principal, request, _, company, _ = accepted_case
    receipt = metric_case[1]
    if state == "UNAVAILABLE":
        receipt.update(
            status=state,
            accepted=[],
            missing_coordinates=["Base!S2"],
            movement_trial_balance=None,
            matched_source_amount=None,
            journal_debit_total=None,
            journal_credit_total=None,
        )
    else:
        receipt.update(status=state, missing_coordinates=["Base!S3"])
    metric = run(metric_case)
    _, source_receipt, contributors = adapter.resolve(principal, request)
    monkeypatch.setattr(adapter, "resolve", lambda *_: (metric, source_receipt, contributors))
    plan = {
        "accepted_movements": adapter.input_plan(principal, request, company),
        "function": request.function.model_dump(mode="json"),
        "implementation": {},
        "plan_hash": "f" * 64,
        "static_dependencies": [],
    }
    output = adapter.execute(principal, request, plan)
    assert all(row["coverage"] == "PARTIAL" for row in output["metric_outputs"])
    assert all(row["value"] is None for row in output["metric_outputs"]) == (state == "UNAVAILABLE")
