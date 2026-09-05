"""Resolve ingestion references exclusively through the shared accepted resource registry."""

from calendar import monthrange
from contextlib import nullcontext
from datetime import date
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from finai_api.domain.authority import canonical_sha256
from finai_api.domain.ingest import CanonicalReference, IngestReceipt, IngestRequest
from finai_api.domain.review import Principal
from finai_api.services.resources import HEAD_SELECT, resource_connection
from finai_api.services.workspace import WorkspaceError


def _accepted_version(
    conn: psycopg.Connection[Any], principal: Principal, version_id: UUID, object_type: str
) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            HEAD_SELECT + "WHERE h.tenant_id=%s AND v.version_id=%s AND v.object_type=%s "
            "AND v.authority_state='APPROVED' AND v.valid_from<=now() "
            "AND (v.valid_to IS NULL OR v.valid_to>now())",
            (principal.scope.tenant_id, version_id, object_type),
        ).fetchone()
    if row is None:
        raise WorkspaceError(409, f"Accepted {object_type} version is unavailable or changed")
    return row


def _reference(row: dict[str, Any]) -> CanonicalReference:
    return CanonicalReference(resource_id=row["resource_id"], version_id=row["version_id"])


def _dependency(
    conn: psycopg.Connection[Any],
    principal: Principal,
    source: dict[str, Any],
    field: str,
    object_type: str,
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT target_resource_id,target_version_id FROM resource_dependencies "
        "WHERE tenant_id=%s AND version_id=%s AND relation=%s",
        (principal.scope.tenant_id, source["version_id"], "FIELD:" + field),
    ).fetchone()
    if row is None or str(row[0]) != source["attributes"].get(field):
        raise WorkspaceError(409, f"Canonical {field} dependency is missing")
    return _accepted_version(conn, principal, row[1], object_type)


def _context(
    conn: psycopg.Connection[Any],
    principal: Principal,
    version_id: UUID,
) -> tuple[dict[str, CanonicalReference], dict[str, Any]]:
    # Shares the registry writer lock: context and account choices cannot mix concurrent versions.
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
        (f"canonical:{principal.scope.tenant_id}",),
    )
    binding = _accepted_version(conn, principal, version_id, "ContextBinding")
    scope_key = canonical_sha256(principal.scope)
    if (
        binding["identity_key"] != "context:" + scope_key
        or binding["attributes"]["source_scope_key"] != scope_key
    ):
        raise WorkspaceError(403, "Canonical context does not match the exact source scope")
    nodes = {
        field: _dependency(conn, principal, binding, field, kind)
        for field, kind in (
            ("legal_entity_id", "LegalEntity"),
            ("ledger_id", "Ledger"),
            ("period_id", "FiscalPeriod"),
            ("currency_id", "Currency"),
        )
    }
    ledger, period = nodes["ledger_id"], nodes["period_id"]
    chart = _dependency(conn, principal, ledger, "chart_id", "LocalChartOfAccounts")
    entity_id = str(nodes["legal_entity_id"]["resource_id"])
    year, month = map(int, principal.scope.period.split("-"))
    if (
        ledger["attributes"]["legal_entity_id"] != entity_id
        or chart["attributes"]["legal_entity_id"] != entity_id
        or ledger["attributes"]["currency_id"] != str(nodes["currency_id"]["resource_id"])
        or nodes["currency_id"]["attributes"]["code"] != principal.scope.currency
        or ledger["attributes"]["calendar_id"] != period["attributes"]["calendar_id"]
        or date.fromisoformat(period["attributes"]["starts_on"]) > date(year, month, 1)
        or date.fromisoformat(period["attributes"]["ends_on"])
        < date(year, month, monthrange(year, month)[1])
    ):
        raise WorkspaceError(409, "Canonical company, ledger, chart, period or currency disagree")
    return {field: _reference(node) for field, node in nodes.items()}, chart


def context_accounts(
    principal: Principal,
    context_version_id: UUID,
    offset: int = 0,
) -> dict[str, Any]:
    from finai_api.services.account_dimensions import choices

    with resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cursor:
        _, chart = _context(conn, principal, context_version_id)
        rows = cursor.execute(
            HEAD_SELECT + "WHERE h.tenant_id=%s AND v.object_type='LocalAccount' "
            "AND v.authority_state='APPROVED' AND v.attributes->>'chart_id'=%s "
            "AND v.valid_from<=now() AND (v.valid_to IS NULL OR v.valid_to>now()) "
            "ORDER BY v.attributes->>'account_code',v.resource_id LIMIT 101 OFFSET %s",
            (principal.scope.tenant_id, str(chart["resource_id"]), offset),
        ).fetchall()
        return {
            "items": [
                {
                    "resource_id": str(row["resource_id"]),
                    "version_id": str(row["version_id"]),
                    "display_name": row["display_name"],
                    "account_code": row["attributes"]["account_code"],
                    "dimension_rules": choices(conn, principal, row),
                }
                for row in rows[:100]
            ],
            "offset": offset,
            "limit": 100,
            "has_more": len(rows) > 100,
        }


def bind_receipt(
    principal: Principal,
    request: IngestRequest,
    receipt: IngestReceipt,
    existing_connection: psycopg.Connection[Any] | None = None,
) -> IngestReceipt:
    if request.context_version_id is None:
        if (
            request.account_version_ids
            or request.account_alias_version_ids
            or request.account_dimension_rule_version_ids
            or request.dimension_member_version_ids
        ):
            raise WorkspaceError(422, "Account version mappings require a canonical context")
        return receipt
    manager = (
        nullcontext(existing_connection)
        if existing_connection is not None
        else resource_connection(principal)
    )
    with manager as conn:
        references, chart = _context(conn, principal, request.context_version_id)
        accounts = {
            candidate.values["account_code"]
            for candidate in receipt.candidates
            if candidate.object_type == "Account"
        }
        if set(request.account_version_ids) != accounts:
            raise WorkspaceError(
                422,
                "Provide exactly one canonical account version for each "
                "recognized source account code",
            )
        if len(set(request.account_version_ids.values())) != len(request.account_version_ids):
            raise WorkspaceError(422, "Source accounts require distinct canonical account versions")
        if set(request.account_alias_version_ids) - accounts:
            raise WorkspaceError(
                422, "Alias mappings must correspond to recognized source accounts"
            )
        if request.account_alias_version_ids and not request.source_system:
            raise WorkspaceError(422, "Pinned source aliases require an explicit source system")
        resolved: dict[str, CanonicalReference] = {}
        account_nodes: dict[str, dict[str, Any]] = {}
        alias_references: dict[str, CanonicalReference] = {}
        for code, version_id in request.account_version_ids.items():
            account = _accepted_version(conn, principal, version_id, "LocalAccount")
            if account["attributes"]["chart_id"] != str(chart["resource_id"]):
                raise WorkspaceError(
                    422,
                    "Account version must match the canonical ledger chart",
                )
            alias_version = request.account_alias_version_ids.get(code)
            if alias_version is not None:
                alias = _accepted_version(conn, principal, alias_version, "Alias")
                if (
                    alias["attributes"]["source_system"] != request.source_system
                    or alias["attributes"]["external_id"] != code
                ):
                    raise WorkspaceError(
                        422, "Alias does not match the exact source system and code"
                    )
                target = _dependency(conn, principal, alias, "target_id", "LocalAccount")
                if target["version_id"] != version_id:
                    raise WorkspaceError(
                        409, "Alias target differs from the pinned account version"
                    )
                alias_references[code] = _reference(alias)
            elif account["attributes"]["account_code"] != code:
                raise WorkspaceError(
                    422,
                    "Account version must match the exact source code or a reviewed source alias",
                )
            account_chart = _dependency(
                conn, principal, account, "chart_id", "LocalChartOfAccounts"
            )
            if account_chart["version_id"] != chart["version_id"]:
                raise WorkspaceError(
                    409, "Account chart version differs from the canonical context"
                )
            redirect = conn.execute(
                HEAD_SELECT + "WHERE h.tenant_id=%s AND v.object_type='IdentityResolution' "
                "AND v.authority_state='APPROVED' AND v.attributes->>'source_id'=%s "
                "AND v.attributes->>'active'='true' AND v.valid_from<=now() "
                "AND (v.valid_to IS NULL OR v.valid_to>now()) LIMIT 1",
                (principal.scope.tenant_id, str(account["resource_id"])),
            ).fetchone()
            if redirect:
                raise WorkspaceError(
                    409, "Account identity was redirected; review its canonical binding"
                )
            resolved[code] = _reference(account)
            account_nodes[code] = account
        candidates = tuple(
            candidate.model_copy(
                update={
                    "canonical_references": {
                        **references,
                        **(
                            {"account_id": resolved[candidate.values["account_code"]]}
                            if candidate.object_type in ("Account", "PeriodBalance")
                            else {}
                        ),
                        **(
                            {"account_alias_id": alias_references[candidate.values["account_code"]]}
                            if candidate.object_type in ("Account", "PeriodBalance")
                            and candidate.values["account_code"] in alias_references
                            else {}
                        ),
                    }
                }
            )
            for candidate in receipt.candidates
        )
        bound = receipt.model_copy(
            update={
                "context_version_id": request.context_version_id,
                "canonical_references": references,
                "candidates": candidates,
                "binding_state": "CANONICAL_BOUND"
                if receipt.source_class == "TRIAL_BALANCE"
                else "SOURCE_ONLY",
            }
        )
        from finai_api.services.account_dimensions import bind_dimensions

        return bind_dimensions(conn, principal, request, bound, account_nodes)
