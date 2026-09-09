"""Read one sealed source exception without proposing, replaying or closing anything."""

import re
from datetime import datetime

from finai_api.domain.company_financial_metrics import FinancialMetricRequest
from finai_api.domain.source_reconciliation_exception import SourceExceptionObservation
from finai_api.security import require_permission
from finai_api.services import (
    company_financial_metrics,
    fact_runs,
    journal_reconciliation,
    semantic_analysis,
)
from finai_api.services.entity_movement_review import digest
from finai_api.services.workspace import WorkspaceError

RUNTIME = "source-reconciliation-exceptions/1"


def compile_observation(request, reconciliation, source_projection, history, context_versions):
    """Internal reducer. Inputs come from existing verified retained-source readers."""
    # Reuse the existing sealed receipt, accounting scope and membership validation.
    metric = company_financial_metrics.compute(
        FinancialMetricRequest(
            invocation_id=request.invocation_id,
            company_id=request.company_id,
            snapshot_at=request.journal_snapshot_at,
            expected_reconciliation_sha256=request.expected_reconciliation_receipt_hash,
        ),
        reconciliation,
        source_projection,
    )
    try:
        output = history["output"]
        source = output["source_document"]
        review = output["entity_movement_review"]
        descriptor = (
            source_projection.descriptor if hasattr(source_projection, "descriptor") else None
        )
        if descriptor is None:
            from finai_api.domain.semantic_analysis import Projection

            descriptor = Projection.model_validate(source_projection).descriptor
        if (
            str(history["invocation_id"]) != str(request.invocation_id)
            or history["receipt_hash"] != descriptor.receipt_hash
            or str(source["company_id"]) != str(request.company_id)
            or source["sha256"] != metric.source_sha256
            or source["binding"] != metric.binding.model_dump(mode="json")
            or review["reconciliation"]["receipt_hash"] != metric.source_receipt_hash
            or review["reconciliation"]["excluded_rows"] != reconciliation["excluded_rows"]
        ):
            raise WorkspaceError(409, "Exception source differs from its retained reconciliation")
        context = {str(row["resource_id"]): row for row in context_versions}
        if len(context) != 7 or any(
            key not in context or str(context[key]["version_id"]) != str(ref.version_id)
            for ref in metric.selection.values()
            for key in [str(ref.resource_id)]
        ):
            raise WorkspaceError(409, "Exception context differs from exact selection versions")
        for pinned in [metric.nodes[0].subject, *descriptor.definitions]:
            selected = context.get(str(pinned.resource_id))
            if selected is not None and selected != pinned.model_dump(mode="json"):
                raise WorkspaceError(
                    409, "Exception context content differs from retained definitions"
                )
        if any(
            datetime.fromisoformat(output["query"][key])
            != datetime.fromisoformat(str(getattr(descriptor, key)))
            for key in ("valid_at", "known_at")
        ):
            raise WorkspaceError(409, "Exception source clocks differ from retained projection")
        pairs = {row["source_coordinate"]: row for row in review["pairs"]}
        exclusions = {row["coordinate"]: row for row in reconciliation["excluded_rows"]}
        accepted = {row["source_coordinate"]: row for row in reconciliation["accepted"]}
        if (
            len(pairs) != len(review["pairs"])
            or set(pairs) != set(reconciliation["missing_coordinates"]) | set(accepted)
            or set(pairs) & set(exclusions)
        ):
            raise WorkspaceError(409, "Exception source coordinate coverage differs")
        coordinate = request.coordinate
        if coordinate not in pairs and coordinate not in exclusions:
            raise WorkspaceError(
                404, "Source coordinate is not an authoritative posting coordinate"
            )
        row_number = (
            pairs[coordinate]["source_row"]
            if coordinate in pairs
            else exclusions[coordinate]["row"]
        )
        raw_rows = [row for row in output["source_rows"] if row["row"] == row_number]
        if (
            len(raw_rows) != 1
            or coordinate.rsplit("!", 1)[0] != source["sheet"]
            or int(re.search(r"[0-9]+$", coordinate)[0]) != row_number
        ):
            raise WorkspaceError(409, "Exact retained source row is unavailable")
        observation = raw_rows[0]["numeric_observations"].get("source_amount", {})
        if coordinate in pairs and observation.get("coordinate") != coordinate:
            raise WorkspaceError(409, "Source amount coordinate differs from retained row")
        excluded = coordinate in exclusions
        state = (
            "EXCLUDED_SOURCE_VALUE"
            if excluded
            else "MATCHED_AT_SNAPSHOT"
            if coordinate in accepted
            else "UNMATCHED_AT_SNAPSHOT"
        )
        result = SourceExceptionObservation(
            company=metric.nodes[0].subject,
            selection=metric.selection,
            binding=metric.binding,
            context_versions=sorted(context_versions, key=lambda row: str(row["resource_id"])),
            source_function=metric.source_function,
            source={
                "invocation_id": request.invocation_id,
                "invocation_receipt_hash": history["receipt_hash"],
                "source_receipt_hash": metric.source_receipt_hash,
                "sha256": source["sha256"],
                "evidence": source["evidence"],
                "document_id": source["document_id"],
                "sheet": source["sheet"],
                "row": row_number,
                "coordinate": coordinate,
            },
            source_valid_at=output["query"]["valid_at"],
            source_known_at=output["query"]["known_at"],
            journal_observed_at=request.journal_snapshot_at,
            reconciliation={
                "receipt_hash": reconciliation["receipt_hash"],
                "status": reconciliation["status"],
            },
            state=state,
            finding_eligible=state == "UNMATCHED_AT_SNAPSHOT",
            exclusion_reason=exclusions[coordinate]["reason"] if excluded else None,
            matched_journals=[accepted[coordinate]["journal"]] if coordinate in accepted else [],
            receipt_hash="0" * 64,
        )
        return result.model_copy(
            update={
                "receipt_hash": digest(result.model_dump(mode="json", exclude={"receipt_hash"}))
            }
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkspaceError(409, "Retained exception evidence is incomplete or invalid") from exc


def resolve(principal, request):
    require_permission(principal, "ontology_read")
    if str(request.company_id) != str(principal.scope.legal_entity_id):
        raise WorkspaceError(404, "Source exception unavailable in selected company")
    reconciled = journal_reconciliation.reconcile(
        principal,
        request.invocation_id,
        request.company_id,
        request.journal_snapshot_at,
    )
    history, _, resolver = semantic_analysis.load(principal, request.invocation_id)
    with resolver.read_session():
        context = [
            resolver.version(ref) for ref in reconciled["reconciliation"]["selection"].values()
        ]
    context_versions = [
        {key: str(row[key]) for key in ("resource_id", "version_id", "content_hash")}
        for row in context
    ]
    return compile_observation(
        request,
        reconciled["reconciliation"],
        reconciled["source_projection"],
        history,
        context_versions,
    )


def retain(principal, request):
    return fact_runs.retain_run(
        principal, resolve(principal, request).model_dump(mode="json"), runtime=RUNTIME
    )


def read(principal, run_id):
    require_permission(principal, "ontology_read")
    if not re.fullmatch(r"fcr_[a-f0-9]{64}", run_id):
        raise WorkspaceError(422, "Invalid source exception run identity")
    payload = fact_runs.read_run(principal, run_id)
    if (
        payload.get("contract") != "source-reconciliation-exception/1"
        or payload.get("calculation_runtime") != RUNTIME
        or payload.get("run_id") != run_id
        or payload.get("scope") != principal.scope.model_dump(mode="json")
    ):
        raise WorkspaceError(404, "Source exception unavailable in this exact scope")
    try:
        observation = SourceExceptionObservation.model_validate(
            {
                key: value
                for key, value in payload.items()
                if key not in {"run_id", "scope", "calculation_runtime", "read_permissions"}
            }
        )
        if (
            str(observation.company.resource_id) != str(principal.scope.legal_entity_id)
            or digest(observation.model_dump(mode="json", exclude={"receipt_hash"}))
            != observation.receipt_hash
        ):
            raise ValueError("Source exception receipt or company differs")
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkspaceError(409, "Retained source exception failed verification") from exc
    return payload
