"""Bounded discovery over immutable invocations, without executing or hydrating analyses."""

import base64
import hmac
import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from psycopg.errors import QueryCanceled
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from finai_api.config import get_settings
from finai_api.domain.retained_analyses import RetainedAnalysisPage, RetainedAnalysisReference
from finai_api.domain.review import Principal
from finai_api.read_budget import ReadBudgetExceeded, bounded_read, remaining_ms
from finai_api.security import require_permission
from finai_api.services import function_invocations, resources, semantic_analysis
from finai_api.services.semantic_analysis_support import pin
from finai_api.services.workspace import WorkspaceError

PAGE_SIZE = 5
MAX_RESULT_BYTES = 8 * 1024 * 1024
MAX_PAGE_BYTES = 16 * 1024 * 1024


def _binding(principal, company_id):
    return sha256(
        json.dumps(
            {
                "scope": principal.scope.model_dump(mode="json"),
                "actor": principal.actor_id,
                "permissions": sorted(principal.permissions),
                "company": str(company_id),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _signature(payload):
    secret = get_settings().access_tokens.get_secret_value()
    if not secret or secret == "{}":
        raise WorkspaceError(503, "Retained discovery pagination is not configured")
    return hmac.new(secret.encode(), b"g8-retained-analysis-page/1:" + payload, sha256).hexdigest()


def _boundary(candidate):
    return sha256(
        json.dumps(
            [
                str(candidate["request_id"]),
                candidate["recorded_at"].astimezone(UTC).isoformat(),
            ],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _cursor(principal, company_id, cutoff, offset, boundary):
    payload = json.dumps(
        {
            "version": 1,
            "binding": _binding(principal, company_id),
            "recorded_before": cutoff.isoformat(),
            "offset": offset,
            "boundary": boundary,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=") + "." + _signature(payload)


def _position(principal, company_id, cursor, now):
    if cursor is None:
        return now, 0, None
    try:
        if len(cursor) > 4096:
            raise ValueError
        encoded, signature = cursor.split(".")
        payload = base64.b64decode(
            encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True
        )
        if not hmac.compare_digest(signature, _signature(payload)):
            raise ValueError
        value = json.loads(payload)
        cutoff = datetime.fromisoformat(value["recorded_before"])
        if (
            set(value) != {"version", "binding", "recorded_before", "offset", "boundary"}
            or type(value["version"]) is not int
            or value["version"] != 1
            or value["binding"] != _binding(principal, company_id)
            or type(value["offset"]) is not int
            or not 1 <= value["offset"] <= 2**63 - 1
            or not isinstance(value["boundary"], str)
            or re.fullmatch(r"[a-f0-9]{64}", value["boundary"]) is None
            or cutoff.utcoffset() is None
            or cutoff > now
        ):
            raise ValueError
        return cutoff, value["offset"], value["boundary"]
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise WorkspaceError(
            422, "Retained analysis cursor is invalid for this company and access context"
        ) from None


def _company(principal, company_id):
    with resources.resource_connection(principal) as conn:
        row = resources._get(conn, principal.scope.tenant_id, company_id)
    if (
        str(row["resource_id"]) != str(company_id)
        or row["object_type"] != "LegalEntity"
        or row["evidence_class"] == "REFERENCE_TEMPLATE"
    ):
        raise WorkspaceError(404, "Retained analyses are unavailable for this canonical company")


def _candidates(principal, cutoff, offset, boundary):
    scope = Jsonb(principal.scope.model_dump(mode="json"))
    with function_invocations._database(principal) as cursor:
        rows = cursor.execute(
            "SELECT i.request_id,r.recorded_at,"
            "i.plan->'implementation'->>'implementation_id' AS implementation, "
            "octet_length(f.payload::text)+octet_length(i.plan::text)"
            "+octet_length(r.payload::text) AS payload_bytes "
            "FROM function_invocations i JOIN function_invocation_results r "
            "USING(tenant_id,request_id) "
            "JOIN fact_calculation_runs f ON f.tenant_id=r.tenant_id AND f.run_id=r.run_id "
            "WHERE i.tenant_id=%s AND i.exact_scope=%s AND r.exact_scope=%s AND f.exact_scope=%s "
            "AND i.plan->'implementation'->>'implementation_id'='ontology.object-set-derived/v1' "
            "AND r.status='SUCCEEDED' AND r.recorded_at<=%s "
            "ORDER BY r.recorded_at DESC,i.request_id DESC LIMIT %s OFFSET %s",
            (
                principal.scope.tenant_id,
                scope,
                scope,
                scope,
                cutoff,
                PAGE_SIZE + 1 + bool(offset),
                max(0, offset - 1),
            ),
        ).fetchall()
    if offset:
        if not rows or _boundary(rows[0]) != boundary:
            raise WorkspaceError(
                409, "Retained analysis page changed; refresh discovery before continuing"
            )
        rows = rows[1:]
    return rows


def _reference(principal, company_id, candidate):
    history, plan, resolver = semantic_analysis.load(principal, candidate["request_id"])
    if plan["implementation"]["implementation_id"] != "ontology.object-set-derived/v1":
        raise WorkspaceError(422, "Adapter is outside this discovery subset")
    if plan.get("group_count"):
        from finai_api.services.semantic_analysis_counts import subject

        contract = "semantic-analysis/1"
    else:
        from finai_api.services.semantic_analysis_objects import subject

        contract = "semantic-analysis/2"
    with resolver.read_session():
        function, company, _, _ = subject(history, plan, resolver, company_id)
    if str(company["resource_id"]) != str(company_id):
        raise WorkspaceError(404, "Retained subject is unavailable for this company")
    recorded = datetime.fromisoformat(history["receipt"]["recorded_at"])
    if recorded != candidate["recorded_at"]:
        raise WorkspaceError(409, "Retained observation time differs from its indexed evidence")
    return RetainedAnalysisReference(
        invocation_id=candidate["request_id"],
        function=pin(function),
        company=pin(company),
        title=function["display_name"][:512],
        receipt_hash=history["receipt_hash"],
        run_id=history["output"]["run_id"],
        valid_at=history["output"]["query"]["valid_at"],
        known_at=history["output"]["query"]["known_at"],
        recorded_at=recorded,
        projection_contract=contract,
    )


def discover(
    principal: Principal, company_id: UUID, cursor: str | None = None
) -> RetainedAnalysisPage:
    require_permission(principal, "ontology_read")
    now = datetime.now(UTC)
    cutoff, offset, boundary = _position(principal, company_id, cursor, now)
    items, candidates, inspected, consumed = [], [], 0, 0
    try:
        with bounded_read():
            _company(principal, company_id)
            candidates = _candidates(principal, cutoff, offset, boundary)
            for candidate in candidates[:PAGE_SIZE]:
                remaining_ms()
                size = candidate["payload_bytes"]
                if type(size) is not int or size < 0:
                    raise WorkspaceError(
                        409, "Retained analysis index has an invalid size contract"
                    )
                if size <= MAX_RESULT_BYTES and consumed + size > MAX_PAGE_BYTES:
                    break  # The next page retries this uninspected candidate.
                if (
                    size > MAX_RESULT_BYTES
                    or candidate["implementation"] != "ontology.object-set-derived/v1"
                ):
                    inspected += 1
                    continue
                consumed += size
                try:
                    items.append(_reference(principal, company_id, candidate))
                except WorkspaceError as error:
                    if error.status not in (403, 404, 409, 422):
                        raise
                    # Never expose candidate identities, titles, or scope-failure details.
                except (KeyError, TypeError, ValueError, ValidationError):
                    pass  # Corrupt retained evidence is not an eligible reference.
                inspected += 1  # An interrupted candidate is never counted or skipped.
    except (ReadBudgetExceeded, QueryCanceled):
        if inspected == 0:
            raise WorkspaceError(
                503, "Retained analysis discovery read budget exceeded; retry this page"
            ) from None
        # Continue the fully verified prefix at the first uncompleted candidate.
    return RetainedAnalysisPage(
        company_id=company_id,
        observed_at=now,
        recorded_before=cutoff,
        items=items,
        inspected_count=inspected,
        returned_count=len(items),
        not_listed_count=inspected - len(items),
        next_cursor=_cursor(
            principal, company_id, cutoff, offset + inspected, _boundary(candidates[inspected - 1])
        )
        if len(candidates) > inspected
        else None,
    )
