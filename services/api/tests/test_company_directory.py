from copy import deepcopy

import pytest

from finai_api.services.company_context import project as context_project
from finai_api.services.company_directory import project


def node(identifier, kind="LegalEntity", evidence="SOURCE_BOUND", **attributes):
    return {
        "resource_id": identifier,
        "version_id": identifier + "-v1",
        "object_type": kind,
        "identity_key": identifier,
        "display_name": identifier,
        "attributes": attributes,
        "authority_state": "APPROVED",
        "evidence_class": evidence,
    }


def fixture():
    company = node("observed-company:region")
    company["display_name"] = "Kakheti"
    enterprise = node("enterprise", "EnterpriseGroup", "USER_ASSERTED")
    pack = node("pack", "DomainPack", "USER_ASSERTED")
    workspace = node(
        "workspace",
        "CompanyWorkspace",
        "USER_ASSERTED",
        company_id=company["resource_id"],
        enterprise_id="enterprise",
        domain_pack_id="pack",
    )
    pins = {
        (workspace["version_id"], field): target["version_id"]
        for field, target in (
            ("company_id", company),
            ("enterprise_id", enterprise),
            ("domain_pack_id", pack),
        )
    }
    return [company, enterprise, pack, workspace], pins


def test_source_label_is_evidence_not_company_and_declaration_needs_no_workspace():
    source = node("observed-company:region")
    source["display_name"] = "Kakheti"
    declared = node("manual", evidence="USER_ASSERTED")
    declared["display_name"] = "Kakheti"  # Name cannot affect classification.
    result = project([source, declared], {})
    assert result["contract"] == "company-directory/1"
    assert result["source_identities"] == [source]
    assert result["companies"] == [
        {
            "company": declared,
            "basis": "EXPLICIT_COMPANY_DECLARATION",
            "workspace_ids": [],
        }
    ]


def test_exact_reviewed_workspace_admits_source_identity_once():
    nodes, pins = fixture()
    result = project(nodes, pins)
    assert result["companies"] == [
        {
            "company": nodes[0],
            "basis": "CONFIGURED_WORKSPACE",
            "workspace_ids": ["workspace"],
        }
    ]
    assert result["source_identities"] == []


@pytest.mark.parametrize("index", [0, 1, 2, 3])
@pytest.mark.parametrize(
    "field,value",
    [
        ("authority_state", "REVOKED"),
        ("evidence_class", "REFERENCE_TEMPLATE"),
        ("object_type", "BusinessUnit"),
    ],
)
def test_invalid_workspace_or_target_cannot_admit(index, field, value):
    nodes, pins = fixture()
    nodes[index][field] = value
    assert project(nodes, pins)["companies"] == []


@pytest.mark.parametrize("field", ["company_id", "enterprise_id", "domain_pack_id"])
def test_stale_dependency_cannot_admit(field):
    nodes, pins = fixture()
    pins[("workspace-v1", field)] = "historical-version"
    assert project(nodes, pins)["companies"] == []


def test_out_of_scope_target_is_never_resolved_outside_supplied_snapshot():
    nodes, pins = fixture()
    assert project(nodes[1:], pins)["companies"] == []
    assert project([nodes[0], nodes[2], nodes[3]], pins)["companies"] == []
    nodes[3]["evidence_class"] = "SOURCE_BOUND"
    assert project(nodes, pins)["companies"] == []


def test_source_and_filing_can_overlap_but_registration_never_admits():
    company = node("reported-code:123", registration_code="123")
    scope = node("scope", "SourceAccountingScope", legal_entity_id=company["resource_id"])
    result = project([company, scope], {("scope-v1", "legal_entity_id"): company["version_id"]})
    assert result["companies"] == []
    assert result["source_identities"] == result["reported_parties"] == [company]
    unknown = node("unknown", registration_code="999")
    assert project([unknown], {})["unclassified_identities"] == [unknown]


def test_filing_links_require_exact_snapshot_provenance():
    company = node("party")
    observation = node("observation", "SourceCorporateObservation")
    binding = node(
        "binding",
        "CorporateDisclosureBinding",
        "USER_ASSERTED",
        related_entity_id="party",
        observation_id="observation",
    )
    pins = {
        ("binding-v1", "related_entity_id"): "party-v1",
        ("binding-v1", "observation_id"): "observation-v1",
    }
    assert project([company, observation, binding], pins)["reported_parties"] == [company]
    pins[("binding-v1", "related_entity_id")] = "party-old"
    assert project([company, observation, binding], pins)["reported_parties"] == []


def test_context_addition_preserves_legacy_source_journey_without_mutation():
    company = node("observed-company:source")
    scope = node("scope", "SourceAccountingScope", legal_entity_id=company["resource_id"])
    nodes = [company, scope]
    before = deepcopy(nodes)
    result = context_project(nodes, {("scope-v1", "legal_entity_id"): company["version_id"]})
    assert result["source_companies"] == [company]
    assert result["company_directory"]["companies"] == []
    assert result["company_directory"]["source_identities"] == [company]
    assert result["context"] is None
    assert nodes == before
