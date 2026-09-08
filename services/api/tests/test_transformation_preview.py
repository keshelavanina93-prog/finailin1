from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from finai_api.domain.authority import canonical_sha256
from finai_api.domain.transformation import PreviewedTransformationStart, TransformationRunRequest
from finai_api.services import transformation_preview as preview
from finai_api.services import transformation_runs as runs
from finai_api.services.workspace import WorkspaceError


@pytest.fixture
def case(monkeypatch):
    request = TransformationRunRequest(
        transformation={"resource_id": uuid4(), "version_id": uuid4()},
        valid_at=datetime(2026, 1, 1, tzinfo=UTC),
        known_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    principal = SimpleNamespace(
        actor_id="builder",
        permissions=("ontology_read",),
        scope=SimpleNamespace(tenant_id=uuid4()),
    )
    compiled = {
        "request": request.model_dump(mode="json"),
        "exact_scope": {"company": "offline"},
        "nodes": [],
        "outputs": [],
        "resource_budget": {"max_returned_rows": 20},
        "publication_review": {"question": "Review inspected outputs"},
    }
    compiled["plan_hash"] = runs.function_execution._digest(compiled)
    state = {"old": None, "insert_count": 0, "plan_calls": 0, "race": None}

    def plan(*_):
        state["plan_calls"] += 1
        return deepcopy(compiled)

    class Database:
        def execute(self, sql, parameters):
            if sql.startswith("INSERT"):
                state["insert_count"] += 1
                state["old"] = state["race"] or (parameters[3], parameters[5].obj)
            return self

        def fetchone(self):
            return state["old"]

    @contextmanager
    def connection(_):
        yield Database()

    monkeypatch.setattr(runs, "resource_connection", connection)
    monkeypatch.setattr(runs.records, "set_scope", lambda *_: {"company": "offline"})
    monkeypatch.setattr(runs.transformation_definitions, "plan", plan)
    return principal, request, compiled, state


def test_preview_exposes_actual_compiler_metadata_without_retaining(case):
    principal, request, compiled, state = case
    result = preview.preview(principal, request)
    assert result["contract"] == "transformation-preview/1"
    assert result["compiled_plan"] == compiled
    assert result["plan_hash"] == compiled["plan_hash"]
    assert result["request"] == request.model_dump(mode="json")
    assert result["coverage"] == "PLAN_METADATA_ONLY"
    assert result["transformed_rows_available"] is False
    assert result["current_use_authorized"] is result["business_effect_authorized"] is False
    assert state["old"] is None and state["insert_count"] == 0


def test_previewed_start_and_replay_keep_original_request_and_plan(case):
    principal, request, compiled, state = case
    expected = compiled["plan_hash"]
    identity = runs.retain(principal, request, expected_plan_hash=expected)
    assert state["old"][1]["request_hash"] == canonical_sha256(request)
    compiled["resource_budget"] = {"max_returned_rows": 30}
    assert runs.retain(principal, request, expected_plan_hash=expected) == identity
    assert state["plan_calls"] == 1 and state["insert_count"] == 1


def test_new_mismatch_retains_nothing(case):
    principal, request, _, state = case
    with pytest.raises(WorkspaceError, match="inspected preview"):
        runs.retain(principal, request, expected_plan_hash="f" * 64)
    assert state["old"] is None and state["insert_count"] == 0


def test_replay_cannot_ignore_mismatched_preview(case):
    principal, request, _, state = case
    runs.retain(principal, request)
    with pytest.raises(WorkspaceError, match="inspected preview"):
        runs.retain(principal, request, expected_plan_hash="f" * 64)
    assert state["plan_calls"] == 1 and state["insert_count"] == 1


def test_retained_plan_tampering_refused_even_when_stored_hash_matches(case):
    principal, request, compiled, state = case
    runs.retain(principal, request)
    state["old"][1]["compiled_plan"]["outputs"] = [{"output_id": "changed"}]
    with pytest.raises(WorkspaceError, match="inspected preview"):
        runs.retain(principal, request, expected_plan_hash=compiled["plan_hash"])


def test_race_winner_plan_must_match_inspected_hash(case):
    principal, request, compiled, state = case
    other = deepcopy(compiled)
    other["outputs"] = [{"output_id": "other", "node_id": "other"}]
    other["plan_hash"] = runs.function_execution._digest(
        {key: value for key, value in other.items() if key != "plan_hash"}
    )
    state["race"] = (
        principal.actor_id,
        {
            "request_hash": canonical_sha256(request),
            "compiled_plan": other,
        },
    )
    with pytest.raises(WorkspaceError, match="inspected preview"):
        runs.retain(principal, request, expected_plan_hash=compiled["plan_hash"])


def test_ordinary_replay_unchanged_and_actor_conflict_preserved(case):
    principal, request, _, state = case
    identity = runs.retain(principal, request)
    assert runs.retain(principal, request) == identity
    state["old"] = ("another-actor", state["old"][1])
    with pytest.raises(WorkspaceError, match="already used differently"):
        runs.retain(principal, request)


def test_preview_envelope_does_not_change_legacy_request(case):
    _, request, compiled, _ = case
    before = canonical_sha256(request)
    envelope = PreviewedTransformationStart(
        request=request, expected_plan_hash=compiled["plan_hash"]
    )
    assert canonical_sha256(envelope.request) == before
    assert "expected_plan_hash" not in envelope.request.model_dump(mode="json")
    with pytest.raises(ValidationError):
        PreviewedTransformationStart(request=request, expected_plan_hash="invalid")
