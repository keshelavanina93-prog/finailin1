"""Deterministic orchestration; business data and policy stay in G8 activities."""

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError


@workflow.defn
class ReportSourceWorkflow:
    def __init__(self) -> None:
        self.state = "QUEUED"
        self.commands: list[str] = []
        self.seen: set[str] = set()
        self.result: dict[str, Any] = {}

    @workflow.signal
    def control(self, message: dict[str, str]) -> None:
        if message["id"] not in self.seen:
            self.seen.add(message["id"])
            self.commands.append(message["command"])

    @workflow.query
    def status(self) -> dict[str, Any]:
        return {"state": self.state, "result": self.result}

    @workflow.run
    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        generation = 0
        while True:
            self.state = "RUNNING"
            try:
                if context.get("definition_version") == "report-source-process/2":
                    self.result["hierarchy"] = await workflow.execute_activity(
                        "report_source_hierarchy",
                        {**context, "generation": generation},
                        start_to_close_timeout=timedelta(minutes=3),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )
                coverage = await workflow.execute_activity(
                    "report_source_coverage",
                    {**context, "generation": generation},
                    start_to_close_timeout=timedelta(minutes=3),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=2),
                        maximum_interval=timedelta(seconds=30),
                        maximum_attempts=3,
                    ),
                )
                self.result.update(coverage)
                self.state = "WAITING_REVIEW"
            except ActivityError:
                self.state = "FAILED"
            checkpoint = self.state
            while True:
                await workflow.wait_condition(lambda: bool(self.commands))
                command = self.commands.pop(0)
                if command == "cancel":
                    self.state = "CANCELLED"
                    return self.result
                if command == "pause":
                    self.state = "PAUSED"
                elif command == "resume" and self.state == "PAUSED":
                    self.state = checkpoint
                elif command == "complete" and self.state == "WAITING_REVIEW":
                    self.state = "REVIEWED"
                    return self.result
                elif command == "retry" and self.state != "PAUSED":
                    break
            generation += 1
