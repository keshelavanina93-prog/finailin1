"""Company-specific licence evidence for regulatory assessments."""

from finai_api.domain.ontology_catalog import canonical_id
from finai_api.services import resources


def licence_bindings(principal, company_id, at, known_at):
    relation_id = str(canonical_id(principal.scope.tenant_id, "LinkType", "HOLDS_LICENSE"))
    result = []
    licences = {}
    for offset in range(0, 5000, 100):
        page = resources.list_resources(principal, "Licence", "", offset, at, known_at)
        licences.update(
            {
                str(row.resource_id): str(row.version_id)
                for row in page
                if row.authority_state == "APPROVED" and row.evidence_class != "REFERENCE_TEMPLATE"
            }
        )
        if len(page) < 100:
            break
    else:
        return [], False
    for offset in range(0, 5000, 100):
        page = resources.list_resources(principal, "Relationship", "", offset, at, known_at)
        for row in page:
            attrs = row.attributes
            if (
                attrs.get("relation_id") == relation_id
                and attrs.get("source_id") == str(company_id)
                and attrs.get("evidence_id")
                and row.evidence_class != "REFERENCE_TEMPLATE"
            ):
                references = resources.version_references(principal, row.version_id)
                licence = references.get("target_id", {})
                if not licence or licences.get(licence.get("resource_id")) != licence.get(
                    "version_id"
                ):
                    continue
                result.append(
                    {
                        "resource_id": str(row.resource_id),
                        "version_id": str(row.version_id),
                        "references": references,
                    }
                )
        if len(page) < 100:
            return result, True
    return result, False


def bind_assessment(assessment, rule_references, holders, complete):
    """A group disclosure never substitutes for a holder-to-licence relationship."""
    licence = rule_references.get("licence_id")
    company = rule_references.get("legal_entity_id")
    matches = [
        holder
        for holder in holders
        if licence
        and company
        and holder["references"].get("source_id") == company
        and holder["references"].get("target_id") == licence
    ]
    state = (
        "VERIFIED_VERSION_BINDING"
        if complete and matches
        else "LICENCE_SCAN_INCOMPLETE"
        if not complete
        else "LICENCE_BINDING_REQUIRED"
    )
    return {
        **assessment,
        "applicability": assessment["applicability"]
        if state == "VERIFIED_VERSION_BINDING" or assessment["applicability"] == "NOT_APPLICABLE"
        else state,
        "effective_obligation": assessment["effective_obligation"]
        and state == "VERIFIED_VERSION_BINDING",
        "licence_context": {"state": state, "holder_relationships": matches},
    }
