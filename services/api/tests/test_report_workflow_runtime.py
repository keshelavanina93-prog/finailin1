"""Opt-in local Temporal invariant; no source data, economic effects or test finance claims."""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker

from finai_api.report_workflow import ReportSourceWorkflow


def test_exhausted_activity_failure_can_resume_without_losing_workflow():
    address = os.environ.get("FINAI_TEMPORAL_TEST_SERVER")
    if not address:
        pytest.skip("Set FINAI_TEMPORAL_TEST_SERVER for isolated local runtime verification")
    attempts = []

    @activity.defn(name="report_source_coverage")
    def fail_then_recover(context: dict) -> dict:
        attempts.append((context["generation"], activity.info().attempt))
        if context["generation"] == 0:
            raise RuntimeError("Injected pre-effect failure")
        return {"assessment_id": "verification-only", "state": "UNAVAILABLE"}

    async def verify():
        client = await Client.connect(address)
        queue = "g8-workflow-invariant-" + uuid4().hex
        with ThreadPoolExecutor(max_workers=1) as executor:
            async with Worker(
                client,
                task_queue=queue,
                workflows=[ReportSourceWorkflow],
                activities=[fail_then_recover],
                activity_executor=executor,
            ):
                handle = await client.start_workflow(
                    ReportSourceWorkflow.run, {}, id=queue, task_queue=queue
                )

                async def state(expected):
                    for _ in range(100):
                        if (await handle.query(ReportSourceWorkflow.status))["state"] == expected:
                            return
                        await asyncio.sleep(0.2)
                    raise AssertionError(await handle.query(ReportSourceWorkflow.status))

                await state("FAILED")
                assert attempts == [(0, 1), (0, 2), (0, 3)]
                await handle.signal(
                    ReportSourceWorkflow.control, {"id": "retry-1", "command": "retry"}
                )
                await handle.signal(
                    ReportSourceWorkflow.control, {"id": "retry-1", "command": "retry"}
                )
                await state("WAITING_REVIEW")
                assert attempts == [(0, 1), (0, 2), (0, 3), (1, 1)]
                await handle.signal(
                    ReportSourceWorkflow.control, {"id": "cancel", "command": "cancel"}
                )
                assert (await handle.result())["state"] == "UNAVAILABLE"
                assert (await handle.query(ReportSourceWorkflow.status))["state"] == "CANCELLED"

    asyncio.run(verify())
