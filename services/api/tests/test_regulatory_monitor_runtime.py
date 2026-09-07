"""Monitor health follows the concrete Temporal execution type."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from temporalio.client import ScheduleActionExecutionStartWorkflow

from finai_api.api import regulation_routes


@pytest.mark.parametrize("workflow_action", [True, False])
def test_monitor_handles_workflow_and_unknown_schedule_actions(monkeypatch, workflow_action):
    action = (
        ScheduleActionExecutionStartWorkflow("retained-check", "first-run")
        if workflow_action
        else object()
    )
    description = SimpleNamespace(
        schedule=SimpleNamespace(state=SimpleNamespace(paused=False)),
        info=SimpleNamespace(
            next_action_times=[],
            running_actions=[],
            num_actions=1,
            recent_actions=[SimpleNamespace(action=action)],
        ),
    )
    workflow = SimpleNamespace(
        describe=AsyncMock(return_value=SimpleNamespace(status=SimpleNamespace(name="FAILED")))
    )
    runtime = SimpleNamespace(
        get_schedule_handle=Mock(
            return_value=SimpleNamespace(describe=AsyncMock(return_value=description))
        ),
        get_workflow_handle=Mock(return_value=workflow),
    )
    monkeypatch.setattr(regulation_routes, "client", AsyncMock(return_value=runtime))
    monkeypatch.setattr(
        regulation_routes.regulatory_monitors,
        "read",
        lambda *_: {
            "events": [],
            "created_at": datetime.now(UTC).isoformat(),
            "request": {"cadence_hours": 24},
        },
    )
    result = asyncio.run(regulation_routes.read_monitor("monitor", None))
    assert result["runtime"]["state"] == "ENABLED"
    if workflow_action:
        runtime.get_workflow_handle.assert_called_once_with("retained-check")
        assert result["runtime"]["latest_execution"] == "FAILED"
        assert result["source_health"] == "CHECK_FAILED"
    else:
        runtime.get_workflow_handle.assert_not_called()
        assert result["runtime"]["latest_execution"] == "UNKNOWN_ACTION"
        assert result["source_health"] == "NOT_CHECKED"
