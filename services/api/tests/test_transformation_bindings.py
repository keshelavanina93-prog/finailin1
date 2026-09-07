"""Existing canonical proposal decisions gate transformation evidence publication."""
# ruff: noqa: F811

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from test_calculated_bindings import calculated_binding_case
from test_definition_history import DB, item, retained  # noqa: F401

from finai_api.domain.resources import ResourceReview
from finai_api.domain.transformation import TransformationRunRequest
from finai_api.services import report_workflows as records
from finai_api.services import resources, transformation_bindings
from finai_api.services import transformation_runs as runs
from finai_api.services.workspace import WorkspaceError
from finai_api.transformation_workflow import TransformationWorkflow


@pytest.mark.parametrize("cancel", [False, True])
def test_workflow_waits_on_retained_decision_without_reexecuting_nodes(monkeypatch, cancel):
    from finai_api import transformation_workflow as module

    instance = TransformationWorkflow()
    calls = []
    decisions = iter(["PENDING", "APPROVED"])

    async def execute(name, context, **options):
        calls.append(name)
        if name == "transformation_load":
            return {
                "node_order": ["source"],
                "dependencies": {"source": []},
                "binding_review": True,
                "publication_review": True,
            }
        if name == "transformation_node":
            return {"state": "COMPLETED"}
        if name == "transformation_binding_review":
            return {"state": next(decisions), "proposal_id": "retained-proposal"}
        if name == "transformation_publication_review":
            return {"state": "APPROVED"}
        return {"publication_id": "retained-publication"}

    async def wait(condition, **options):
        assert instance.state == "AWAITING_BINDING_REVIEW"
        assert options["timeout"].total_seconds() == 30
        if cancel:
            instance.control({"id": "cancel", "command": "cancel"})
        else:
            instance.review_changed()
        assert condition()

    monkeypatch.setattr(module.workflow, "execute_activity", execute)
    monkeypatch.setattr(module.workflow, "wait_condition", wait)
    monkeypatch.setattr(module.workflow, "patched", lambda _: True)
    asyncio.run(instance.run({}))
    assert calls.count("transformation_node") == 1
    if cancel:
        assert instance.state == "CANCELLED"
        assert "transformation_publish" not in calls
    else:
        assert instance.state == "COMPLETED"
        assert calls[-3:] == [
            "transformation_binding_review",
            "transformation_publication_review",
            "transformation_publish",
        ]


def transformation_binding_case(retained, monkeypatch):
    author, reviewer, dimension, binding, source, _action = calculated_binding_case(retained)
    _, publish = retained
    transform = item(
        "TransformationDefinition",
        {
            "resource_budget": {
                "max_returned_rows": 10,
                "max_derived_evaluations": 10,
                "max_published_result_bytes": 16000000,
            },
            "binding_review": {
                "binding_id": str(binding.resource_id),
                "source_node_id": "source",
                "rationale": "Synthetic retained binding review from existing canonical source",
            },
            "definition": {
                "nodes": [
                    {
                        "node_id": "source",
                        "function_id": source["receipt"]["request"]["function"]["resource_id"],
                        "limit": 10,
                    }
                ],
                "outputs": [{"output_id": "evidence", "node_id": "source"}],
            },
        },
    )
    row = publish(transform)[0]
    now = datetime.now(UTC)
    request = TransformationRunRequest(
        transformation={"resource_id": transform.resource_id, "version_id": row["version_id"]},
        valid_at=now,
        known_at=now,
    )
    identity = runs.retain(author, request)
    context = {
        "workflow_id": identity,
        "actor_id": author.actor_id,
        "scope": author.scope.model_dump(mode="json"),
    }
    monkeypatch.setattr(records, "current_principal", lambda *_: author)
    return author, reviewer, dimension, context


@DB
def test_native_binding_review_reuses_proposal_and_publishes_only_after_canonical_approval(
    retained, monkeypatch
):
    author, reviewer, dimension, context = transformation_binding_case(retained, monkeypatch)
    identity = context["workflow_id"]
    assert runs.load(context)["binding_review"] is True
    with pytest.raises(WorkspaceError, match="every Function"):
        transformation_bindings.prepare(context)
    terminal = runs.execute_node({**context, "node_id": "source"})
    with pytest.raises(WorkspaceError, match="binding proposal approval"):
        runs.publish(context)
    retained_ack = {}
    original_record = transformation_bindings.record_event

    def lost_ack(principal, workflow_id, event_id, payload):
        assert event_id == transformation_bindings.EVENT
        retained_ack.update(payload)
        raise RuntimeError("Synthetic loss after canonical proposal retention")

    monkeypatch.setattr(transformation_bindings, "record_event", lost_ack)
    with pytest.raises(RuntimeError, match="after canonical proposal"):
        transformation_bindings.prepare(context)
    assert resources.proposal_detail(author, UUID(retained_ack["proposal_id"])).decision is None
    monkeypatch.setattr(transformation_bindings, "record_event", original_record)
    pending = transformation_bindings.prepare(context)
    assert pending["operation_id"] == retained_ack["operation_id"]
    assert pending["proposal_id"] == retained_ack["proposal_id"]
    assert runs.execute_node({**context, "node_id": "source"}) == terminal
    with records.scope_connection(author) as conn:
        records.set_scope(conn, author)
        count = conn.execute(
            "SELECT count(*) FROM workflow_requests WHERE tenant_id=%s "
            "AND definition_version='ontology-action/1' "
            "AND payload->'invocation'->>'request_id'=%s",
            (author.scope.tenant_id, pending["operation_request_id"]),
        ).fetchone()[0]
    assert count == 1
    assert pending["state"] == "PENDING" and pending["decision"] is None
    assert pending["input_result"] == terminal["output"]
    assert pending["proposal_history_independent"] is True
    assert transformation_bindings.prepare(context) == pending
    assert runs.read(reviewer, identity)["binding_review"]["proposal_id"] == pending["proposal_id"]
    with pytest.raises(WorkspaceError, match="binding proposal approval"):
        runs.publication_review(context)
    with pytest.raises(WorkspaceError, match="binding proposal approval"):
        runs.publish(context)
    resources.review(
        reviewer,
        UUID(pending["proposal_id"]),
        ResourceReview(
            decision="APPROVED",
            rationale="Independent synthetic calculated canonical update verification",
        ),
    )
    approved = transformation_bindings.prepare(context)
    assert approved["state"] == approved["decision"] == "APPROVED"
    assert approved["proposal_id"] == pending["proposal_id"]
    assert approved["reviewed_by"] == reviewer.actor_id
    assert runs.execute_node({**context, "node_id": "source"}) == terminal
    publication = runs.publish(context)
    assert runs.publish(context) == publication
    history = runs.read(author, identity)
    assert (
        len(
            [
                event
                for event in history["events"]
                if event["event_id"] == transformation_bindings.EVENT
            ]
        )
        == 1
    )
    assert len(history["publications"]) == 1
    assert (
        resources.get_resource(author, dimension.resource_id)["resource"]["display_name"]
        == "SYNTHETIC retained fixture"
    )


def test_source_receipt_requires_exact_terminal_and_complete_nodes(monkeypatch):
    invocation = str(uuid4())
    retained = {
        "request": {
            "compiled_plan": {
                "binding_review": {"source_node_id": "source"},
                "nodes": [{"node_id": "source", "invocation": {"request_id": invocation}}],
            }
        },
        "events": [],
    }
    with pytest.raises(WorkspaceError, match="every Function"):
        transformation_bindings.source_receipt(None, retained)
    retained["events"] = [
        {
            "state": "COMPLETED",
            "node": "source",
            "output": {
                "invocation_id": invocation,
                "receipt_hash": "forged",
                "run_id": "fcr_original",
            },
        }
    ]
    monkeypatch.setattr(
        transformation_bindings.function_invocations,
        "history",
        lambda *_: {
            "status": "SUCCEEDED",
            "invocation_id": invocation,
            "receipt_hash": "original",
            "receipt": {"run_id": "fcr_original"},
        },
    )
    with pytest.raises(WorkspaceError, match="differs"):
        transformation_bindings.source_receipt(None, retained)
