"""Protect source capture's retry boundary without creating canonical demo resources."""

from types import SimpleNamespace

import pytest

from finai_api.services import regulatory_monitors as monitors


def test_completed_check_retry_reuses_retained_checkpoint(monkeypatch):
    monkeypatch.setattr(monitors.records, "current_principal", lambda *a: object())
    monkeypatch.setattr(monitors, "require_permission", lambda *a: None)
    monkeypatch.setattr(
        monitors,
        "read",
        lambda *a: {"events": [{"event_id": "source-check:run-1", "state": "UNCHANGED"}]},
    )
    monkeypatch.setattr(monitors.sources, "capture", lambda *a: pytest.fail("Re-fetched source"))
    assert monitors.check(
        {"actor_id": "actor", "scope": {}, "workflow_id": "job", "check_id": "run-1"}
    ) == {"event_id": "source-check:run-1", "state": "UNCHANGED"}


def test_failed_check_retains_failure_without_completed_checkpoint(monkeypatch):
    events = []
    monkeypatch.setattr(monitors.records, "current_principal", lambda *a: object())
    monkeypatch.setattr(monitors, "require_permission", lambda *a: None)
    monkeypatch.setattr(
        monitors,
        "read",
        lambda *a: {"events": [], "request": {"document_number": "6049454", "publication": 0}},
    )
    monkeypatch.setattr(monitors.activity, "info", lambda: SimpleNamespace(attempt=2))
    monkeypatch.setattr(monitors.records, "event", lambda *a: events.append(a[-1]))

    def fail(*args):
        raise ValueError("Publisher unavailable")

    monkeypatch.setattr(monitors.sources, "capture", fail)
    with pytest.raises(ValueError, match="Publisher unavailable"):
        monitors.check(
            {"actor_id": "actor", "scope": {}, "workflow_id": "job", "check_id": "run-1"}
        )
    assert [event["state"] for event in events] == ["CHECKING", "CHECK_FAILED"]
    assert all("document" not in event for event in events)
