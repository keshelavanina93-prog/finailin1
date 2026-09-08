"""Orchestration boundaries: failed or cancelled work cannot publish a report.

These tests exercise the workflow against injected activity outcomes. Native
activity persistence and real Temporal execution have separate integration proofs.
"""

import asyncio
from datetime import timedelta

import pytest

from finai_api import ontology_validation_workflow as module


@pytest.mark.parametrize("outcome", ["CONFORMS", "VIOLATES", "NOT_EVALUATED", "REFUSED"])
def test_validation_completion_means_published_evidence_not_conformance(monkeypatch, outcome):
    instance = module.OntologyValidationWorkflow()
    context = {"workflow_id": "retained-request", "actor_id": "maker", "scope": {}}
    publication = {"publication_id": "retained-publication", "outcome": outcome}
    observed = []

    async def activity(name, argument, *, start_to_close_timeout, retry_policy):
        # Every retry resolves the same retained request and fresh authority.
        assert argument is context
        assert start_to_close_timeout == timedelta(seconds=60)
        assert retry_policy.maximum_attempts == 3
        assert retry_policy.maximum_interval == timedelta(seconds=10)
        observed.append((name, instance.status()["state"]))
        if name == "ontology_validation_publish":
            return publication
        return {"outcome": outcome}

    monkeypatch.setattr(module.workflow, "execute_activity", activity)
    assert instance.status() == {"state": "PENDING"}
    assert asyncio.run(instance.run(context)) == publication
    assert instance.status() == {"state": "COMPLETED"}
    assert observed == [
        ("ontology_validation_load", "VERIFYING_INPUTS"),
        ("ontology_validation_execute", "VALIDATING"),
        ("ontology_validation_publish", "PUBLISHING_REPORT"),
    ]


@pytest.mark.parametrize("failed_stage", ["load", "execute", "publish"])
@pytest.mark.parametrize("cancelled", [False, True])
def test_interrupted_activity_never_advances_or_claims_publication(
    monkeypatch, failed_stage, cancelled
):
    instance = module.OntologyValidationWorkflow()
    seen = []
    failure = asyncio.CancelledError() if cancelled else RuntimeError("retry budget exhausted")

    async def activity(name, _context, **_options):
        stage = name.removeprefix("ontology_validation_")
        seen.append(stage)
        if stage == failed_stage:
            raise failure
        return {"retained": True}

    monkeypatch.setattr(module.workflow, "execute_activity", activity)
    with pytest.raises(type(failure)) as caught:
        asyncio.run(instance.run({"workflow_id": "same-retained-request"}))
    assert caught.value is failure
    assert instance.status() == {"state": "INTERRUPTED"}
    assert seen == ["load", "execute", "publish"][: ["load", "execute", "publish"].index(
        failed_stage
    ) + 1]
