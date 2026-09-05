import os
from datetime import UTC, datetime
from uuid import UUID, uuid4, uuid5

import pytest

from finai_api.domain.authority import ExactScope
from finai_api.domain.resources import ResourceMutation, ResourceProposal, ResourceReview
from finai_api.domain.review import Principal
from finai_api.services import resources
from finai_api.services.resource_rollback import RollbackRequest, rollback_draft
from finai_api.services.workspace import WorkspaceError


@pytest.mark.skipif(os.environ.get("G8_BINDING_DB_TEST") != "1", reason="Local PostgreSQL opt-in")
def test_reviewed_rollback_retains_history_and_dependency_definitions() -> None:
    operator = Principal(
        actor_id="rollback-proposer",
        display_name="Synthetic rollback",
        scope=ExactScope(
            tenant_id=UUID("805d8a32-d12b-4268-a236-b0b16e59da9f"),
            legal_entity_id="rollback-" + uuid4().hex,
            period="2026-08",
            currency="GEL",
        ),
        permissions=("ontology_read", "ontology_propose", "ontology_review", "ontology_admin"),
    )
    reviewer = operator.model_copy(update={"actor_id": "rollback-reviewer"})
    semantic = ResourceMutation(
        object_type="SemanticContract",
        identity_key="rollback:" + uuid4().hex,
        display_name="Original meaning",
        attributes={"kind": "identifier"},
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
    )
    schema = ResourceMutation(
        object_type="SchemaDefinition",
        identity_key="Restore" + uuid4().hex,
        display_name="Original schema",
        attributes={
            "additional_fields": False,
            "fields": {
                "code": {
                    "field_id": str(uuid4()),
                    "semantic_id": str(semantic.resource_id),
                    "kind": "identifier",
                    "required": True,
                }
            },
        },
        valid_from=semantic.valid_from,
    )

    def publish(items: list[ResourceMutation]) -> ResourceProposal:
        proposal = ResourceProposal(
            title="Synthetic rollback setup",
            rationale="Controlled synthetic acceptance",
            access_entity="__PLATFORM__",
            mutations=items,
        )
        resources.propose(operator, proposal)
        resources.review(
            reviewer,
            proposal.proposal_id,
            ResourceReview(decision="APPROVED", rationale="Independent definition review"),
        )
        return proposal

    original = publish([semantic, schema])
    versions = {
        item.resource_id: uuid5(original.proposal_id, str(item.resource_id))
        for item in original.mutations
    }
    changed = publish(
        [
            item.model_copy(
                update={
                    "expected_version_id": versions[item.resource_id],
                    "display_name": "Corrected " + item.display_name,
                }
            )
            for item in original.mutations
        ]
    )
    request = RollbackRequest(
        versions=versions,
        rationale="Restore original meaning after independent review",
        valid_from=datetime(2026, 9, 1, tzinfo=UTC),
    )
    with pytest.raises(WorkspaceError, match="dependency changed"):
        rollback_draft(
            operator,
            request.model_copy(
                update={"versions": {schema.resource_id: versions[schema.resource_id]}}
            ),
        )
    draft = rollback_draft(operator, request)
    assert draft.restores_versions == versions
    tampered = draft.model_copy(
        update={
            "proposal_id": uuid4(),
            "mutations": [
                draft.mutations[0].model_copy(update={"display_name": "Forged restoration"}),
                draft.mutations[1],
            ],
        }
    )
    with pytest.raises(WorkspaceError, match="retained approved definition"):
        resources.propose(operator, tampered)
    resources.propose(operator, draft)
    assert UUID(
        str(resources.get_resource(operator, semantic.resource_id)["resource"]["version_id"])
    ) == uuid5(changed.proposal_id, str(semantic.resource_id))
    with pytest.raises(WorkspaceError):
        resources.review(
            operator,
            draft.proposal_id,
            ResourceReview(decision="APPROVED", rationale="Invalid self approval attempt"),
        )
    resources.review(
        reviewer,
        draft.proposal_id,
        ResourceReview(decision="APPROVED", rationale="Independent restoration acceptance"),
    )
    restored = resources.get_resource(operator, semantic.resource_id)
    assert restored["resource"]["display_name"] == semantic.display_name
    assert len(restored["versions"]) == 3
    with resources.resource_connection(operator) as conn:
        pin = conn.execute(
            "SELECT target_version_id FROM resource_dependencies WHERE tenant_id=%s "
            "AND version_id=%s AND target_resource_id=%s",
            (
                operator.scope.tenant_id,
                uuid5(draft.proposal_id, str(schema.resource_id)),
                semantic.resource_id,
            ),
        ).fetchone()
        assert pin and pin[0] == uuid5(draft.proposal_id, str(semantic.resource_id))
