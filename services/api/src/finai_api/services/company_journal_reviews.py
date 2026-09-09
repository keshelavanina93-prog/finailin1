"""Bounded review readback of existing production receipts and canonical proposals.

No workflow identity or accounting authority is synthesized. Receipt decisions are
historical acknowledgements; only current canonical proposal detail supplies state.
"""

import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid5

from psycopg import Error as DatabaseError
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from finai_api.domain.company_condition import CompanyJournalReviewItem, CompanyJournalReviews
from finai_api.domain.journal_production import JournalProductionRequest
from finai_api.domain.resources import ResourceProposal
from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services import journal_production_history, resources
from finai_api.services.entity_movement_review import digest
from finai_api.services.workspace import WorkspaceError

LIMIT = 25
MAX_BYTES = 8 * 1024 * 1024


def _receipts(principal: Principal, company_id: UUID) -> list[dict[str, Any]]:
    scope = principal.scope.model_dump(mode="json")
    with resources.resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cur:
        conn.execute("SELECT set_config('finai.exact_scope',%s,true)", (json.dumps(scope),))
        conn.execute("SET LOCAL statement_timeout = '5s'")
        return list(
            cur.execute(
                "WITH selected AS (SELECT * FROM ("
                "SELECT DISTINCT ON (request_id) *,octet_length(payload::text) AS payload_bytes "
                "FROM journal_production_attempts WHERE tenant_id=%s AND exact_scope=%s "
                "AND payload->'request'->>'company_id'=%s "
                "ORDER BY request_id,(phase='SUBMITTED') DESC) latest "
                "ORDER BY recorded_at DESC,request_id LIMIT 26) "
                "SELECT tenant_id,request_id,phase,exact_scope,request_hash,receipt_hash,"
                "recorded_at,"
                "payload_bytes,CASE WHEN sum(payload_bytes) OVER ()<=%s "
                "THEN payload ELSE NULL END AS payload FROM selected "
                "ORDER BY recorded_at DESC,request_id",
                (principal.scope.tenant_id, Jsonb(scope), str(company_id), MAX_BYTES),
            ).fetchall()
        )


def _candidates(
    principal: Principal,
    company_id: UUID,
    receipts: list[dict[str, Any]],
) -> tuple[list[tuple[JournalProductionRequest, ResourceProposal, str, datetime, bool]], bool]:
    if len(receipts) > LIMIT + 1 or sum(row["payload_bytes"] for row in receipts) > MAX_BYTES:
        raise ValueError("Receipt read budget exceeded")
    candidates = []
    seen_requests: set[UUID] = set()
    seen_proposals: set[UUID] = set()
    for row in receipts[:LIMIT]:
        if (
            row["tenant_id"] != principal.scope.tenant_id
            or row["exact_scope"] != principal.scope.model_dump(mode="json")
            or row["phase"] not in ("PREPARED", "SUBMITTED")
        ):
            raise ValueError("Receipt scope or phase differs")
        if not isinstance(row["payload"], dict):
            raise ValueError("Receipt body unavailable")
        payload = journal_production_history.verify(row, principal)
        request = JournalProductionRequest.model_validate(payload["request"])
        if (
            payload["contract"] != "source-journal-production/1"
            or request.company_id != company_id
            or request.request_id != row["request_id"]
            or payload["invocation_id"] != str(request.invocation_id)
            or digest(request.model_dump(mode="json")) != row["request_hash"]
            or request.request_id in seen_requests
        ):
            raise ValueError("Receipt intent differs")
        seen_requests.add(request.request_id)
        rows = payload["rows"]
        if not isinstance(rows, list) or len(rows) > 5000:
            raise ValueError("Receipt row budget exceeded")
        by_coordinate = {item["coordinate"]: item for item in rows}
        if len(by_coordinate) != len(rows):
            raise ValueError("Duplicate retained coordinate")
        submitted = payload.get("submitted", [])
        if not isinstance(submitted, list) or len(submitted) > 20:
            raise ValueError("Submission budget exceeded")
        acknowledged = {item["coordinate"]: item["proposal_id"] for item in submitted}
        if (
            len(acknowledged) != len(submitted)
            or not set(acknowledged).issubset(request.coordinates)
            or (row["phase"] == "PREPARED" and submitted)
            or (row["phase"] == "SUBMITTED" and "submitted" not in payload)
        ):
            raise ValueError("Submission selection differs")
        for coordinate in sorted(request.coordinates):
            entry = by_coordinate[coordinate]
            if "proposal" not in entry:
                if coordinate in acknowledged:
                    raise ValueError("Submission lacks prepared proposal")
                continue
            proposal = ResourceProposal.model_validate(entry["proposal"])
            if (
                proposal.proposal_id != uuid5(request.request_id, coordinate)
                or entry.get("proposal_id") != str(proposal.proposal_id)
                or proposal.access_entity != principal.scope.legal_entity_id
                or proposal.proposal_id in seen_proposals
                or (
                    coordinate in acknowledged
                    and acknowledged[coordinate] != str(proposal.proposal_id)
                )
            ):
                raise ValueError("Prepared proposal identity differs")
            seen_proposals.add(proposal.proposal_id)
            candidates.append(
                (request, proposal, coordinate, row["recorded_at"], coordinate in acknowledged)
            )
    return candidates[:LIMIT], len(receipts) > LIMIT or len(candidates) > LIMIT


def observe(principal: Principal, company_id: UUID) -> CompanyJournalReviews:
    require_permission(principal, "ontology_read")
    observed_at = datetime.now(UTC)
    try:
        candidates, truncated = _candidates(principal, company_id, _receipts(principal, company_id))
        items = []
        for request, prepared, coordinate, created_at, acknowledged in candidates:
            state: Literal["PREPARED", "PENDING_REVIEW", "PUBLISHED", "REJECTED"]
            try:
                detail = resources.proposal_detail(principal, prepared.proposal_id)
            except WorkspaceError as exc:
                if exc.status != 404 or acknowledged:
                    raise
                state = "PREPARED"
                reason = "Prepared journal proposal; submission for review is not established."
            else:
                if detail.proposal.model_dump(mode="json") != prepared.model_dump(
                    mode="json"
                ) or detail.decision not in (None, "APPROVED", "REJECTED"):
                    raise ValueError("Canonical proposal differs from retained preparation")
                state = (
                    "PUBLISHED"
                    if detail.decision == "APPROVED"
                    else "REJECTED"
                    if detail.decision == "REJECTED"
                    else "PENDING_REVIEW"
                )
                reason = detail.proposal.rationale
                created_at = detail.created_at
            items.append(
                CompanyJournalReviewItem(
                    request_id=request.request_id,
                    proposal_id=prepared.proposal_id,
                    company_id=company_id,
                    invocation_id=request.invocation_id,
                    coordinate=coordinate,
                    title=prepared.title,
                    state=state,
                    created_at=created_at,
                    reason=reason,
                )
            )
        return CompanyJournalReviews(observed_at=observed_at, items=items, truncated=truncated)
    except (DatabaseError, WorkspaceError, ValueError, KeyError, TypeError):
        return CompanyJournalReviews(
            state="UNAVAILABLE",
            observed_at=observed_at,
            items=[],
            truncated=False,
            reason="Journal review receipts or current canonical decisions could not be verified. "
            "No empty-queue or approval-state conclusion is established.",
        )
