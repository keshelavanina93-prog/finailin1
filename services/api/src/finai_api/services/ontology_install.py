"""Read-only planning and preflight for the governed platform ontology install."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from psycopg.rows import dict_row

from finai_api.config import get_settings
from finai_api.domain.ontology_catalog import canonical_id, platform_definitions
from finai_api.domain.review import Principal
from finai_api.services import finance_ontology, resources
from finai_api.services.workspace import WorkspaceError

LEGACY_PHASE = "LegacyPlatformContracts"
LEGACY_SCHEMA_KEYS = {
    "Artifact",
    "JournalEntry",
    "JournalLine",
    "PeriodControl",
    "AccountDimensionPolicy",
    "DeploymentTarget",
    "RuntimeAgent",
    "DesiredState",
    "FunctionDefinition",
    "TransformationDefinition",
    "RetentionPolicy",
    "CertificationContract",
    "SourceRegulatoryPublication",
    "SourceAccountDefinition",
    "SourceJournalMovement",
    "SourceTrialBalanceRow",
    "CompanyDimension",
    "CompanyWorkspace",
    "SourceDimensionAssignment",
    "SourceAccountingScope",
    "SourceAccountingBinding",
    "SourceCorporateObservation",
    "CorporateDisclosureBinding",
    "SourceLicenceNotice",
    "LicenceNoticeBinding",
}

AUTHOR_PERMISSIONS = ("ontology_admin", "ontology_propose")
REVIEWER_PERMISSIONS = ("ontology_admin", "ontology_review")
STEWARD_PERMISSION = "restricted_read"


def _configured_principals() -> list[Principal]:
    """Return configured identities without exposing access-token material."""
    values = json.loads(get_settings().access_tokens.get_secret_value())
    principals: list[Principal] = []
    for token, grant in values.items():
        if "scope" in grant:
            principals.append(Principal.model_validate(grant))
        else:
            from hashlib import sha256

            principals.append(
                Principal(
                    actor_id=f"bootstrap-{sha256(token.encode()).hexdigest()[:24]}",
                    display_name="Bootstrap operator",
                    scope=grant,
                    permissions=("read", "ingest", "export"),
                )
            )
    return principals


def _same_tenant(value: Principal, tenant) -> bool:
    return value.scope.tenant_id == tenant


def _select_identity(
    principals: list[Principal],
    tenant,
    required: tuple[str, ...],
    *,
    different_from: str | None = None,
) -> Principal | None:
    for principal in principals:
        if not _same_tenant(principal, tenant):
            continue
        if different_from is not None and principal.actor_id == different_from:
            continue
        if set(required).issubset(principal.permissions):
            return principal
    return None


def _specifications(tenant) -> tuple[Any, list[dict[str, Any]], tuple[str, ...]]:
    compiled = finance_ontology.compilation(tenant)
    specifications = list(compiled.definitions)
    legacy = platform_definitions(tenant)
    known = {
        (specification["object_type"], specification["identity_key"])
        for specification in specifications
    }
    for specification in legacy:
        is_legacy = (
            specification["object_type"] == "SchemaDefinition"
            and specification["identity_key"] in LEGACY_SCHEMA_KEYS
        ) or (
            specification["object_type"] == "SemanticContract"
            and specification["identity_key"] == "OntologyDefinition"
        )
        identity = (specification["object_type"], specification["identity_key"])
        if is_legacy and identity not in known:
            specifications.append(specification)
    return compiled, specifications, (*finance_ontology.PHASES, LEGACY_PHASE)


def _principal_summary(principal: Principal | None, tenant) -> dict[str, Any]:
    if principal is None:
        return {
            "actor_id": None,
            "display_name": None,
            "tenant_id": str(tenant),
            "permissions": [],
        }
    return {
        "actor_id": principal.actor_id,
        "display_name": principal.display_name,
        "tenant_id": str(principal.scope.tenant_id),
        "permissions": sorted(principal.permissions),
    }


def _hidden_dependents(principal: Principal, root_ids: list) -> list[dict[str, Any]]:
    if not root_ids:
        return []
    rows: list[dict[str, Any]] = []
    with resources.resource_connection(principal) as conn, conn.cursor(
        row_factory=dict_row
    ) as cursor:
        has_batch_function = cursor.execute(
            "SELECT to_regprocedure("
            "'public.g8_hidden_current_dependents_for_roots(uuid[])'"
            ") AS function_name"
        ).fetchone()["function_name"] is not None
        has_detail_function = cursor.execute(
            "SELECT to_regprocedure('public.g8_hidden_current_dependents(uuid)') AS function_name"
        ).fetchone()["function_name"] is not None
        if has_batch_function:
            values = cursor.execute(
                "SELECT * FROM public.g8_hidden_current_dependents_for_roots(%s::uuid[])",
                (root_ids,),
            ).fetchall()
            values = [dict(value) for value in values]
        else:
            values = []
            for root_id in root_ids:
                if has_detail_function:
                    values.extend(
                        cursor.execute(
                            "SELECT * FROM public.g8_hidden_current_dependents(%s)",
                            (root_id,),
                        ).fetchall()
                    )
                    continue
                hidden = cursor.execute(
                    "SELECT public.g8_has_hidden_current_dependents(%s) AS hidden", (root_id,)
                ).fetchone()["hidden"]
                values.extend(
                    [
                        {
                            "resource_id": None,
                            "version_id": None,
                            "object_type": "UNKNOWN",
                            "identity_key": "hidden-dependents",
                            "display_name": "Hidden current dependent(s)",
                            "access_entity": None,
                        }
                    ]
                    if hidden
                    else []
                )
        for value in values:
            root_id = value.get("root_resource_id") or value.get("root_id")
            if root_id is None and len(root_ids) == 1:
                root_id = root_ids[0]
            rows.append(
                {
                    "root_resource_id": str(root_id) if root_id else None,
                    "resource_id": str(value["resource_id"])
                    if value.get("resource_id")
                    else None,
                    "version_id": str(value["version_id"])
                    if value.get("version_id")
                    else None,
                    "object_type": value.get("object_type"),
                    "identity_key": value.get("identity_key"),
                    "display_name": value.get("display_name"),
                    "access_entity": value.get("access_entity"),
                }
            )
    return sorted(rows, key=lambda item: (item["object_type"] or "", item["identity_key"] or ""))


def preflight(principal: Principal) -> dict[str, Any]:
    """Build an install plan without proposing, reviewing, or mutating anything."""
    if "ontology_read" not in principal.permissions:
        raise WorkspaceError(403, "Permission required: ontology_read")
    compiled, specifications, phases = _specifications(principal.scope.tenant_id)
    identities = [
        canonical_id(principal.scope.tenant_id, item["object_type"], item["identity_key"])
        for item in specifications
    ]
    installed: dict[str, dict[str, Any]] = {}
    with resources.resource_connection(principal) as conn, conn.cursor(
        row_factory=dict_row
    ) as cursor:
        rows = cursor.execute(
            "SELECT i.resource_id,i.object_type,i.identity_key,h.version_id,v.authority_state,"
            "v.attributes FROM canonical_identities i LEFT JOIN resource_heads h "
            "ON h.tenant_id=i.tenant_id AND h.resource_id=i.resource_id LEFT JOIN "
            "resource_versions v ON v.tenant_id=h.tenant_id AND v.version_id=h.version_id "
            "WHERE i.tenant_id=%s AND i.resource_id=ANY(%s::uuid[])",
            (principal.scope.tenant_id, identities),
        ).fetchall()
    for row in rows:
        installed[str(row["resource_id"])] = row

    compiled_rows: list[dict[str, Any]] = []
    publish: list[dict[str, Any]] = []
    preserve: list[dict[str, Any]] = []
    for item in specifications:
        identity = canonical_id(
            principal.scope.tenant_id, item["object_type"], item["identity_key"]
        )
        current = installed.get(str(identity))
        exact = bool(
            current
            and current.get("authority_state") == "APPROVED"
            and current.get("attributes") == item["attributes"]
        )
        status = "INSTALLED" if exact else "CHANGE_REQUIRED" if current else "NOT_INSTALLED"
        row = {
            "phase": item["object_type"]
            if item["object_type"] in finance_ontology.PHASES
            else LEGACY_PHASE,
            "object_type": item["object_type"],
            "identity_key": item["identity_key"],
            "resource_id": str(identity),
            "status": status,
            "version_id": (
                str(current["version_id"])
                if current and current.get("version_id")
                else None
            ),
        }
        compiled_rows.append(row)
        if status in {"NOT_INSTALLED", "CHANGE_REQUIRED"}:
            publish.append(row)
        elif current and current.get("authority_state") != "APPROVED":
            preserve.append(row)

    configured = _configured_principals()
    author = _select_identity(configured, principal.scope.tenant_id, AUTHOR_PERMISSIONS)
    reviewer = _select_identity(
        configured,
        principal.scope.tenant_id,
        REVIEWER_PERMISSIONS,
        different_from=author.actor_id if author else None,
    )
    steward = _select_identity(configured, principal.scope.tenant_id, (STEWARD_PERMISSION,))
    roots = []
    for item in specifications:
        if item["object_type"] not in {"SchemaDefinition", "SemanticContract", "LinkType"}:
            continue
        identity = canonical_id(
            principal.scope.tenant_id, item["object_type"], item["identity_key"]
        )
        if str(identity) in installed:
            roots.append(identity)
    hidden = _hidden_dependents(principal, roots)
    missing_permissions = {
        "author": [
            permission
            for permission in AUTHOR_PERMISSIONS
            if not author or permission not in author.permissions
        ],
        "reviewer": [
            permission
            for permission in REVIEWER_PERMISSIONS
            if not reviewer or permission not in reviewer.permissions
        ],
        "steward": [] if steward else [STEWARD_PERMISSION],
    }
    blockers: list[str] = []
    if missing_permissions["author"]:
        blockers.append(
            "No configured ontology author has: "
            + ", ".join(missing_permissions["author"])
        )
    if missing_permissions["reviewer"]:
        blockers.append(
            "No distinct configured ontology reviewer has: "
            + ", ".join(missing_permissions["reviewer"])
        )
    if hidden and not steward:
        names = ", ".join(
            sorted({item["identity_key"] or item["object_type"] for item in hidden})
        )
        blockers.append(
            "Complete dependency impact requires an authorized tenant steward; "
            f"missing {STEWARD_PERMISSION} for hidden dependents: {names}"
        )
    phase_counts = []
    for phase in phases:
        rows = [item for item in compiled_rows if item["phase"] == phase]
        phase_counts.append(
            {
                "phase": phase,
                "compiled": len(rows),
                "installed": sum(item["status"] == "INSTALLED" for item in rows),
                "pending": sum(item["status"] != "INSTALLED" for item in rows),
            }
        )
    return {
        "catalog_id": compiled.manifest["catalog_id"],
        "catalog_sha256": sha256(
            json.dumps(
                compiled.definitions,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest(),
        "tenant_id": str(principal.scope.tenant_id),
        "author": _principal_summary(author, principal.scope.tenant_id),
        "reviewer": _principal_summary(reviewer, principal.scope.tenant_id),
        "steward": _principal_summary(steward, principal.scope.tenant_id),
        "required_permissions": {
            "author": list(AUTHOR_PERMISSIONS),
            "reviewer": list(REVIEWER_PERMISSIONS),
            "steward": [STEWARD_PERMISSION],
        },
        "present_permissions": {
            "author": sorted(author.permissions) if author else [],
            "reviewer": sorted(reviewer.permissions) if reviewer else [],
            "steward": sorted(steward.permissions) if steward else [],
        },
        "missing_permissions": missing_permissions,
        "hidden_dependents": hidden,
        "phase_counts": phase_counts,
        "compiled_identity_keys": compiled_rows,
        "installed_identity_keys": [
            item for item in compiled_rows if item["status"] == "INSTALLED"
        ],
        "would_publish": {
            "count": len(publish),
            "identities": publish,
        },
        "would_preserve": {
            "count": len(preserve),
            "identities": preserve,
        },
        "company_instances_published": 0,
        "company_facts_published": False,
        "blocked_reason": blockers,
        "can_install": not blockers,
        "mutation_performed": False,
        "diagnostics": compiled.diagnostics,
    }
