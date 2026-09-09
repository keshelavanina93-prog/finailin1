"""Compile and publish finance definitions through the existing independent review path."""

import json
from copy import deepcopy
from hashlib import sha256
from importlib.resources import files
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from psycopg.rows import dict_row

from finai_api.domain.finance_catalog_compiler import compile_finance_catalog
from finai_api.domain.finance_dimensions import DimensionValidationRequest, policies, validate
from finai_api.domain.finance_ontology import CatalogProposalRequest, FinanceCapabilityDefinition
from finai_api.domain.ontology_catalog import CATALOG_NAMESPACE, canonical_id, platform_definitions
from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services import resources
from finai_api.services.schema_compatibility import SchemaCompatibilityError, schema_compatibility
from finai_api.services.workspace import WorkspaceError

PHASES = (
    "SemanticContract",
    "SchemaDefinition",
    "LinkType",
    "ObjectInterface",
    "ObjectTypeGroup",
    "ObjectTypeImplementation",
    "ObjectSetDefinition",
    "ObjectBinding",
    "DerivedProperty",
    "FactContract",
    "FinanceCapabilityDefinition",
)

FINANCE_FUNCTIONS: tuple[dict[str, Any], ...] = (
    {
        "api_name": "fn.tb_from_journal",
        "implementation_id": "finance.canonical-journal-turnover/1",
        "operation": "trial_balance",
        "endpoint": "/v1/ontology/finance/journal-trial-balance",
        "state": "EXECUTABLE_WITH_EXACT_CANONICAL_PINS",
    },
    {
        "api_name": "fn.ytd_flow",
        "implementation_id": "finance.fact-contract/1",
        "operation": "ytd_flow",
        "endpoint": "/v1/ontology/finance/execute",
        "state": "EXECUTABLE_WITH_REVIEWED_FACT_CONTRACT",
    },
    {
        "api_name": "fn.closing_as_of",
        "implementation_id": "finance.fact-contract/1",
        "operation": "closing_as_of",
        "endpoint": "/v1/ontology/finance/execute",
        "state": "EXECUTABLE_WITH_REVIEWED_FACT_CONTRACT",
    },
    {
        "api_name": "fn.reconcile_parent",
        "implementation_id": "finance.fact-contract/1",
        "operation": "reconcile_parent",
        "endpoint": "/v1/ontology/finance/execute",
        "state": "EXECUTABLE_WITH_REVIEWED_FACT_CONTRACT",
    },
    {
        "api_name": "fn.classify_fact",
        "implementation_id": "finance.classification-rules/1",
        "operation": "classify_fact",
        "endpoint": "/v1/ontology/finance/classify",
        "state": "EXECUTABLE_AS_CANDIDATE_ONLY",
    },
    {
        "api_name": "fn.validate_dimensions",
        "implementation_id": "finance.canonical-dimensions/1",
        "operation": "validate_dimensions",
        "endpoint": "/v1/ontology/finance/dimensions/validate",
        "state": "EXECUTABLE_AS_CANDIDATE_ONLY",
    },
    {
        "api_name": "fn.petroleum_pl",
        "implementation_id": "finance.reviewed-projection/1",
        "operation": "project",
        "projection_code": "PETROLEUM_PNL",
        "endpoint": "/v1/ontology/finance/execute",
        "state": "EXECUTABLE_WITH_REVIEWED_PROJECTION",
    },
    {
        "api_name": "fn.corporate_mr",
        "implementation_id": "finance.reviewed-projection/1",
        "operation": "project",
        "projection_code": "CORPORATE_MR",
        "endpoint": "/v1/ontology/finance/execute",
        "state": "EXECUTABLE_WITH_REVIEWED_PROJECTION",
    },
)

FINANCE_ACTIONS: tuple[dict[str, Any], ...] = (
    {
        "api_name": "act.promote_object_version",
        "endpoint": "/v1/ontology/proposals/{proposal_id}/decision",
        "changes_authority": True,
        "nyx_may_execute": False,
        "state": "INDEPENDENT_REVIEW_REQUIRED",
    },
    {
        "api_name": "act.rollback_publication",
        "endpoint": "/v1/ontology/rollback-proposal",
        "changes_authority": True,
        "nyx_may_execute": False,
        "state": "INDEPENDENT_REVIEW_REQUIRED",
    },
    {
        "api_name": "act.accept_mapping_version",
        "endpoint": "/v1/ontology/source-adoption/proposal",
        "changes_authority": True,
        "nyx_may_execute": False,
        "state": "INDEPENDENT_REVIEW_REQUIRED",
    },
    {
        "api_name": "act.propose_alignment",
        "endpoint": "/v1/ontology/finance/candidates/proposals",
        "changes_authority": False,
        "nyx_may_execute": True,
        "state": "CANDIDATE_PROPOSAL_ONLY",
    },
    {
        "api_name": "act.classify_chaotic_row",
        "endpoint": "/v1/ontology/finance/classify",
        "changes_authority": False,
        "nyx_may_execute": True,
        "state": "CANDIDATE_ONLY",
    },
)


def _digest(value: Any) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def domain_catalog() -> dict[str, Any]:
    package = files("finai_api").joinpath("catalog", "finance-domain.g8.v1.json")
    if package.is_file():
        value = json.loads(package.read_text(encoding="utf-8"))
    else:
        path = (
            Path(__file__).resolve().parents[5]
            / "packages/contracts/catalog/finance-domain.g8.v1.json"
        )
        value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("domain_id") != "g8.finance.domain.v1":
        raise WorkspaceError(503, "Finance domain package identity mismatch")
    definitions = [FinanceCapabilityDefinition.model_validate(row) for row in value["capabilities"]]
    if len({row.code for row in definitions}) != len(definitions):
        raise WorkspaceError(503, "Finance domain contains duplicate capabilities")
    return value


def dimension_policies() -> dict[str, Any]:
    """Return observed account-family semantics without promoting posting rules."""
    return {
        "contract": "finance-dimension-policy/1",
        "authority": "OBSERVED_LABELS_ONLY",
        "policies": [item.model_dump(mode="json") for item in policies()],
        "unknown_state": "UNKNOWN",
        "subkonto_rule": "Labels and slot order are not posting authority until RULE_EVIDENCED.",
    }


def validate_dimensions(request: DimensionValidationRequest) -> dict[str, Any]:
    return {
        "contract": "finance-dimension-validation/1",
        "authority": "CANDIDATE_ONLY",
        **validate(request),
    }


def compilation(tenant: UUID) -> Any:
    domain = domain_catalog()
    baseline = platform_definitions(tenant)
    reference = next(
        row
        for row in baseline
        if row["object_type"] == "SchemaDefinition" and row["identity_key"] == "ObjectSetDefinition"
    )
    for kind in (
        "FinanceCapabilityDefinition",
        "FinanceClassificationPolicy",
        "FinanceProjectionDefinition",
    ):
        specification = deepcopy(reference)
        specification.update(identity_key=kind, display_name=kind)
        for name, field in specification["attributes"]["fields"].items():
            field["field_id"] = str(uuid5(CATALOG_NAMESPACE, f"field:{kind}:{name}"))
        baseline.append(specification)
    compiled = compile_finance_catalog(tenant, baseline)
    for row in domain["capabilities"]:
        compiled.definitions.append(
            {
                "object_type": "FinanceCapabilityDefinition",
                "identity_key": "finance.capability." + row["code"],
                "display_name": row["name"],
                "attributes": {"definition": row},
            }
        )
    # The capability rows are part of the compiled plan, so refresh the
    # integrity manifest after appending them. A stale manifest would make a
    # reviewed catalog impossible to replay exactly.
    compiled.manifest["definitions_sha256"] = _digest(compiled.definitions)
    compiled.manifest["resources"] = [
        {
            "object_type": item["object_type"],
            "identity_key": item["identity_key"],
            "resource_id": str(
                canonical_id(tenant, item["object_type"], item["identity_key"])
            ),
            "content_sha256": _digest(item),
        }
        for item in compiled.definitions
    ]
    compiled.manifest["finance_capabilities"] = [row["code"] for row in domain["capabilities"]]
    compiled.manifest["finance_function_adapters"] = list(FINANCE_FUNCTIONS)
    compiled.manifest["finance_action_bindings"] = list(FINANCE_ACTIONS)
    return compiled


def _heads(principal: Principal, definitions: list[dict[str, Any]]) -> dict[UUID, dict[str, Any]]:
    identities = [
        canonical_id(principal.scope.tenant_id, row["object_type"], row["identity_key"])
        for row in definitions
    ]
    with (
        resources.resource_connection(principal) as conn,
        conn.cursor(row_factory=dict_row) as cursor,
    ):
        rows = cursor.execute(
            resources.HEAD_SELECT + "WHERE h.tenant_id=%s AND h.resource_id=ANY(%s::uuid[])",
            (principal.scope.tenant_id, identities),
        ).fetchall()
    return {row["resource_id"]: row for row in rows}


def accepted_definition_matches(spec: dict[str, Any], current: dict[str, Any] | None) -> bool:
    """Treat an accepted, semantically compatible schema superset as installed."""
    if not current or current["authority_state"] != "APPROVED":
        return False
    if current["attributes"] == spec["attributes"]:
        return True
    if spec["object_type"] != "SchemaDefinition":
        return False
    try:
        schema_compatibility(
            spec["identity_key"], current["attributes"], spec["attributes"]
        )
    except SchemaCompatibilityError:
        return False
    return True


def catalog(principal: Principal) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    compiled = compilation(principal.scope.tenant_id)
    digest = _digest(compiled.definitions)
    heads = _heads(principal, compiled.definitions)
    entries = []
    for spec in compiled.definitions:
        identity = canonical_id(
            principal.scope.tenant_id, spec["object_type"], spec["identity_key"]
        )
        current = heads.get(identity)
        matches = accepted_definition_matches(spec, current)
        entries.append(
            {
                "resource_id": str(identity),
                "object_type": spec["object_type"],
                "identity_key": spec["identity_key"],
                "display_name": spec["display_name"],
                "status": "INSTALLED"
                if matches
                else "CHANGE_REQUIRED"
                if current
                else "NOT_INSTALLED",
                "version_id": current["version_id"] if current else None,
                "expected_attributes": spec["attributes"],
            }
        )
    phases = [
        {
            "kind": kind,
            "pending": sum(
                row["object_type"] == kind and row["status"] != "INSTALLED" for row in entries
            ),
        }
        for kind in PHASES
    ]
    return {
        "catalog_id": "g8.ontology.finance.v1",
        "catalog_sha256": digest,
        "manifest": compiled.manifest,
        "diagnostics": compiled.diagnostics,
        "definitions": entries,
        "phases": phases,
        "ready": all(row["status"] == "INSTALLED" for row in entries),
        "company_facts_published": False,
    }


def functions(principal: Principal) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    return {
        "items": list(FINANCE_FUNCTIONS),
        "purpose": "DETERMINISTIC_FINANCE_EXECUTION_WITH_EXACT_REVIEWED_INPUTS",
        "authority_effect": "NONE",
    }


def actions(principal: Principal) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    return {
        "items": list(FINANCE_ACTIONS),
        "purpose": "GOVERNED_PROPOSAL_AND_REVIEW_ACTIONS",
        "authority_effect": "REVIEW_REQUIRED_FOR_AUTHORITY_CHANGES",
    }


def propose_catalog(principal: Principal, request: CatalogProposalRequest) -> Any:
    require_permission(principal, "ontology_admin")
    require_permission(principal, "ontology_propose")
    compiled = compilation(principal.scope.tenant_id)
    if _digest(compiled.definitions) != request.catalog_sha256:
        raise WorkspaceError(
            409, "Catalog changed since preview; review the current definition plan"
        )
    if request.phase not in PHASES:
        raise WorkspaceError(422, "Unknown catalog publication phase")
    pending = []
    heads = _heads(principal, compiled.definitions)
    for spec in compiled.definitions:
        if spec["object_type"] != request.phase:
            continue
        identity = canonical_id(
            principal.scope.tenant_id, spec["object_type"], spec["identity_key"]
        )
        current = heads.get(identity)
        if (
            current
            and current["authority_state"] == "APPROVED"
            and current["attributes"] == spec["attributes"]
        ):
            continue
        pending.append(
            ResourceMutation(
                resource_id=identity,
                expected_version_id=current["version_id"] if current else None,
                valid_from=request.valid_from,
                evidence_class="REFERENCE_TEMPLATE",
                **spec,
            )
        )
    selected = pending[request.offset : request.offset + request.limit]
    if not selected:
        raise WorkspaceError(409, "No pending definitions in this publication page")
    proposal = ResourceProposal(
        proposal_id=uuid5(
            request.request_id,
            f"finance-catalog:{request.catalog_sha256}:{request.phase}:{request.offset}",
        ),
        title="Publish finance ontology: " + request.phase,
        rationale=request.rationale,
        access_entity="__PLATFORM__",
        mutations=selected,
    )
    return resources.propose(principal, proposal)
