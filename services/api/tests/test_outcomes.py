from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from finai_api.services import outcomes
from finai_api.services.workspace import WorkspaceError


def _principal():
    return type(
        "P",
        (),
        {
            "scope": type(
                "S", (), {"legal_entity_id": UUID("00000000-0000-0000-0000-000000000001")}
            )(),
            "permissions": ["ontology_read"],
        },
    )()


def _db_principal(*permissions):
    legal_entity_id = UUID("00000000-0000-0000-0000-000000000001")
    scope = SimpleNamespace(
        tenant_id=UUID("00000000-0000-0000-0000-000000000002"),
        legal_entity_id=legal_entity_id,
        model_dump=lambda mode="json": {
            "tenant_id": str(UUID("00000000-0000-0000-0000-000000000002")),
            "legal_entity_id": str(legal_entity_id),
            "period": "2026-08",
            "currency": "GEL",
        },
    )
    return SimpleNamespace(scope=scope, actor_id="actor-a", permissions=list(permissions))


class _Db:
    def __init__(self, one=None, many=()):
        self.one = one
        self.many = list(many)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, _params=None):
        self.sql = sql
        return self

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.many


def test_actual_vs_plan_requires_actual_kind(monkeypatch):
    principal = _principal()
    plan = UUID("10000000-0000-0000-0000-000000000001")
    actual = UUID("20000000-0000-0000-0000-000000000001")
    rows = [
        {
            "resource_id": plan,
            "attributes": {"legal_entity_id": str(principal.scope.legal_entity_id), "kind": "PLAN"},
        },
        {
            "resource_id": actual,
            "attributes": {
                "legal_entity_id": str(principal.scope.legal_entity_id),
                "kind": "FORECAST",
            },
        },
    ]
    monkeypatch.setattr(
        outcomes.planning, "_resources", lambda _p, kind: rows if kind == "ScenarioVersion" else []
    )
    with pytest.raises(WorkspaceError, match="ACTUAL"):
        outcomes.actual_vs_plan(principal, plan, actual)


def test_actual_vs_plan_returns_decimal_variance(monkeypatch):
    principal = _principal()
    plan = UUID("10000000-0000-0000-0000-000000000001")
    actual = UUID("20000000-0000-0000-0000-000000000001")
    base = {
        "legal_entity_id": str(principal.scope.legal_entity_id),
        "period_id": "2025-01",
        "measure": "amount",
    }
    scenarios = [
        {"resource_id": plan, "attributes": {**base, "kind": "PLAN"}},
        {"resource_id": actual, "attributes": {**base, "kind": "ACTUAL"}},
    ]
    cells = [
        {
            "resource_id": "p",
            "attributes": {**base, "scenario_version_id": str(plan), "amount": "10.10"},
        },
        {
            "resource_id": "a",
            "attributes": {**base, "scenario_version_id": str(actual), "amount": "12.35"},
        },
    ]
    monkeypatch.setattr(
        outcomes.planning,
        "_resources",
        lambda _p, kind: scenarios if kind == "ScenarioVersion" else cells,
    )
    result = outcomes.actual_vs_plan(principal, plan, actual)
    assert result["contract"] == "outcome-measurement/1"
    assert result["rows"][0]["variance"] == "2.25"
    assert result["measurement_id"].startswith("om_")
    assert result["scope"]["legal_entity_id"] == str(principal.scope.legal_entity_id)
    assert isinstance(result["observed_at"], str) and result["observed_at"].endswith("+00:00")
    assert result["learning_candidate_created"] is False


def test_learning_evaluation_is_deterministic_shadow_only(monkeypatch):
    principal = _principal()
    plan = UUID("10000000-0000-0000-0000-000000000001")
    actual = UUID("20000000-0000-0000-0000-000000000001")
    base = {
        "legal_entity_id": str(principal.scope.legal_entity_id),
        "period_id": "2025-01",
        "measure": "amount",
    }
    scenarios = [
        {"resource_id": plan, "attributes": {**base, "kind": "PLAN"}},
        {"resource_id": actual, "attributes": {**base, "kind": "ACTUAL"}},
    ]
    cells = [
        {
            "resource_id": "p",
            "attributes": {**base, "scenario_version_id": str(plan), "amount": "10.10"},
        },
        {
            "resource_id": "a",
            "attributes": {**base, "scenario_version_id": str(actual), "amount": "12.35"},
        },
    ]
    monkeypatch.setattr(
        outcomes.planning,
        "_resources",
        lambda _p, kind: scenarios if kind == "ScenarioVersion" else cells,
    )
    result = outcomes.evaluate_learning(principal, plan, actual, "2.25")
    repeat = outcomes.evaluate_learning(principal, plan, actual, "2.25")
    assert result["contract"] == "learning-evaluation/1"
    assert result["candidate_id"] == repeat["candidate_id"]
    assert result["status"] == "SHADOW_PASS"
    assert result["measurement"]["rows"][0]["within_tolerance"] is True
    assert result["promotion_required"] is True
    assert result["production_policy_changed"] is False
    assert result["production_model_changed"] is False


def test_outcome_measurement_rejects_missing_scope_and_invalid_identity():
    principal = _db_principal("ontology_propose")
    with pytest.raises(WorkspaceError, match="authorized company scope"):
        outcomes.retain_measurement(principal, {"contract": "wrong", "scope": {}})
    with pytest.raises(WorkspaceError, match="identity is invalid"):
        outcomes.retain_measurement(
            principal,
            {
                "contract": "outcome-measurement/1",
                "scope": {"legal_entity_id": str(principal.scope.legal_entity_id)},
                "measurement_id": "om_bad",
            },
        )


def test_outcome_measurement_and_timeline_preserve_hash(monkeypatch):
    principal = _db_principal("ontology_propose", "ontology_read")
    measurement = {
        "contract": "outcome-measurement/1",
        "measurement_id": "om_" + "a" * 64,
        "scope": {"legal_entity_id": str(principal.scope.legal_entity_id)},
        "rows": [],
    }
    import hashlib
    import json

    digest = hashlib.sha256(
        json.dumps(measurement, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    recorded = datetime(2026, 8, 12, tzinfo=UTC)
    monkeypatch.setattr(
        outcomes,
        "connection",
        lambda *_args, **kwargs: _Db(
            (measurement, digest, recorded),
            [(measurement, digest, recorded)] if kwargs.get("repeatable_read") else (),
        ),
    )
    retained = outcomes.retain_measurement(principal, measurement)
    assert retained["retained"] is True
    assert retained["content_hash"] == digest
    timeline = outcomes.measurement_timeline(principal, 500)
    assert timeline["limit"] == 100
    assert timeline["items"][0]["measurement"] == measurement


def test_learning_candidate_lifecycle_is_retained_and_independently_reviewed(monkeypatch):
    principal = _db_principal("ontology_propose", "ontology_review", "ontology_read")
    evaluation = {
        "contract": "learning-evaluation/1",
        "candidate_id": "lc_" + "b" * 64,
        "measurement": {"scope": {"legal_entity_id": str(principal.scope.legal_entity_id)}},
    }
    recorded = datetime(2026, 8, 12, tzinfo=UTC)
    captured = {}

    class CandidateDb(_Db):
        def execute(self, sql, params=None):
            captured["sql"] = sql
            if sql.startswith("INSERT"):
                payload = params[5].obj if hasattr(params[5], "obj") else params[5]
                captured["payload"] = payload
            return super().execute(sql, params)

    import hashlib
    import json

    def db_factory(*_args, **_kwargs):
        class Conn(CandidateDb):
            def fetchone(self):
                payload = captured.get("payload", {})
                digest = hashlib.sha256(
                    json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                return (payload, digest, recorded)

        return Conn()

    monkeypatch.setattr(outcomes, "connection", db_factory)
    event = outcomes.retain_learning_candidate(principal, evaluation)
    assert event["event"]["event_type"] == "EVALUATED"
    assert event["promotion_executed"] is False

    candidate_id = evaluation["candidate_id"]
    current_payload = {"event_type": "EVALUATED", "candidate_id": candidate_id}
    current_hash = hashlib.sha256(
        json.dumps(current_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    class DecisionDb(_Db):
        def execute(self, sql, params=None):
            if sql.startswith("INSERT"):
                self.inserted = (
                    params[5].obj if hasattr(params[5], "obj") else params[5],
                    params[6],
                    recorded,
                )
            return super().execute(sql, params)

        def fetchone(self):
            if (
                "learning_candidate_events" in getattr(self, "sql", "")
                and hasattr(self, "inserted")
            ):
                return self.inserted
            return (current_payload, "other-actor")

    monkeypatch.setattr(outcomes, "connection", lambda *_args, **_kwargs: DecisionDb())
    approved = outcomes.decide_learning_candidate(
        _db_principal("ontology_review"),
        candidate_id,
        "PROMOTION_APPROVED",
        "independent review approved",
    )
    assert approved["event"]["previous_event"] == "EVALUATED"
    assert current_hash


def test_learning_candidate_validation_and_timeline_errors(monkeypatch):
    principal = _db_principal("ontology_propose", "ontology_review", "ontology_read")
    with pytest.raises(WorkspaceError, match="non-negative"):
        outcomes.evaluate_learning(principal, UUID(int=1), UUID(int=2), "-1")
    with pytest.raises(WorkspaceError, match="identity"):
        outcomes.retain_learning_candidate(principal, {"contract": "learning-evaluation/1"})
    with pytest.raises(WorkspaceError, match="rationale"):
        outcomes.decide_learning_candidate(principal, "lc_" + "c" * 64, "REJECTED", "short")
    monkeypatch.setattr(outcomes, "connection", lambda *_args, **_kwargs: _Db(many=[]))
    result = outcomes.learning_candidate_timeline(principal, 0)
    assert result["limit"] == 1
    assert result["items"] == []
