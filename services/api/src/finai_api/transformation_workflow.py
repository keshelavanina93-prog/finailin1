"""Deterministic completion barriers; Functions own computation and output identity."""

from contextlib import suppress
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError


@workflow.defn
class TransformationWorkflow:
    def __init__(self) -> None:
        self.state = "QUEUED"
        self.paused = False
        self.cancelled = False
        self.seen: set[str] = set()
        self.result: dict = {}
        self.review_notification = 0

    @workflow.signal
    def review_changed(self) -> None:
        self.review_notification += 1

    @workflow.signal
    def control(self, message: dict[str, str]) -> None:
        if message["id"] in self.seen:
            return
        self.seen.add(message["id"])
        if message["command"] == "pause":
            self.paused = True
        elif message["command"] == "resume":
            self.paused = False
        elif message["command"] == "cancel":
            self.cancelled = True

    @workflow.query
    def status(self) -> dict:
        return {
            "state": self.state,
            "result": self.result,
            "pause_requested": self.paused,
            "cancel_requested": self.cancelled,
        }

    async def _boundary(self) -> bool:
        if self.paused and not self.cancelled:
            self.state = "PAUSED"
            await workflow.wait_condition(lambda: not self.paused or self.cancelled)
        if self.cancelled:
            self.state = "CANCELLED"
            return False
        self.state = "RUNNING"
        return True

    @workflow.run
    async def run(self, context: dict) -> dict:
        options: dict[str, Any] = {
            "start_to_close_timeout": timedelta(minutes=3),
            "retry_policy": RetryPolicy(maximum_attempts=3),
        }
        try:
            topology = await workflow.execute_activity("transformation_load", context, **options)
            completed: set[str] = set()
            for node_id in topology["node_order"]:
                if not await self._boundary():
                    return self.result
                if not set(topology["dependencies"][node_id]).issubset(completed):
                    self.state = "FAILED"
                    return self.result
                outcome = await workflow.execute_activity(
                    "transformation_node", {**context, "node_id": node_id}, **options
                )
                self.result[node_id] = outcome
                if outcome["state"] != "COMPLETED":
                    self.state = "FAILED"
                    return self.result
                completed.add(node_id)
            if not await self._boundary():
                return self.result
            if workflow.patched("transformation-binding-review-v1") and topology.get(
                "binding_review"
            ):
                while True:
                    notification = self.review_notification
                    review = await workflow.execute_activity(
                        "transformation_binding_review", context, **options
                    )
                    self.result["binding_review"] = review
                    if review["state"] == "APPROVED":
                        break
                    if review["state"] in ("REJECTED", "CANCELLED"):
                        self.state = review["state"]
                        return self.result
                    self.state = "AWAITING_BINDING_REVIEW"

                    def binding_notified(notification: int = notification) -> bool:
                        return self.review_notification != notification or self.cancelled

                    with suppress(TimeoutError):
                        await workflow.wait_condition(
                            binding_notified,
                            timeout=timedelta(seconds=30),
                        )
                    if not await self._boundary():
                        return self.result
                if not await self._boundary():
                    return self.result
            if workflow.patched("transformation-publication-review-v1") and topology.get(
                "publication_review"
            ):
                while True:
                    notification = self.review_notification
                    review = await workflow.execute_activity(
                        "transformation_publication_review", context, **options
                    )
                    self.result["publication_review"] = review
                    if review["state"] == "APPROVED":
                        break
                    if review["state"] in ("REJECTED", "CANCELLED"):
                        self.state = review["state"]
                        return self.result
                    self.state = "AWAITING_REVIEW"

                    def notified(notification: int = notification) -> bool:
                        return self.review_notification != notification or self.cancelled

                    with suppress(TimeoutError):
                        await workflow.wait_condition(
                            notified,
                            timeout=timedelta(seconds=30),
                        )
                    if not await self._boundary():
                        return self.result
                if not await self._boundary():
                    return self.result
            self.result["publication"] = await workflow.execute_activity(
                "transformation_publish", context, **options
            )
            self.state = "COMPLETED"
        except ActivityError:
            self.state = "FAILED"
        return self.result
