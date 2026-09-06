from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from test_seg_expense_source import workbook

from finai_api.domain.authority import ExactScope
from finai_api.domain.review import Principal
from finai_api.services import source_company_alias as aliases
from finai_api.services.workspace import WorkspaceError


def fixture(monkeypatch):
    principal = Principal(
        actor_id="synthetic-alias",
        display_name="Synthetic alias review",
        scope=ExactScope(
            tenant_id=uuid4(), legal_entity_id="synthetic", period="2026-09", currency="GEL"
        ),
        permissions=("ontology_read", "ontology_propose"),
    )
    content = workbook()
    monkeypatch.setattr(
        aliases, "read_source", lambda *_: ({"source_sha256": sha256(content).hexdigest()}, content)
    )
    company = {
        "resource_id": str(uuid4()),
        "version_id": str(uuid4()),
        "object_type": "LegalEntity",
        "display_name": "Existing corporate-disclosure identity",
        "authority_state": "APPROVED",
        "evidence_class": "SOURCE_BOUND",
        "attributes": {"evidence_id": str(uuid4())},
        "system_from": datetime.now(UTC).isoformat(),
    }
    monkeypatch.setattr(
        aliases, "_effective_resources", lambda *_: {company["resource_id"]: company}
    )
    monkeypatch.setattr(aliases.resources, "current_resources", lambda *_: {})
    monkeypatch.setattr(aliases.resources, "propose", lambda _principal, proposal: proposal)
    return principal, company


def test_alias_proposal_reuses_existing_company_and_retains_exact_label_coordinate(monkeypatch):
    principal, company = fixture(monkeypatch)
    company_id = UUID(company["resource_id"])
    result = aliases.inspect(principal, "ir_synthetic", "Base", "seg_expense_base", company_id)
    assert result["company"]["display_name"] != result["source_label"]
    assert result["coordinate"] == "Base!D2"
    assert result["can_propose"] and not result["accepted"]
    assert not result["accounting_use_authorized"]
    proposal = aliases.propose(
        principal,
        "ir_synthetic",
        "Base",
        "seg_expense_base",
        company_id,
        "Review observed label against the already accepted company",
    )
    assert {m.object_type for m in proposal.mutations} == {
        "Alias",
        "SourceRecord",
        "SourceEvidence",
    }
    alias = next(m for m in proposal.mutations if m.object_type == "Alias")
    assert alias.evidence_class == "USER_ASSERTED"
    assert all(
        m.evidence_class == "SOURCE_BOUND" for m in proposal.mutations if m.object_type != "Alias"
    )
    assert alias.attributes["target_id"] == company["resource_id"]
    assert proposal.source_versions[alias.resource_id][company_id] == UUID(company["version_id"])
    records = {str(m.resource_id): m.model_dump(mode="json") for m in proposal.mutations}
    records[company["resource_id"]] = company
    aliases.validate_alias(principal, alias, lambda identity, *_: records[identity])


@pytest.mark.parametrize("change", ["label", "external_id", "coordinate", "new_company"])
def test_alias_provenance_or_coproposed_company_cannot_be_substituted(monkeypatch, change):
    principal, company = fixture(monkeypatch)
    proposal = aliases.propose(
        principal,
        "ir_synthetic",
        "Base",
        "seg_expense_base",
        UUID(company["resource_id"]),
        "Review an existing company identity",
    )
    alias = next(m for m in proposal.mutations if m.object_type == "Alias")
    records = {str(m.resource_id): m.model_dump(mode="json") for m in proposal.mutations}
    records[company["resource_id"]] = company
    if change == "label":
        alias = alias.model_copy(update={"display_name": "Invented company label"})
    elif change == "external_id":
        attrs = deepcopy(alias.attributes)
        attrs["external_id"] = "0" * 64
        alias = alias.model_copy(update={"attributes": attrs})
    elif change == "coordinate":
        records[alias.attributes["source_record_id"]]["attributes"]["coordinate"] = "Base!M2"
    else:
        company.pop("system_from")
    with pytest.raises(WorkspaceError):
        aliases.validate_alias(principal, alias, lambda identity, *_: records[identity])


def test_different_retained_bytes_have_different_external_identity(monkeypatch):
    principal, _ = fixture(monkeypatch)
    first = aliases.observe(principal, "ir_synthetic", "Base", "seg_expense_base")
    content = workbook(replacement={"D2": "Another explicitly observed source company"})
    monkeypatch.setattr(
        aliases, "read_source", lambda *_: ({"source_sha256": sha256(content).hexdigest()}, content)
    )
    second = aliases.observe(principal, "ir_synthetic", "Base", "seg_expense_base")
    assert first["external_id"] != second["external_id"]
    assert first["alias_id"] != second["alias_id"]
