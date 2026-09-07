# ruff: noqa: F811
"""Independent review gates retained evidence publication, never computation authority."""

from uuid import uuid4, uuid5

import psycopg
import pytest
from test_definition_history import DB, item, retained  # noqa: F401
from test_function_execution import function_case

from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.domain.transformation import TransformationRunRequest
from finai_api.services import report_workflows as records
from finai_api.services import transformation_runs as runs
from finai_api.services.workspace import WorkspaceError


@DB
@pytest.mark.parametrize("decision", ["APPROVED", "REJECTED", "CANCELLED"])
def test_native_review_gate_independence_replay_and_publication(retained, monkeypatch, decision):
    reader, invocation, _, _, _ = function_case(retained)
    maker = reader.model_copy(
        update={"permissions": (*reader.permissions, "read", "ingest", "review")}
    )
    checker = maker.model_copy(update={"actor_id": "synthetic-publication-checker"})
    definition = item(
        "TransformationDefinition",
        {
            "resource_budget": {
                "max_returned_rows": 10,
                "max_derived_evaluations": 0,
                "max_published_result_bytes": 1000000,
            },
            "publication_review": {
                "question": "Confirm these synthetic retained observations for publication"
            },
            "definition": {
                "nodes": [
                    {
                        "node_id": "source",
                        "function_id": str(invocation.function.resource_id),
                        "limit": 10,
                    }
                ],
                "outputs": [{"output_id": "observations", "node_id": "source"}],
            },
        },
    )
    row = retained[1](definition)[0]
    request = TransformationRunRequest(
        transformation=VersionReference(
            resource_id=row["resource_id"], version_id=row["version_id"]
        ),
        valid_at=invocation.valid_at,
        known_at=invocation.known_at,
    )
    identity = runs.retain(maker, request)
    context = {
        "workflow_id": identity,
        "actor_id": maker.actor_id,
        "scope": maker.scope.model_dump(mode="json"),
    }
    monkeypatch.setattr(
        records,
        "current_principal",
        lambda actor, _: checker if actor == checker.actor_id else maker,
    )
    with pytest.raises(WorkspaceError, match="every completed"):
        runs.publication_review(context)
    outcome = runs.execute_node({**context, "node_id": "source"})
    review = runs.publication_review(context)
    assert review["state"] == "PENDING"
    assert review["task_id"] == str(uuid5(request.request_id, "publication"))
    assert review["outputs"][0] == {
        "output_id": "observations",
        "node_id": "source",
        **outcome["output"],
    }
    assert runs.publication_review(context) == review
    with pytest.raises(WorkspaceError, match="independent approval"):
        runs.publish(context)
    key = uuid4()
    with pytest.raises(WorkspaceError) as maker_refused:
        runs.decide_review(maker, identity, key, "APPROVED", "SYNTHETIC independent decision")
    assert maker_refused.value.status == 403
    stranger = checker.model_copy(
        update={
            "scope": checker.scope.model_copy(
                update={"legal_entity_id": "synthetic-other-" + uuid4().hex}
            )
        }
    )
    with pytest.raises(WorkspaceError) as hidden:
        runs.decide_review(stranger, identity, key, "APPROVED", "SYNTHETIC independent decision")
    assert hidden.value.status == 404
    with pytest.raises(psycopg.errors.RaiseException):
        records.event(
            maker,
            identity,
            "publication-review:decision",
            {
                "task_id": review["task_id"],
                "state": "APPROVED",
                "decision_id": str(key),
                "actor_id": checker.actor_id,
                "reason": "SYNTHETIC forged session actor",
            },
        )
    if decision == "CANCELLED":
        records.event(
            maker,
            identity,
            "control:" + str(key),
            {
                "command": "cancel",
                "actor_id": maker.actor_id,
                "reason": "SYNTHETIC cancel pending review",
            },
        )
        with pytest.raises(WorkspaceError, match="not pending"):
            runs.decide_review(checker, identity, key, "APPROVED", "SYNTHETIC independent decision")
    else:
        decided = runs.decide_review(
            checker, identity, key, decision, "SYNTHETIC independent decision"
        )
        assert decided["state"] == decision
        assert (
            runs.decide_review(checker, identity, key, decision, "SYNTHETIC independent decision")
            == decided
        )
    if decision == "APPROVED":
        assert runs.publish(context)["publication_id"].startswith("pub_")
        assert (
            runs.decide_review(checker, identity, key, decision, "SYNTHETIC independent decision")
            == decided
        )
    else:
        with pytest.raises(WorkspaceError, match="independent approval"):
            runs.publish(context)
        assert runs.read(maker, identity)["publications"] == []
