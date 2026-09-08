"""Durable orchestration of bounded external meaning validation, without business effects."""

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn
class OntologyValidationWorkflow:
    def __init__(self) -> None:
        self.state = "PENDING"

    @workflow.query
    def status(self) -> dict[str, str]:
        return {"state": self.state}

    @workflow.run
    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        retry = RetryPolicy(
            initial_interval=timedelta(seconds=2),
            maximum_interval=timedelta(seconds=10),
            maximum_attempts=3,
        )
        try:
            for name, state in (
                ("ontology_validation_load", "VERIFYING_INPUTS"),
                ("ontology_validation_execute", "VALIDATING"),
                ("ontology_validation_publish", "PUBLISHING_REPORT"),
            ):
                self.state = state
                result = await workflow.execute_activity(
                    name,
                    context,
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=retry,
                )
            self.state = "COMPLETED"
            return dict(result)
        except BaseException:
            self.state = "INTERRUPTED"
            raise
