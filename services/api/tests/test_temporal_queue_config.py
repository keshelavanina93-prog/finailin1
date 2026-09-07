"""API dispatch and worker consumption share a server-owned queue setting."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from finai_api.config import Settings


def test_queue_default_and_environment_override(monkeypatch):
    monkeypatch.delenv("FINAI_TEMPORAL_TASK_QUEUE", raising=False)
    assert Settings().temporal_task_queue == "g8-report-source-v1"
    monkeypatch.setenv("FINAI_TEMPORAL_TASK_QUEUE", "g8-candidate-artifact-worker")
    assert Settings().temporal_task_queue == "g8-candidate-artifact-worker"
    for invalid in ("", "a b", "../queue", "a\n", "x" * 97):
        with pytest.raises(ValueError):
            Settings(temporal_task_queue=invalid)


def test_transformation_dispatch_uses_configured_queue(monkeypatch):
    from finai_api.api import transformation_routes as routes

    captured = {}

    class Client:
        async def start_workflow(self, *args, **kwargs):
            captured.update(kwargs)

    async def client():
        return Client()

    principal = SimpleNamespace(
        actor_id="synthetic", scope=SimpleNamespace(model_dump=lambda **_: {})
    )
    monkeypatch.setattr(routes, "require_permission", lambda *_: None)
    monkeypatch.setattr(routes.transformation_runs, "retain", lambda *_: "synthetic-run")
    monkeypatch.setattr(routes, "client", client)
    monkeypatch.setattr(
        routes, "get_settings", lambda: Settings(temporal_task_queue="g8-candidate-dispatch")
    )
    asyncio.run(routes.start(principal, SimpleNamespace(request_id=uuid4())))
    assert captured["task_queue"] == "g8-candidate-dispatch"


def test_worker_uses_same_server_queue(monkeypatch):
    from finai_api import workflow_worker as worker

    captured = {}

    class FakeWorker:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

        async def run(self):
            pass

    async def connect(*args, **kwargs):
        return object()

    monkeypatch.setattr(worker.Client, "connect", connect)
    monkeypatch.setattr(worker, "Worker", FakeWorker)
    monkeypatch.setattr(
        worker, "get_settings", lambda: Settings(temporal_task_queue="g8-candidate-dispatch")
    )
    asyncio.run(worker.main())
    assert captured["task_queue"] == "g8-candidate-dispatch"
