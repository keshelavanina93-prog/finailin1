"""Bounded ready batches and atomic cumulative terminal usage."""
# ruff: noqa: F811

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from test_definition_history import DB, item, retained  # noqa: F401
from test_function_execution import function_case

from finai_api.domain.transformation import TransformationRunRequest
from finai_api.services import function_invocations
from finai_api.services import report_workflows as records
from finai_api.services import transformation_runs as runs
from finai_api.services.workspace import WorkspaceError
from finai_api.transformation_workflow import TransformationWorkflow


@pytest.mark.parametrize("mode", ["success", "failure", "cancel", "pause"])
def test_ready_batches_overlap_respect_barriers_and_drain(monkeypatch, mode):
    from finai_api import transformation_workflow as module

    instance = TransformationWorkflow()
    started, finished = [], set()
    active = maximum = 0
    topology = {
        "node_order": ["b", "a", "c", "join"],
        "execution_policy": {"max_concurrent_nodes": 2},
        "dependencies": {"a": [], "b": [], "c": [], "join": ["a", "b"]},
    }

    async def activity(context):
        nonlocal active, maximum
        node = context["node_id"]
        assert set(topology["dependencies"][node]) <= finished
        started.append(node)
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0)
        if node == "a":
            if mode == "cancel":
                instance.cancelled = True
            elif mode == "pause":
                instance.paused = True
        active -= 1
        finished.add(node)
        if node == "a" and mode == "failure":
            raise RuntimeError("Synthetic failed activity")
        return {"state": "COMPLETED"}

    async def boundary_wait(condition, **options):
        assert finished == {"a", "b"} and active == 0
        assert instance.state == "PAUSED"
        instance.paused = False
        assert condition()

    monkeypatch.setattr(
        module.workflow,
        "start_activity",
        lambda _name, context, **kw: asyncio.create_task(activity(context)),
    )
    monkeypatch.setattr(module.workflow, "wait_condition", boundary_wait)
    result = asyncio.run(instance._parallel_nodes({}, topology, {}))
    assert maximum == 2 and active == 0
    assert started[:2] == ["a", "b"]
    if mode in ("failure", "cancel"):
        assert not result and finished == {"a", "b"}
        assert instance.state == ("FAILED" if mode == "failure" else "CANCELLED")
    else:
        assert result and started == ["a", "b", "c", "join"]


@DB
def test_concurrent_terminal_budget_admits_one_and_reuses_refusal(retained, monkeypatch):
    reader, invocation, _, _, _ = function_case(retained)
    reader = reader.model_copy(update={"permissions": (*reader.permissions, "read", "ingest")})
    baseline = function_invocations.invoke(reader, invocation)
    size = runs.measured_usage(reader, baseline["output"]["run_id"])["published_result_bytes"]
    assert size > 1024
    _, publish = retained
    definition = item(
        "TransformationDefinition",
        {
            "execution_policy": {"max_concurrent_nodes": 2},
            "resource_budget": {
                "max_returned_rows": 2,
                "max_derived_evaluations": 0,
                "max_published_result_bytes": size + 1024,
            },
            "definition": {
                "nodes": [
                    {"node_id": n, "function_id": str(invocation.function.resource_id), "limit": 1}
                    for n in ("a", "b")
                ],
                "outputs": [{"output_id": n, "node_id": n} for n in ("a", "b")],
            },
        },
    )
    row = publish(definition)[0]
    request = TransformationRunRequest(
        transformation={"resource_id": row["resource_id"], "version_id": row["version_id"]},
        valid_at=invocation.valid_at,
        known_at=invocation.known_at,
    )
    identity = runs.retain(reader, request)
    context = {
        "workflow_id": identity,
        "actor_id": reader.actor_id,
        "scope": reader.scope.model_dump(mode="json"),
    }
    monkeypatch.setattr(records, "current_principal", lambda *_: reader)
    assert runs.load(context)["execution_policy"] == {"max_concurrent_nodes": 2}
    original_measure = runs.measured_usage
    barrier = Barrier(2)
    synchronize = True

    def measured(*args):
        value = original_measure(*args)
        if synchronize:
            barrier.wait(timeout=15)
        return value

    monkeypatch.setattr(runs, "measured_usage", measured)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda n: runs.execute_node({**context, "node_id": n}), ("a", "b")))
    synchronize = False
    assert sorted(r["state"] for r in results) == ["BUDGET_REFUSED", "COMPLETED"]
    refused = next(r for r in results if r["state"] == "BUDGET_REFUSED")
    assert refused["cumulative_usage"]["published_result_bytes"] > size + 1024
    for result in results:
        assert runs.execute_node({**context, "node_id": result["node"]}) == result
    history = runs.read(reader, identity)
    assert len([e for e in history["events"] if e["state"] in ("COMPLETED", "BUDGET_REFUSED")]) == 2
    with pytest.raises(WorkspaceError, match="incomplete"):
        runs.publish(context)
    assert history["publications"] == []
