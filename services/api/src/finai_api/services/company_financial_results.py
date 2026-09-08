"""Company financial discovery over canonical capabilities and retained invocation evidence.

Discovery never invokes a Function, reads source bytes, or grants publication authority.
Historical results keep their own scope and clocks even when current catalog entries change.
"""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

from finai_api.domain.function_execution import (
    AcceptedMovementsImplementation,
    FunctionDefinition,
    PostedMovementsImplementation,
)
from finai_api.domain.resources import ResourceMutation
from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services import (
    company_context,
    function_catalog,
    function_execution,
    function_invocations,
)
from finai_api.services.workspace import WorkspaceError

FINANCIAL_IMPLEMENTATIONS = (
    function_execution.POSTED_MOVEMENTS_IMPLEMENTATION_ID,
    function_execution.ACCEPTED_MOVEMENTS_IMPLEMENTATION_ID,
)


def pin(row: dict[str, Any]) -> dict[str, str]:
    return {key: str(row[key]) for key in ("resource_id", "version_id", "content_hash")}


def capability(
    item: dict[str, Any],
    dependencies: list[dict[str, Any]],
    context: dict[str, Any],
) -> dict[str, Any] | None:
    """Only installed typed financial adapters can describe guarded finance work."""
    attrs = item["attributes"]
    if attrs.get("definition", {}).get("implementation_id") not in FINANCIAL_IMPLEMENTATIONS:
        return None
    spec = FunctionDefinition.model_validate(attrs)
    company = context["company"]

    def target(identity: str, *_: str) -> dict[str, Any]:
        matches = {
            (str(r["resource_id"]), str(r["version_id"])): r
            for r in dependencies
            if str(r["resource_id"]) == identity
        }
        if len(matches) != 1:
            raise WorkspaceError(409, "Financial Function requires an exact unambiguous dependency")
        return next(iter(matches.values()))

    source = None
    binding = None
    eligibility = None
    if isinstance(spec.definition, PostedMovementsImplementation):
        source = next(
            (
                row
                for row in context["accounting_sources"]
                if row["scope"]["resource_id"] == str(spec.source_scope_id)
            ),
            None,
        )
        if source is None:
            return None
        if source["scope"]["attributes"].get("legal_entity_id") != company["resource_id"]:
            return None
        binding = next(
            (b for b in source["bindings"] if b["resource_id"] == str(spec.accounting_binding_id)),
            None,
        )
        if binding is None:
            return None
        if pin(target(str(spec.source_scope_id))) != pin(source["scope"]) or pin(
            target(str(spec.accounting_binding_id))
        ) != pin(binding):
            raise WorkspaceError(
                409, "Financial Function differs from selected accounting versions"
            )
        eligibility = source.get("binding_eligibility", {}).get(binding["version_id"])
    elif isinstance(spec.definition, AcceptedMovementsImplementation):
        if str(spec.definition.company.resource_id) != company["resource_id"]:
            return None
        if pin(target(company["resource_id"])) != pin(company):
            raise WorkspaceError(409, "Financial Function differs from selected company version")
    function_execution.validate_function(
        cast(
            ResourceMutation,
            SimpleNamespace(resource_id=UUID(item["reference"]["resource_id"]), attributes=attrs),
        ),
        target,
    )
    available = source is None or bool(eligibility and eligibility.get("eligible_for_accounting"))
    return {
        "function": {**item["reference"], "content_hash": item["content_hash"]},
        "display_name": item["display_name"],
        "implementation_id": spec.definition.implementation_id,
        "kind": "SOURCE_POSTED_MOVEMENTS" if source else "ACCEPTED_JOURNAL_MOVEMENTS",
        "state": "DISCOVERED" if available else "ACCOUNTING_BINDING_BLOCKED",
        "reason": None
        if available
        else (eligibility or {}).get(
            "reason", "Exact binding eligibility has not been established"
        ),
        "source_scope": pin(source["scope"]) if source else None,
        "accounting_binding": pin(binding) if binding else None,
        "document_id": spec.definition.document_id
        if isinstance(spec.definition, PostedMovementsImplementation)
        else None,
        "source_sha256": spec.definition.source_sha256
        if isinstance(spec.definition, PostedMovementsImplementation)
        else None,
        "sheet": spec.definition.sheet
        if isinstance(spec.definition, PostedMovementsImplementation)
        else None,
        "required_input": "REVIEWED_SOURCE_CONTEXT" if source else "EXACT_ACCEPTED_MOVEMENTS_INPUT",
        "current_use_authorized": False,
        "business_effect_authorized": False,
    }


def _retained_item(
    row: dict[str, Any], principal: Principal, company_id: UUID
) -> dict[str, Any] | None:
    """Validate catalog metadata; actual reopening still uses retained history/projection guards."""
    plan, payload = row["plan"], row["payload"]
    scope = principal.scope.model_dump(mode="json")
    if row["exact_scope"] != scope or plan.get("exact_scope") != scope:
        raise WorkspaceError(409, "Retained financial result differs from exact access scope")
    if (
        function_execution._digest({k: v for k, v in plan.items() if k != "plan_hash"})
        != row["plan_hash"]
        or plan.get("plan_hash") != row["plan_hash"]
        or function_invocations._digest(payload) != row["proof_hash"]
        or payload.get("plan_hash") != row["plan_hash"]
        or payload.get("exact_scope") != scope
        or payload.get("function") != plan.get("function")
        or payload.get("request_id") != str(row["request_id"])
        or plan.get("request", {}).get("request_id") != str(row["request_id"])
    ):
        raise WorkspaceError(409, "Retained financial discovery evidence integrity failed")
    implementation = plan["implementation"]["implementation_id"]
    if implementation not in FINANCIAL_IMPLEMENTATIONS or payload.get("status") != "SUCCEEDED":
        return None
    source = (
        plan.get("source_document")
        if implementation == FINANCIAL_IMPLEMENTATIONS[0]
        else plan.get("accepted_movements")
    )
    if not source or str(source.get("company_id")) != str(company_id):
        return None
    return {
        "invocation_id": str(row["request_id"]),
        "function": plan["function"],
        "implementation_id": implementation,
        "receipt_hash": row["proof_hash"],
        "recorded_at": row["recorded_at"].isoformat(),
        "run_id": payload["run_id"],
        "valid_at": plan["request"]["valid_at"],
        "known_at": plan["request"]["known_at"],
        "source": {
            key: source[key]
            for key in (
                "company_id",
                "document_id",
                "sha256",
                "sheet",
                "scope",
                "binding",
                "context",
                "selection",
                "observed_from",
                "observed_through",
                "source_invocation_id",
                "source_invocation_receipt_hash",
                "source_receipt_hash",
                "reconciliation_receipt_hash",
                "result_sha256",
                "source_valid_at",
                "source_known_at",
                "journal_observed_at",
            )
            if key in source
        },
        "state": "RETAINED_RESULT_REFERENCE",
        "reopen": "SEMANTIC_ANALYSIS"
        if implementation == FINANCIAL_IMPLEMENTATIONS[0]
        else "FUNCTION_HISTORY",
        "current_use_authorized": False,
        "business_effect_authorized": False,
    }


def retained_item(
    row: dict[str, Any], principal: Principal, company_id: UUID
) -> dict[str, Any] | None:
    try:
        return _retained_item(row, principal, company_id)
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkspaceError(409, "Retained financial discovery metadata is invalid") from exc


def discover(
    principal: Principal,
    company_id: UUID,
    *,
    valid_at: datetime | None = None,
    known_at: datetime | None = None,
    after_function_id: UUID | None = None,
    after_invocation_id: UUID | None = None,
) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    if str(company_id) != principal.scope.legal_entity_id:
        raise WorkspaceError(404, "Financial discovery unavailable for this company")
    snapshot = company_context.resolve(principal, company_id, valid_at, known_at)
    context = snapshot.get("context")
    if not context or context["company"]["resource_id"] != str(company_id):
        raise WorkspaceError(404, "Financial discovery requires an established company context")
    catalog = function_catalog.discover(principal, after_function_id)
    capabilities, unavailable = [], []
    with function_invocations._database(principal) as cursor:
        for item in catalog["items"]:
            if (
                item["attributes"].get("definition", {}).get("implementation_id")
                not in FINANCIAL_IMPLEMENTATIONS
            ):
                continue
            dependencies = cursor.execute(
                "SELECT v.* FROM resource_dependencies d JOIN resource_versions v "
                "ON v.tenant_id=d.tenant_id AND v.resource_id=d.target_resource_id "
                "AND v.version_id=d.target_version_id WHERE d.tenant_id=%s "
                "AND d.version_id=%s LIMIT 101",
                (principal.scope.tenant_id, item["reference"]["version_id"]),
            ).fetchall()
            try:
                if len(dependencies) > 100:
                    raise WorkspaceError(409, "Financial capability exceeds dependency bound")
                value = capability(item, dependencies, context)
                if value:
                    capabilities.append(value)
            except (WorkspaceError, ValueError, KeyError, TypeError) as exc:
                unavailable.append(
                    {
                        "function": item["reference"],
                        "state": "UNAVAILABLE",
                        "reason": exc.detail
                        if isinstance(exc, WorkspaceError)
                        else "Financial capability contract is incomplete",
                    }
                )
        rows = cursor.execute(
            "SELECT i.request_id,i.exact_scope,i.plan,i.plan_hash,"
            "r.payload,r.proof_hash,r.recorded_at "
            "FROM function_invocations i JOIN function_invocation_results r "
            "USING(tenant_id,request_id) "
            "WHERE i.tenant_id=%s AND i.exact_scope=%s::jsonb AND r.exact_scope=i.exact_scope "
            "AND r.status='SUCCEEDED' AND i.plan->'implementation'->>'implementation_id'=ANY(%s) "
            "AND (%s::uuid IS NULL OR i.request_id>%s) ORDER BY i.request_id LIMIT 51",
            (
                principal.scope.tenant_id,
                json.dumps(principal.scope.model_dump(mode="json")),
                list(FINANCIAL_IMPLEMENTATIONS),
                after_invocation_id,
                after_invocation_id,
            ),
        ).fetchall()
    results = [value for row in rows[:50] if (value := retained_item(row, principal, company_id))]
    return {
        "contract": "company-financial-results/1",
        "company": context["company"],
        "valid_at": snapshot["valid_at"],
        "known_at": snapshot["known_at"],
        "catalog_checked_at": datetime.now(UTC).isoformat(),
        "sources": context["accounting_sources"],
        "capabilities": capabilities,
        "unavailable_capabilities": unavailable,
        "results": results,
        "next_function_cursor": catalog["next_cursor"],
        "next_invocation_cursor": str(rows[49]["request_id"]) if len(rows) > 50 else None,
        "current_use_authorized": False,
        "business_effect_authorized": False,
    }
