"""Explicitly hypothetical multi-domain modeling proposal; never authentic company records."""

from datetime import UTC, datetime

from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.domain.review import Principal


def socar_reference(principal: Principal) -> ResourceProposal:
    tenant = principal.scope.tenant_id
    specs = [
        (
            "holding",
            "EnterpriseGroup",
            "SOCAR Georgia — reference model",
            {"code": "SOCAR-REFERENCE"},
        ),
        ("petroleum", "BusinessDomain", "Petroleum industry classification", {"code": "PETROLEUM"}),
        ("gas", "BusinessDomain", "Gas industry classification", {"code": "GAS"}),
        (
            "petroleum-entity",
            "LegalEntity",
            "SOCAR Georgia Petroleum — company reference",
            {"jurisdiction": "GE"},
        ),
        (
            "gas-entity",
            "LegalEntity",
            "SOCAR Georgia Gas — company reference",
            {"jurisdiction": "GE"},
        ),
        (
            "retail-unit",
            "BusinessUnit",
            "Retail operating unit — placeholder",
            {"code": "RETAIL-REFERENCE"},
        ),
        (
            "licensed-operator",
            "LicensedOperator",
            "Gas licensed operator — placeholder",
            {"licence_reference": "UNVERIFIED-REFERENCE"},
        ),
        (
            "licence",
            "Licence",
            "Gas distribution licence — unverified reference",
            {"identifier": "UNVERIFIED-REFERENCE", "jurisdiction": "GE"},
        ),
        (
            "consolidation",
            "ConsolidationGroup",
            "Group consolidation — reference",
            {"code": "GROUP-REFERENCE"},
        ),
        (
            "network",
            "OperationalNetwork",
            "Gas distribution network — reference",
            {"code": "NETWORK-REFERENCE"},
        ),
        (
            "petroleum-pack",
            "DomainPack",
            "Petroleum industry classification semantics",
            {"code": "PETROLEUM", "version": "planned/1"},
        ),
        (
            "gas-pack",
            "DomainPack",
            "Georgian gas domain semantics",
            {"code": "GEORGIAN_GAS", "version": "planned/1"},
        ),
    ]
    specs.sort(
        key=lambda item: {"holding": 0, "petroleum-entity": 1, "gas-entity": 2}.get(item[0], 3)
    )
    ids = {key: canonical_id(tenant, kind, f"reference:socar:{key}") for key, kind, _, _ in specs}
    mutations = [
        ResourceMutation(
            resource_id=ids[key],
            object_type=kind,
            identity_key=f"reference:socar:{key}",
            display_name=name,
            attributes=attributes,
            valid_from=datetime.now(UTC),
            evidence_class="REFERENCE_TEMPLATE",
        )
        for key, kind, name, attributes in specs
    ]
    links = [
        ("holding", "HAS_LEGAL_ENTITY", "petroleum-entity"),
        ("holding", "HAS_LEGAL_ENTITY", "gas-entity"),
        ("petroleum", "OPERATED_BY", "petroleum-entity"),
        ("gas", "OPERATED_BY", "gas-entity"),
        ("gas-entity", "HAS_OPERATOR", "licensed-operator"),
        ("petroleum-entity", "HAS_BUSINESS_UNIT", "retail-unit"),
        ("petroleum-entity", "PARTICIPATES_IN", "consolidation"),
        ("gas-entity", "PARTICIPATES_IN", "consolidation"),
        ("licensed-operator", "OPERATES", "network"),
        ("licensed-operator", "HOLDS_LICENSE", "licence"),
        ("petroleum-entity", "USES_DOMAIN_PACK", "petroleum-pack"),
        ("gas-entity", "USES_DOMAIN_PACK", "gas-pack"),
    ]
    for source, relation, target in links:
        key = f"reference:socar:{source}:{relation}:{target}"
        mutations.append(
            ResourceMutation(
                resource_id=canonical_id(tenant, "Relationship", key),
                object_type="Relationship",
                identity_key=key,
                display_name=f"{source} · {relation.replace('_', ' ').lower()} · {target}",
                attributes={
                    "source_id": str(ids[source]),
                    "target_id": str(ids[target]),
                    "relation_id": str(canonical_id(tenant, "LinkType", relation)),
                },
                valid_from=datetime.now(UTC),
                evidence_class="REFERENCE_TEMPLATE",
            )
        )
    return ResourceProposal(
        title="SOCAR company-first reference model",
        rationale=(
            "Hypothetical structural reference only. Legal entities, "
            "operators, licence and membership facts require authentic "
            "evidence before real use."
        ),
        access_entity="__TENANT__",
        mutations=mutations,
    )
