"""Eligibility presentation cannot turn a retained selection into execution authority."""

from contextlib import nullcontext

import pytest
from test_accounting_consumption import fixture_graph

from finai_api.services import accounting_binding_status as status
from finai_api.services.workspace import WorkspaceError


def binding_fixture():
    rows, edges, _, _, _, key = fixture_graph()
    binding = {
        **rows[key],
        "resource_id": str(key[0]),
        "version_id": str(key[1]),
        "valid_from": "2025-01-01T00:00:00Z",
        "valid_to": None,
        "system_from": "2025-02-01T00:00:00Z",
    }
    return binding, rows, edges


def test_unselected_and_review_candidate_are_never_execution_grants():
    assert status.inspect(None, None)["state"] == "UNSELECTED"
    binding, _, _ = binding_fixture()
    binding["attributes"]["source_use"] = "REVIEW_CANDIDATE"
    result = status.inspect(None, binding)
    assert result["state"] == "NOT_ACCOUNTING_INPUT"
    assert not result["current_use_authorized"] and not result["eligible_for_accounting"]


def test_legacy_selection_remains_explainable_without_current_eligibility():
    binding, _, _ = binding_fixture()
    binding["attributes"].pop("contract_version")
    result = status.inspect(None, binding)
    assert result["state"] == "INTERPRETATION_REQUIRED"
    assert result["binding_version_id"] == binding["version_id"]
    assert result["effective_from"] == binding["valid_from"]
    assert result["known_from"] == binding["system_from"]
    assert not result["current_use_authorized"]


@pytest.mark.parametrize("blocked", [True, False])
def test_shared_current_guard_outcome_is_advisory_not_authority(monkeypatch, blocked):
    from finai_api.services import accounting_consumption, accounting_promotion, resources

    binding, rows, edges = binding_fixture()
    monkeypatch.setattr(resources, "resource_connection", lambda *a, **k: nullcontext(None))
    monkeypatch.setattr(accounting_consumption, "load_accounting_lineage", lambda *a: (rows, edges))

    def current_guard(*_):
        if blocked:
            raise WorkspaceError(409, "Upstream authority withdrawn")

    monkeypatch.setattr(accounting_promotion, "validate_current_binding", current_guard)
    result = status.inspect(None, binding)
    assert result["eligible_for_accounting"] is not blocked
    assert result["current_use_authorized"] is False
    assert result["advisory"] is True
    if blocked:
        assert result["state"] == "CURRENT_USE_BLOCKED"
        assert result["reason"] == "Upstream authority withdrawn"
