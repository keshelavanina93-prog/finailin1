"""Synthetic retained bytes and native reviewed aliases; no accounting activation."""

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from test_seg_expense_source import workbook

from finai_api.domain.authority import ExactScope
from finai_api.domain.resources import ResourceMutation, ResourceProposal, ResourceReview
from finai_api.domain.review import Principal
from finai_api.services import resources, source_documents
from finai_api.services import source_accounting_context as accounting_context
from finai_api.services import source_company_alias as aliases
from finai_api.services.workspace import WorkspaceError


@pytest.mark.skipif(os.environ.get("G8_BINDING_DB_TEST") != "1", reason="Opt-in native DB")
def test_scheduled_company_and_alias_heads_do_not_change_current_attribution():
    p = Principal(
        actor_id="synthetic-alias-time-author",
        display_name="Synthetic alias time",
        scope=ExactScope(
            tenant_id=UUID("805d8a32-d12b-4268-a236-b0b16e59da9f"),
            legal_entity_id="synthetic-alias-time-" + uuid4().hex,
            period="2026-09",
            currency="GEL",
        ),
        permissions=(
            "ingest",
            "ontology_read",
            "ontology_admin",
            "ontology_propose",
            "ontology_review",
        ),
    )
    reviewer = p.model_copy(update={"actor_id": "synthetic-alias-time-reviewer"})
    content = workbook(replacement={"D2": "Synthetic source company " + uuid4().hex})
    document_id = source_documents.retain_document(
        p, "SYNTHETIC alias temporal acceptance.xlsx", content
    )["document_id"]

    def approve(proposal):
        resources.review(
            reviewer,
            proposal.proposal_id,
            ResourceReview(
                decision="APPROVED",
                rationale="Review synthetic temporal source identity",
            ),
        )

    def publish(*mutations):
        proposal = ResourceProposal(
            title="Synthetic source identity time acceptance",
            rationale="Current identity must stay distinct from future editing heads",
            access_entity=p.scope.legal_entity_id,
            mutations=list(mutations),
        )
        resources.propose(p, proposal)
        approve(proposal)

    company = ResourceMutation(
        object_type="LegalEntity",
        identity_key="synthetic:" + uuid4().hex,
        display_name="Current synthetic company",
        attributes={},
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
    )
    other = company.model_copy(
        update={
            "resource_id": uuid4(),
            "identity_key": "synthetic:" + uuid4().hex,
            "display_name": "Other synthetic company",
        }
    )
    publish(company, other)
    proposed = aliases.propose(
        p,
        document_id,
        "Base",
        "seg_expense_base",
        company.resource_id,
        "Bind retained synthetic label to existing company identity",
    )
    alias_proposal_id = proposed.proposal.proposal_id
    resources.review(
        reviewer,
        alias_proposal_id,
        ResourceReview(
            decision="APPROVED",
            rationale="Review synthetic source company alias",
        ),
    )
    before = aliases.inspect(p, document_id, "Base", "seg_expense_base", company.resource_id)
    assert before["accepted"] and not before["accounting_use_authorized"]
    alias = before["alias"]
    scheduled_alias = ResourceMutation(
        resource_id=UUID(alias["resource_id"]),
        expected_version_id=UUID(alias["version_id"]),
        object_type="Alias",
        identity_key=alias["identity_key"],
        display_name=alias["display_name"],
        attributes={**alias["attributes"], "target_id": str(other.resource_id)},
        valid_from=datetime.now(UTC) + timedelta(days=30),
        evidence_class="USER_ASSERTED",
    )
    future_company = company.model_copy(
        update={
            "expected_version_id": UUID(before["company"]["version_id"]),
            "display_name": "Future synthetic company name",
            "valid_from": datetime.now(UTC) + timedelta(days=30),
        }
    )
    publish(future_company, scheduled_alias)
    current = aliases.inspect(p, document_id, "Base", "seg_expense_base", company.resource_id)
    assert current["accepted"]
    assert current["company"] == before["company"]
    assert current["alias"] == alias
    assert not current["accounting_use_authorized"]
    readiness = accounting_context.inspect(
        p, document_id, "Base", "seg_expense_base", company.resource_id
    )
    assert readiness["company_binding"]["company"] == before["company"]
    assert readiness["observed"]["company_alias_id"] == alias["resource_id"]
    assert not readiness["canonical_ready"]  # No accounting chart was invented.
    mismatch = aliases.inspect(p, document_id, "Base", "seg_expense_base", other.resource_id)
    assert not mismatch["accepted"]
    with pytest.raises(WorkspaceError, match="already current"):
        aliases.propose(
            p,
            document_id,
            "Base",
            "seg_expense_base",
            company.resource_id,
            "An unchanged current attribution must not override its scheduled revision",
        )
    alias_head = resources.get_resource(p, UUID(alias["resource_id"]))["resource"]
    publish(
        scheduled_alias.model_copy(
            update={
                "expected_version_id": UUID(alias_head["version_id"]),
                "authority_state": "REVOKED",
                "valid_from": datetime.now(UTC),
            }
        )
    )
    revoked = aliases.inspect(p, document_id, "Base", "seg_expense_base", other.resource_id)
    assert not revoked["accepted"]
    assert revoked["alias"]["authority_state"] == "REVOKED"
    assert revoked["alias"]["version_id"] != alias["version_id"]
    future_only = company.model_copy(update={
        "resource_id": uuid4(), "identity_key": "synthetic:" + uuid4().hex,
        "valid_from": datetime.now(UTC) + timedelta(days=30),
    })
    publish(future_only)
    with pytest.raises(WorkspaceError, match="existing accepted canonical legal entity"):
        aliases.inspect(p, document_id, "Base", "seg_expense_base", future_only.resource_id)
