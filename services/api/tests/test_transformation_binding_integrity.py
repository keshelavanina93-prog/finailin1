"""Synthetic app-role SQL proofs for durable canonical binding review gates."""

# ruff: noqa: F811

from uuid import uuid4

import pytest
from psycopg.errors import RaiseException
from test_definition_history import DB, retained  # noqa: F401
from test_transformation_bindings import transformation_binding_case

from finai_api.services import transformation_bindings
from finai_api.services import transformation_runs as runs


@DB
def test_sql_rejects_forged_preparation_and_publication_before_binding_review(
    retained, monkeypatch
):
    author, _reviewer, _dimension, context = transformation_binding_case(retained, monkeypatch)
    runs.execute_node({**context, "node_id": "source"})
    original_event = transformation_bindings.record_event
    captured = []

    def capture(principal, identity, event_id, payload):
        if event_id == transformation_bindings.EVENT:
            captured.append((principal, identity, event_id, payload))
            return
        return original_event(principal, identity, event_id, payload)

    # Retain the real operation/proposal but delay only the linking event, so the
    # SQL trigger sees forged links before any immutable event occupies its ID.
    with monkeypatch.context() as patch:
        patch.setattr(transformation_bindings, "record_event", capture)
        transformation_bindings.prepare(context)
    assert len(captured) == 1
    principal, identity, event_id, payload = captured[0]
    for forged in (
        {**payload, "proposal_id": str(uuid4())},
        {**payload, "input_result": {**payload["input_result"], "receipt_hash": "0" * 64}},
    ):
        with pytest.raises(
            RaiseException,
            match="Binding review must retain the exact completed source and canonical proposal",
        ):
            original_event(principal, identity, event_id, forged)
    assert not any(event["event_id"] == event_id for event in runs.read(author, identity)["events"])
    pending = transformation_bindings.prepare(context)
    assert pending["state"] == "PENDING"
    assert pending["proposal_id"] == payload["proposal_id"]
    assert pending["input_result"] == payload["input_result"]

    # Bypass only the Python gate projection; the database reads the real pending
    # canonical decision and must refuse an otherwise valid publication event.
    original_context = runs._context

    def approved_projection(value):
        principal, retained_run = original_context(value)
        return principal, {
            **retained_run,
            "binding_review": {**retained_run["binding_review"], "state": "APPROVED"},
        }

    with monkeypatch.context() as patch:
        patch.setattr(runs, "_context", approved_projection)
        with pytest.raises(
            RaiseException,
            match="Transformation publication requires its canonical binding approval",
        ):
            runs.publish(context)
    current = runs.read(author, identity)
    assert current["publications"] == []
    assert current["binding_review"]["state"] == "PENDING"
