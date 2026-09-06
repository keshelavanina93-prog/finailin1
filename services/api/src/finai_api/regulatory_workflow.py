"""One bounded source check per durable Temporal Schedule action."""

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn
class RegulatorySourceCheck:
    @workflow.run
    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        return await workflow.execute_activity(
            "regulatory_source_check",
            {**context, "check_id": workflow.info().workflow_id},
            start_to_close_timeout=timedelta(minutes=3),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=5),
                maximum_interval=timedelta(minutes=1),
                maximum_attempts=3,
            ),
        )
