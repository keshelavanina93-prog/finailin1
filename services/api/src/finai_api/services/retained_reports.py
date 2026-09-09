"""Immutable report drafts over exact retained results; no financial execution."""

import json
from collections.abc import Callable
from datetime import datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

from finai_api.domain.authority import canonical_sha256
from finai_api.domain.resources import ProposalDetail, ResourceMutation, ResourceProposal
from finai_api.domain.retained_reports import (
    ReportComposition,
    ReportPreview,
    RetainedReportDefinition,
    RetainedReportSnapshot,
    SaveRetainedReport,
)
from finai_api.domain.review import Principal
from finai_api.domain.semantic_analysis import Pin
from finai_api.security import require_permission
from finai_api.services import company_context, resources
from finai_api.services.workspace import WorkspaceError

MAX_BYTES = 16_000_000


def digest(value: Any) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def _definition(item: ResourceMutation) -> RetainedReportDefinition:
    try:
        definition = RetainedReportDefinition.model_validate(item.attributes["definition"])
    except (ValueError, KeyError, TypeError) as exc:
        raise WorkspaceError(422, "Invalid retained report definition") from exc
    if len(json.dumps(item.model_dump(mode="json"), ensure_ascii=True).encode()) > MAX_BYTES:
        raise WorkspaceError(422, "Report exceeds the supported retained payload size")
    return definition


def preview(principal: Principal, composition: ReportComposition) -> dict[str, Any]:
    from finai_api.services.retained_report_results import resolve

    require_permission(principal, "ontology_read")
    context = company_context.resolve(
        principal,
        composition.company_id,
        valid_at=composition.valid_at,
        known_at=composition.known_at,
    )
    admitted = [
        entry["company"]
        for entry in context["company_directory"]["companies"]
        if entry["company"]["resource_id"] == str(composition.company_id)
    ]
    if len(admitted) != 1:
        raise WorkspaceError(404, "Company is unavailable in the selected snapshot")
    company = admitted[0]
    snapshot = RetainedReportSnapshot(
        composition=composition,
        company=Pin.model_validate(
            {key: company[key] for key in ("resource_id", "version_id", "content_hash")}
        ),
        company_label=company["display_name"],
        sections=resolve(principal, composition.company_id, composition.sections),
    )
    return ReportPreview(
        snapshot=snapshot, snapshot_sha256=digest(snapshot.model_dump(mode="json"))
    ).model_dump(mode="json")


def _read_detail(
    principal: Principal, proposal_id: UUID, company_id: UUID
) -> tuple[ProposalDetail, ResourceMutation, RetainedReportDefinition]:
    require_permission(principal, "ontology_read")
    detail = resources.proposal_detail(principal, proposal_id)
    matches = [item for item in detail.proposal.mutations if item.object_type == "RetainedReport"]
    if len(matches) != 1 or len(detail.proposal.mutations) != 1:
        raise WorkspaceError(404, "Saved report is unavailable in this context")
    item = matches[0]
    definition = _definition(item)
    if (
        definition.snapshot.composition.company_id != company_id
        or definition.exact_scope != principal.scope
        or detail.proposal.access_entity != principal.scope.legal_entity_id
    ):
        raise WorkspaceError(404, "Saved report is unavailable in this context")
    return detail, item, definition


def _response(
    detail: ProposalDetail, item: ResourceMutation, definition: RetainedReportDefinition
) -> dict[str, Any]:
    return {
        "contract": "retained-report/1",
        "reference": {
            "report_id": str(definition.report_id),
            "proposal_id": str(detail.proposal.proposal_id),
            "content_hash": canonical_sha256(item),
        },
        "previous_proposal_id": str(definition.previous_proposal_id)
        if definition.previous_proposal_id
        else None,
        "company_id": str(definition.snapshot.composition.company_id),
        "title": definition.snapshot.composition.title,
        "created_at": detail.created_at.isoformat(),
        "created_by": detail.submitted_by,
        "review_state": detail.decision or "DRAFT",
        "snapshot": definition.snapshot.model_dump(mode="json"),
        "exports": {
            key: artifact.model_dump(exclude={"content_base64"})
            for key, artifact in definition.exports.items()
        },
        "current_use_authorized": False,
        "business_effect_authorized": False,
    }


def read(principal: Principal, proposal_id: UUID, company_id: UUID) -> dict[str, Any]:
    return _response(*_read_detail(principal, proposal_id, company_id))


def save(principal: Principal, request: SaveRetainedReport) -> dict[str, Any]:
    from finai_api.services.retained_report_exports import build

    require_permission(principal, "ontology_read")
    require_permission(principal, "ontology_propose")
    # Retry reads retained bytes before any producer or adapter is consulted.
    try:
        prior = _read_detail(principal, request.request_id, request.composition.company_id)
    except WorkspaceError as exc:
        if exc.status_code != 404:
            raise
    else:
        definition = prior[2]
        if (
            definition.report_id != request.report_id
            or definition.previous_proposal_id != request.previous_proposal_id
            or definition.snapshot.composition != request.composition
            or definition.expected_preview_sha256 != request.expected_preview_sha256
        ):
            raise WorkspaceError(
                409, "Save request identity was reused for different report content"
            )
        return _response(*prior)
    resolved = preview(principal, request.composition)
    if resolved["snapshot_sha256"] != request.expected_preview_sha256:
        raise WorkspaceError(409, "Report preview changed; review the exact result before saving")
    definition = RetainedReportDefinition(
        report_id=request.report_id,
        exact_scope=principal.scope,
        previous_proposal_id=request.previous_proposal_id,
        expected_preview_sha256=request.expected_preview_sha256,
        snapshot=resolved["snapshot"],
        exports=build(resolved["snapshot"]),
    )
    item = ResourceMutation(
        resource_id=request.report_id,
        object_type="RetainedReport",
        identity_key="retained-report:" + str(request.report_id),
        display_name=request.composition.title,
        valid_from=request.composition.valid_at,
        evidence_class="SOURCE_BOUND",
        attributes={
            "legal_entity_id": str(request.composition.company_id),
            "definition": definition.model_dump(mode="json"),
        },
    )
    _definition(item)
    proposal = ResourceProposal(
        proposal_id=request.request_id,
        title=("Report: " + request.composition.title)[:200],
        rationale="Save an immutable analytical report draft from exact retained results.",
        access_entity=principal.scope.legal_entity_id,
        mutations=[item],
    )
    detail = resources.propose(principal, proposal)
    return _response(detail, item, definition)


def preflight(principal: Principal, proposal: ResourceProposal) -> dict[UUID, str]:
    """Materialize before the canonical write lock; fence authority again inside it."""
    from finai_api.services.retained_report_exports import build

    reports = [item for item in proposal.mutations if item.object_type == "RetainedReport"]
    if reports and (
        len(proposal.mutations) != 1
        or proposal.source_versions
        or proposal.calculated_bindings
        or proposal.restores_versions
    ):
        raise WorkspaceError(422, "Save one report revision in its own change set")
    proofs = {}
    for item in reports:
        definition = _definition(item)
        if definition.exact_scope != principal.scope:
            raise WorkspaceError(403, "Report requires its exact authorized scope")
        current = preview(principal, definition.snapshot.composition)
        if (
            current["snapshot"] != definition.snapshot.model_dump(mode="json")
            or current["snapshot_sha256"] != definition.expected_preview_sha256
            or build(current["snapshot"])
            != {
                key: artifact.model_dump(mode="json")
                for key, artifact in definition.exports.items()
            }
        ):
            raise WorkspaceError(
                409, "Report content differs from exact retained result materialization"
            )
        if definition.previous_proposal_id:
            previous = _read_detail(
                principal,
                definition.previous_proposal_id,
                definition.snapshot.composition.company_id,
            )[2]
            if previous.report_id != definition.report_id:
                raise WorkspaceError(
                    409, "Report revision cannot change its logical report identity"
                )
        proofs[item.resource_id] = canonical_sha256(item)
    return proofs


def validate(
    principal: Principal,
    item: ResourceMutation,
    target: Callable[..., dict],
    conn: Any,
    access_entity: str,
    proofs: dict[UUID, str] | None,
) -> None:
    from finai_api.services.resource_lifecycle import require_available_version
    from finai_api.services.upstream_authority import upstream_authority

    definition = _definition(item)
    if (
        not proofs
        or proofs.get(item.resource_id) != canonical_sha256(item)
        or definition.exact_scope != principal.scope
        or access_entity != principal.scope.legal_entity_id
        or item.resource_id != definition.report_id
        or item.identity_key != "retained-report:" + str(definition.report_id)
        or item.attributes.get("legal_entity_id") != str(definition.snapshot.composition.company_id)
        or item.display_name != definition.snapshot.composition.title
        or item.evidence_class != "SOURCE_BOUND"
        or item.authority_state != "APPROVED"
    ):
        raise WorkspaceError(
            409, "Report requires validated exact materialization and company identity"
        )
    pins = {
        (
            str(definition.snapshot.company.resource_id),
            str(definition.snapshot.company.version_id),
        ): definition.snapshot.company
    }
    for section in definition.snapshot.sections:
        for raw in section.authority_observation["roots"]:
            pin = Pin.model_validate(raw)
            pins[(str(pin.resource_id), str(pin.version_id))] = pin
    if len(pins) > 1000:
        raise WorkspaceError(422, "Report exceeds the supported exact dependency bound")
    for index, pin in enumerate(pins.values()):
        require_available_version(conn, principal, pin.resource_id, pin.version_id)
        row = target(
            str(pin.resource_id),
            str(item.resource_id),
            f"RETAINED_REPORT:{index}",
            str(pin.version_id),
        )
        if row["content_hash"] != pin.content_hash:
            raise WorkspaceError(409, "Report dependency content changed")
        upstream_authority(
            conn, principal, pin.resource_id, pin.version_id, allow_historical_provenance=True
        )


def export(
    principal: Principal, proposal_id: UUID, company_id: UUID, format: str
) -> tuple[bytes, dict[str, str]]:
    from finai_api.services.retained_report_exports import validate_artifact_bytes

    require_permission(principal, "export")
    if format not in {"xlsx", "html"}:
        raise WorkspaceError(404, "Report export format is unavailable")
    detail, item, definition = _read_detail(principal, proposal_id, company_id)
    artifact = definition.exports[format].model_dump(mode="json")
    content = validate_artifact_bytes(artifact)
    return content, {
        "Content-Type": artifact["media_type"],
        "Content-Disposition": f'attachment; filename="report.{format}"',
        "Content-Length": str(len(content)),
        "X-Content-SHA256": artifact["sha256"],
        "X-Report-Content-Hash": canonical_sha256(item),
        "X-Report-Proposal-Id": str(detail.proposal.proposal_id),
        "Cache-Control": "no-store",
    }


def list_reports(
    principal: Principal,
    company_id: UUID,
    cursor_created_at: datetime | None = None,
    cursor_proposal_id: UUID | None = None,
) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    if (cursor_created_at is None) != (cursor_proposal_id is None):
        raise WorkspaceError(422, "Report continuation requires both cursor values")
    if cursor_created_at and cursor_created_at.tzinfo is None:
        raise WorkspaceError(422, "Report continuation timestamp requires a timezone")
    with resources.resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as c:
        rows = c.execute(
            "SELECT proposal_id,created_at FROM resource_proposals WHERE tenant_id=%s "
            "AND access_entity=%s AND jsonb_array_length(payload->'request'->'mutations')=1 "
            "AND payload->'request'->'mutations'->0->>'object_type'='RetainedReport' "
            "AND payload->'request'->'mutations'->0->'attributes'->>'legal_entity_id'=%s "
            "AND payload->'request'->'mutations'->0->'attributes'->'definition'->"
            "'exact_scope'=%s::jsonb "
            "AND (%s::timestamptz IS NULL OR (created_at,proposal_id)<(%s::timestamptz,%s::uuid)) "
            "ORDER BY created_at DESC,proposal_id DESC LIMIT 21",
            (
                principal.scope.tenant_id,
                principal.scope.legal_entity_id,
                str(company_id),
                principal.scope.model_dump_json(),
                cursor_created_at,
                cursor_created_at,
                cursor_proposal_id,
            ),
        ).fetchall()
    items = []
    for row in rows[:20]:
        report = read(principal, row["proposal_id"], company_id)
        items.append(
            {key: value for key, value in report.items() if key not in {"snapshot", "exports"}}
        )
    last = rows[19] if len(rows) > 20 else None
    return {
        "contract": "retained-report-list/1",
        "company_id": str(company_id),
        "items": items,
        "next_cursor": {
            "created_at": last["created_at"].isoformat(),
            "proposal_id": str(last["proposal_id"]),
        }
        if last
        else None,
    }
