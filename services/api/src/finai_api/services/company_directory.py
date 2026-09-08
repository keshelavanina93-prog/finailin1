"""Business chooser classification over an already authorized ontology snapshot.

This projection grants no access and changes no identity. Its caller owns RLS and
valid/known-time selection. Retained observations remain available as evidence.
"""

from typing import Any


def project(nodes: list[dict[str, Any]], pins: dict[tuple[str, str], str]) -> dict[str, Any]:
    eligible = {
        node["resource_id"]: node
        for node in nodes
        if node.get("authority_state") == "APPROVED"
        and node.get("evidence_class") in {"USER_ASSERTED", "SOURCE_BOUND"}
    }

    def linked(node: dict[str, Any], field: str, kind: str) -> dict[str, Any] | None:
        target = eligible.get(node["attributes"].get(field))
        if (
            target
            and target["object_type"] == kind
            and pins.get((node["version_id"], field)) == target["version_id"]
        ):
            return target
        return None

    configured: dict[str, list[str]] = {}
    source_ids: set[str] = set()
    reported_ids: set[str] = set()
    for node in eligible.values():
        kind = node["object_type"]
        if kind == "CompanyWorkspace" and node["evidence_class"] == "USER_ASSERTED":
            company = linked(node, "company_id", "LegalEntity")
            if (
                company
                and linked(node, "enterprise_id", "EnterpriseGroup")
                and linked(node, "domain_pack_id", "DomainPack")
            ):
                configured.setdefault(company["resource_id"], []).append(node["resource_id"])
        elif kind == "SourceAccountingScope":
            company = linked(node, "legal_entity_id", "LegalEntity")
            if company:
                source_ids.add(company["resource_id"])
        elif kind == "CorporateDisclosureBinding":
            if linked(node, "observation_id", "SourceCorporateObservation"):
                for field in ("reporter_id", "related_entity_id"):
                    company = linked(node, field, "LegalEntity")
                    if company:
                        reported_ids.add(company["resource_id"])

    companies, sources, reported, unclassified = [], [], [], []
    for node in eligible.values():
        if node["object_type"] != "LegalEntity":
            continue
        identifier = node["resource_id"]
        declared = node["evidence_class"] == "USER_ASSERTED"
        if declared or identifier in configured:
            companies.append(
                {
                    "company": node,
                    "basis": "EXPLICIT_COMPANY_DECLARATION" if declared else "CONFIGURED_WORKSPACE",
                    "workspace_ids": sorted(configured.get(identifier, [])),
                }
            )
            continue
        # These are producer identity namespaces, never name/region heuristics.
        source = identifier in source_ids or node["identity_key"].startswith("observed-company:")
        filing = identifier in reported_ids or node["identity_key"].startswith("reported-code:")
        if source:
            sources.append(node)
        if filing:
            reported.append(node)
        if not source and not filing:
            unclassified.append(node)
    return {
        "contract": "company-directory/1",
        "companies": companies,
        "source_identities": sources,
        "reported_parties": reported,
        "unclassified_identities": unclassified,
    }
