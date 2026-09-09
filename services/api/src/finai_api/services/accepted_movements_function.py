"""Shared read-only Function adapter over the existing accepted movement producer."""

from datetime import datetime

from finai_api.domain.company_financial_metrics import FinancialMetricRequest
from finai_api.services import company_financial_metrics, semantic_analysis
from finai_api.services.workspace import WorkspaceError


def resolve(principal, request):
    selected = request.accepted_movements
    if selected is None or str(selected.company_id) != str(principal.scope.legal_entity_id):
        raise WorkspaceError(409, "Accepted movement input differs from selected company")
    history, _, resolver = semantic_analysis.load(principal, selected.source_invocation_id)
    query = history["output"].get("query", {})
    try:
        source_times = {key: datetime.fromisoformat(query[key]) for key in ("valid_at", "known_at")}
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkspaceError(409, "Retained source temporal context is unavailable") from exc
    if source_times != {"valid_at": request.valid_at, "known_at": request.known_at}:
        raise WorkspaceError(409, "Function times must equal the retained source times")
    result = company_financial_metrics.produce(
        principal,
        FinancialMetricRequest(
            invocation_id=selected.source_invocation_id,
            company_id=selected.company_id,
            snapshot_at=selected.journal_snapshot_at,
            expected_reconciliation_sha256=selected.expected_reconciliation_sha256,
            expected_result_sha256=selected.expected_result_sha256,
        ),
    )
    if (
        history["output"]["entity_movement_review"]["reconciliation"]["receipt_hash"]
        != result.source_receipt_hash
    ):
        raise WorkspaceError(409, "Accepted movements differ from retained source receipt")
    references = [result.selection["currency_id"], *[entry.journal for entry in result.journals]]
    contributors = [
        result.source_function.model_dump(mode="json"),
        result.binding.model_dump(mode="json"),
        result.nodes[0].subject.model_dump(mode="json"),
    ]
    with resolver.read_session():
        for reference in references:
            row = resolver.version(reference.model_dump(mode="json"))
            contributors.append(
                {key: str(row[key]) for key in ("resource_id", "version_id", "content_hash")}
            )
    unique = {row["resource_id"]: row for row in contributors}
    if len(unique) != len(contributors):
        raise WorkspaceError(409, "Accepted movement contributors contain duplicate identities")
    return result, history["receipt_hash"], sorted(contributors, key=lambda row: row["resource_id"])


def input_plan(principal, request, company):
    result, invocation_receipt_hash, contributors = resolve(principal, request)
    if result.nodes[0].subject.model_dump(mode="json") != company:
        raise WorkspaceError(409, "Function company differs from retained source company version")
    return {
        "source_invocation_id": str(result.invocation_id),
        "company_id": str(result.company_id),
        "selection": {
            key: value.model_dump(mode="json") for key, value in result.selection.items()
        },
        "source_function": result.source_function.model_dump(mode="json"),
        "binding": result.binding.model_dump(mode="json"),
        "source_receipt_hash": result.source_receipt_hash,
        "source_invocation_receipt_hash": invocation_receipt_hash,
        "contributors": contributors,
        "reconciliation_receipt_hash": result.reconciliation_receipt_hash,
        "result_sha256": result.result_sha256,
        "source_valid_at": request.valid_at.isoformat(),
        "source_known_at": request.known_at.isoformat(),
        "journal_observed_at": result.snapshot_at.isoformat(),
    }


def metric_outputs(result, request, contributors):
    from finai_api.domain.metric_execution import MetricOutput

    root = result.nodes[0]
    currency = next(
        row
        for row in contributors
        if row["resource_id"] == str(result.selection["currency_id"].resource_id)
    )
    return [
        MetricOutput(
            key=key,
            state=value.state,
            value=value.value,
            unit={"kind": "CURRENCY", "reference": currency},
            grain="COMPANY_MOVEMENTS",
            dimensions=[],
            company=root.subject.model_dump(mode="json"),
            valid_at=request.valid_at,
            known_at=request.known_at,
            coverage="COMPLETE" if result.coverage.state == "RECONCILED" else "PARTIAL",
            contributors=contributors,
        ).model_dump(mode="json")
        for key, value in root.metrics.items()
    ]


def execute(principal, request, plan):
    frozen = plan["accepted_movements"]
    result, invocation_receipt_hash, contributors = resolve(principal, request)
    if (
        result.result_sha256 != frozen["result_sha256"]
        or invocation_receipt_hash != frozen["source_invocation_receipt_hash"]
        or contributors != frozen["contributors"]
    ):
        raise WorkspaceError(409, "Accepted movement input changed after planning")
    outputs = metric_outputs(result, request, contributors)
    return {
        "contract": "function-result/1",
        "function": plan["function"],
        "implementation": plan["implementation"],
        "plan_hash": plan["plan_hash"],
        "static_dependencies": plan["static_dependencies"],
        "accepted_movements": frozen,
        "metric_outputs": outputs,
        "financial_metrics": result.model_dump(mode="json"),
        "returned_rows": len(outputs),
        "next_offset": None,
        "objects": [],
        "derived_values": [],
        "used_versions": [],
        "query": {
            "valid_at": request.valid_at.isoformat(),
            "known_at": request.known_at.isoformat(),
            "offset": request.offset,
            "limit": request.limit,
        },
        "journal_observed_at": result.snapshot_at.isoformat(),
        "coverage": "EXACT_SOURCE_MATCHED_ACCEPTED_JOURNAL_MOVEMENTS",
        "temporal_semantics": "RETAINED_SOURCE_TIMES_WITH_SEPARATE_JOURNAL_OBSERVATION",
        "mode": "EVIDENCE_ANALYSIS_ONLY",
        "business_effect_authorized": False,
        "current_use_authorized": False,
    }
