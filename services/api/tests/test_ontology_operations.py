"""A stale binding cannot produce a new effect; an existing effect remains recoverable."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.services import ontology_operations as operations
from finai_api.services.workspace import WorkspaceError


@pytest.mark.parametrize("already_retained", [False, True])
def test_binding_change_blocks_new_effect_but_not_receipt_recovery(monkeypatch, already_retained):
    binding, version = uuid4(), uuid4()
    proposal = ResourceProposal(
        title="Unit fixture binding",
        rationale="Isolated failure-boundary fixture; never published to a database",
        access_entity="fixture",
        mutations=[
            ResourceMutation(
                object_type="LegalEntity",
                identity_key="fixture",
                display_name="Fixture",
                attributes={},
                valid_from=datetime.now(UTC),
            )
        ],
    )
    record = {
        "definition": {"version": "ontology-action/1"},
        "request": {
            "prepared_proposal": proposal.model_dump(mode="json"),
            "invocation": {"binding_id": str(binding), "binding_version_id": str(version)},
        },
    }
    monkeypatch.setattr(operations, "require_permission", Mock())
    monkeypatch.setattr(operations.report_workflows, "read", Mock(return_value=record))
    events = Mock()
    monkeypatch.setattr(operations.report_workflows, "event", events)
    monkeypatch.setattr(
        operations.resources,
        "proposal_detail",
        Mock(
            return_value=SimpleNamespace(proposal=proposal),
            side_effect=None if already_retained else WorkspaceError(404, "Not retained"),
        ),
    )
    head = Mock(
        return_value={"resource": {"authority_state": "APPROVED", "version_id": str(uuid4())}}
    )
    monkeypatch.setattr(operations.resources, "get_resource", head)
    effect = Mock(return_value=SimpleNamespace(proposal=proposal))
    monkeypatch.setattr(operations.resources, "propose", effect)
    monkeypatch.setattr(operations, "read", Mock(return_value={"state": "PENDING_REVIEW"}))
    if already_retained:
        operations.resume(SimpleNamespace(actor_id="fixture"), "operation-fixture")
        head.assert_not_called()
        assert effect.call_args.args[1] == proposal
        assert events.call_args.args[2] == "proposal-receipt"
    else:
        with pytest.raises(WorkspaceError, match="Binding version changed"):
            operations.resume(SimpleNamespace(actor_id="fixture"), "operation-fixture")
        effect.assert_not_called()
        assert events.call_args.args[3]["state"] == "FAILED"
