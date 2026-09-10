"""Deterministic, evidence-bound outcome measurement over accepted plan facts."""

import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any, Literal
from uuid import UUID

from psycopg.types.json import Jsonb

from finai_api.security import require_permission
from finai_api.services import planning
from finai_api.services.workspace import WorkspaceError
from finai_api.storage import connection

DIMENSIONS = (
    "budget_article_id",
    "legal_entity_id",
    "period_id",
    "department_id",
    "measure",
    "warehouse_id",
    "unit_id",
    "currency_id",
)


def actual_vs_plan(principal, plan_scenario_id: UUID, actual_scenario_id: UUID) -> dict[str, Any]:
    """Measure accepted actual cells against accepted plan cells in one company scope.

    A ScenarioVersion is only treated as actual when its declared ``kind`` is
    ``ACTUAL`` (case-insensitive). The endpoint never promotes a scenario,
    recalculates a metric, or creates a learning candidate.
    """
    require_permission(principal, "ontology_read")
    company_id = str(principal.scope.legal_entity_id)
    scenarios = {
        str(row["resource_id"]): row
        for row in planning._resources(principal, "ScenarioVersion")
        if not row["attributes"].get("legal_entity_id")
        or str(row["attributes"].get("legal_entity_id")) == company_id
    }
    for scenario_id in (plan_scenario_id, actual_scenario_id):
        if str(scenario_id) not in scenarios:
            raise WorkspaceError(404, "Scenario is unavailable in the authorized company scope")
    actual_kind = str(scenarios[str(actual_scenario_id)]["attributes"].get("kind", "")).upper()
    if actual_kind != "ACTUAL":
        raise WorkspaceError(409, "Outcome measurement requires an ACTUAL scenario")

    grouped: dict[tuple[str, ...], dict[str, Decimal]] = {}
    wanted = {str(plan_scenario_id): "planned", str(actual_scenario_id): "actual"}
    for row in planning._resources(principal, "PlanningCellFact"):
        attrs = row["attributes"]
        if str(attrs.get("legal_entity_id")) != company_id:
            continue
        scenario = wanted.get(str(attrs.get("scenario_version_id")))
        if scenario is None:
            continue
        try:
            amount = Decimal(str(attrs["amount"]))
        except (InvalidOperation, KeyError) as exc:
            raise WorkspaceError(409, "Accepted planning cell contains an invalid amount") from exc
        key = tuple(str(attrs.get(name, "")) for name in DIMENSIONS)
        bucket = grouped.setdefault(key, {})
        bucket[scenario] = bucket.get(scenario, Decimal(0)) + amount

    rows = []
    for key, values in sorted(grouped.items()):
        planned = values.get("planned", Decimal(0))
        actual = values.get("actual", Decimal(0))
        variance = actual - planned
        rows.append(
            {
                "dimension": dict(zip(DIMENSIONS, key, strict=True)),
                "planned": format(planned, "f"),
                "actual": format(actual, "f"),
                "variance": format(variance, "f"),
            }
        )
    identity_material = {
        "contract": "outcome-measurement/1",
        "plan_scenario_id": str(plan_scenario_id),
        "actual_scenario_id": str(actual_scenario_id),
        "legal_entity_id": company_id,
        "rows": rows,
    }
    return {
        "contract": "outcome-measurement/1",
        "measurement_id": "om_" + sha256(
            json.dumps(identity_material, sort_keys=True).encode()
        ).hexdigest(),
        "observed_at": datetime.now(UTC).isoformat(),
        "scope": {"legal_entity_id": company_id},
        "plan_scenario": scenarios[str(plan_scenario_id)],
        "actual_scenario": scenarios[str(actual_scenario_id)],
        "rows": rows,
        "coverage": "ACCEPTED_PLANNING_CELL_FACTS",
        "measurement_authorized": True,
        "learning_candidate_created": False,
        "policy_or_model_changed": False,
        "business_effect_authorized": False,
    }


def multi_baseline(
    principal, actual_scenario_id: UUID, baseline_scenario_ids: tuple[UUID, ...]
) -> dict[str, Any]:
    """Compare one validated Actual snapshot with several immutable baselines."""

    require_permission(principal, "ontology_read")
    if not baseline_scenario_ids or len(baseline_scenario_ids) > 12:
        raise WorkspaceError(422, "Provide between 1 and 12 baseline snapshots")
    if actual_scenario_id in baseline_scenario_ids or len(set(baseline_scenario_ids)) != len(
        baseline_scenario_ids
    ):
        raise WorkspaceError(422, "Actual and baseline snapshots must be distinct")
    comparisons = []
    for baseline_id in baseline_scenario_ids:
        measurement = actual_vs_plan(principal, baseline_id, actual_scenario_id)
        comparisons.append(
            {
                "baseline": measurement["plan_scenario"],
                "alignment": "EXACT",
                "rows": [
                    {
                        "dimension": row["dimension"],
                        "baseline": row["planned"],
                        "actual": row["actual"],
                        "variance": row["variance"],
                    }
                    for row in measurement["rows"]
                ],
            }
        )
    identity_material = {
        "contract": "outcome-multi-baseline/1",
        "actual_scenario_id": str(actual_scenario_id),
        "baseline_scenario_ids": [str(item) for item in baseline_scenario_ids],
        "comparisons": comparisons,
        "legal_entity_id": str(principal.scope.legal_entity_id),
    }
    return {
        "contract": "outcome-multi-baseline/1",
        "measurement_id": "omb_"
        + sha256(json.dumps(identity_material, sort_keys=True, default=str).encode()).hexdigest(),
        "scope": {"legal_entity_id": str(principal.scope.legal_entity_id)},
        "actual_scenario": measurement["actual_scenario"],
        "comparisons": comparisons,
        "coverage": "ACCEPTED_PLANNING_CELL_FACTS",
        "comparison_authorized": True,
        "business_effect_authorized": False,
    }


def evaluate_learning(
    principal, plan_scenario_id: UUID, actual_scenario_id: UUID, tolerance: str
) -> dict[str, Any]:
    """Evaluate a measured outcome in shadow mode without promoting learning."""
    try:
        threshold = Decimal(tolerance)
    except InvalidOperation as exc:
        raise WorkspaceError(422, "Learning tolerance must be a finite decimal") from exc
    if not threshold.is_finite() or threshold < 0:
        raise WorkspaceError(422, "Learning tolerance must be a non-negative finite decimal")
    measurement = actual_vs_plan(principal, plan_scenario_id, actual_scenario_id)
    rows = []
    within_tolerance = True
    for row in measurement["rows"]:
        variance = Decimal(row["variance"])
        absolute = abs(variance)
        accepted = absolute <= threshold
        within_tolerance = within_tolerance and accepted
        rows.append(
            {**row, "absolute_variance": format(absolute, "f"), "within_tolerance": accepted}
        )
    candidate_material = {
        "measurement_contract": measurement["contract"],
        "plan_scenario_id": str(plan_scenario_id),
        "actual_scenario_id": str(actual_scenario_id),
        "tolerance": format(threshold, "f"),
        "rows": rows,
    }
    candidate_id = (
        "lc_" + sha256(json.dumps(candidate_material, sort_keys=True).encode()).hexdigest()
    )
    return {
        "contract": "learning-evaluation/1",
        "candidate_id": candidate_id,
        "measurement": {**measurement, "rows": rows},
        "status": "SHADOW_PASS" if within_tolerance else "SHADOW_REVIEW_REQUIRED",
        "tolerance": format(threshold, "f"),
        "promotion_required": True,
        "production_policy_changed": False,
        "production_model_changed": False,
        "business_effect_authorized": False,
    }


def retain_measurement(principal, measurement: dict[str, Any]) -> dict[str, Any]:
    """Retain an exact deterministic measurement without promoting learning."""
    require_permission(principal, "ontology_propose")
    expected_scope = {"legal_entity_id": str(principal.scope.legal_entity_id)}
    if (
        measurement.get("contract") != "outcome-measurement/1"
        or measurement.get("scope") != expected_scope
    ):
        raise WorkspaceError(422, "Outcome measurement does not match the authorized company scope")
    measurement_id = str(measurement.get("measurement_id", ""))
    if not measurement_id.startswith("om_") or len(measurement_id) != 67:
        raise WorkspaceError(422, "Outcome measurement identity is invalid")
    content_hash = sha256(
        json.dumps(measurement, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    scope = principal.scope.model_dump(mode="json")
    with connection(principal.scope) as conn:
        conn.execute("SELECT set_config('finai.exact_scope',%s,true)", (json.dumps(scope),))
        conn.execute(
            "INSERT INTO outcome_measurements "
            "(tenant_id,measurement_id,exact_scope,payload,content_hash,actor_id) "
            "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (tenant_id,measurement_id) DO NOTHING",
            (
                principal.scope.tenant_id,
                measurement_id,
                Jsonb(scope),
                Jsonb(measurement),
                content_hash,
                principal.actor_id,
            ),
        )
        row = conn.execute(
            "SELECT payload,content_hash,recorded_at FROM outcome_measurements "
            "WHERE tenant_id=%s AND measurement_id=%s AND exact_scope=%s",
            (principal.scope.tenant_id, measurement_id, Jsonb(scope)),
        ).fetchone()
    if row is None or row[1] != content_hash:
        raise WorkspaceError(409, "Outcome measurement retention integrity check failed")
    return {
        "measurement": dict(row[0]),
        "content_hash": row[1],
        "recorded_at": row[2].isoformat(),
        "retained": True,
    }


def measurement_timeline(principal, limit: int = 50) -> dict[str, Any]:
    """Read retained outcome measurements in the caller's exact company scope."""
    require_permission(principal, "ontology_read")
    bounded = max(1, min(limit, 100))
    scope = principal.scope.model_dump(mode="json")
    with connection(principal.scope, repeatable_read=True) as conn:
        conn.execute("SELECT set_config('finai.exact_scope',%s,true)", (json.dumps(scope),))
        rows = conn.execute(
            "SELECT payload,content_hash,recorded_at FROM outcome_measurements "
            "WHERE tenant_id=%s AND exact_scope=%s "
            "ORDER BY recorded_at DESC,measurement_id DESC LIMIT %s",
            (principal.scope.tenant_id, Jsonb(scope), bounded),
        ).fetchall()
    items = []
    for payload, content_hash, recorded_at in rows:
        if (
            sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            != content_hash
        ):
            raise WorkspaceError(409, "Outcome measurement timeline integrity failed")
        items.append(
            {
                "measurement": dict(payload),
                "content_hash": content_hash,
                "recorded_at": recorded_at.isoformat(),
            }
        )
    return {
        "contract": "outcome-measurement-timeline/1",
        "scope": {"legal_entity_id": str(principal.scope.legal_entity_id)},
        "items": items,
        "limit": bounded,
    }


def retain_learning_candidate(principal, evaluation: dict[str, Any]) -> dict[str, Any]:
    """Retain a shadow evaluation as a governed candidate, without deploying it."""
    require_permission(principal, "ontology_propose")
    candidate_id = str(evaluation.get("candidate_id", ""))
    if evaluation.get("contract") != "learning-evaluation/1" or not (
        candidate_id.startswith("lc_") and len(candidate_id) == 67
    ):
        raise WorkspaceError(422, "Learning evaluation identity is invalid")
    measurement = evaluation.get("measurement")
    if not isinstance(measurement, dict) or measurement.get("scope") != {
        "legal_entity_id": str(principal.scope.legal_entity_id)
    }:
        raise WorkspaceError(422, "Learning candidate is outside the authorized company scope")
    event = {
        "contract": "learning-candidate-event/1",
        "candidate_id": candidate_id,
        "event_type": "EVALUATED",
        "evaluation": evaluation,
        "promotion_executed": False,
        "rollback_executed": False,
        "production_policy_changed": False,
        "production_model_changed": False,
        "business_effect_authorized": False,
    }
    return _retain_learning_event(principal, event)


def decide_learning_candidate(
    principal,
    candidate_id: str,
    decision: Literal["PROMOTION_APPROVED", "REJECTED", "ROLLBACK_APPROVED"],
    rationale: str,
) -> dict[str, Any]:
    """Record independent candidate governance; execution remains a separate disabled plane."""
    require_permission(principal, "ontology_review")
    if not (candidate_id.startswith("lc_") and len(candidate_id) == 67):
        raise WorkspaceError(422, "Learning candidate identity is invalid")
    rationale = rationale.strip()
    if len(rationale) < 10:
        raise WorkspaceError(422, "Learning candidate rationale needs at least 10 characters")
    scope = principal.scope.model_dump(mode="json")
    with connection(principal.scope, repeatable_read=True) as conn:
        conn.execute("SELECT set_config('finai.exact_scope',%s,true)", (json.dumps(scope),))
        row = conn.execute(
            "SELECT payload,actor_id FROM learning_candidate_events "
            "WHERE tenant_id=%s AND candidate_id=%s AND exact_scope=%s "
            "ORDER BY recorded_at DESC,event_id DESC LIMIT 1",
            (principal.scope.tenant_id, candidate_id, Jsonb(scope)),
        ).fetchone()
    if row is None:
        raise WorkspaceError(404, "Learning candidate is unavailable in authorized scope")
    current = dict(row[0])
    if row[1] == principal.actor_id:
        raise WorkspaceError(409, "Independent reviewer identity is required")
    current_type = str(current.get("event_type"))
    if decision == "ROLLBACK_APPROVED" and current_type != "PROMOTION_APPROVED":
        raise WorkspaceError(409, "Only an approved promotion can be rolled back")
    if decision == "PROMOTION_APPROVED" and current_type != "EVALUATED":
        raise WorkspaceError(409, "Only an evaluated candidate can be approved")
    if decision == "REJECTED" and current_type not in {"EVALUATED", "PROMOTION_APPROVED"}:
        raise WorkspaceError(409, "Learning candidate is not reviewable in its current state")
    event = {
        "contract": "learning-candidate-event/1",
        "candidate_id": candidate_id,
        "event_type": decision,
        "rationale": rationale,
        "previous_event": current_type,
        "promotion_executed": False,
        "rollback_executed": False,
        "production_policy_changed": False,
        "production_model_changed": False,
        "business_effect_authorized": False,
    }
    return _retain_learning_event(principal, event)


def _retain_learning_event(principal, event: dict[str, Any]) -> dict[str, Any]:
    scope = principal.scope.model_dump(mode="json")
    content_hash = sha256(
        json.dumps(event, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    event_id = "lce_" + sha256(
        f"{event['candidate_id']}:{event['event_type']}:{content_hash}".encode()
    ).hexdigest()
    with connection(principal.scope) as conn:
        conn.execute("SELECT set_config('finai.exact_scope',%s,true)", (json.dumps(scope),))
        conn.execute(
            "INSERT INTO learning_candidate_events "
            "(tenant_id,event_id,candidate_id,event_type,exact_scope,payload,"
            "content_hash,actor_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (
                principal.scope.tenant_id,
                event_id,
                event["candidate_id"],
                event["event_type"],
                Jsonb(scope),
                Jsonb(event),
                content_hash,
                principal.actor_id,
            ),
        )
        row = conn.execute(
            "SELECT payload,content_hash,recorded_at FROM learning_candidate_events "
            "WHERE tenant_id=%s AND event_id=%s AND exact_scope=%s",
            (principal.scope.tenant_id, event_id, Jsonb(scope)),
        ).fetchone()
    if row is None or row[1] != content_hash:
        raise WorkspaceError(409, "Learning candidate event integrity check failed")
    return {
        "event": dict(row[0]),
        "event_id": event_id,
        "content_hash": row[1],
        "recorded_at": row[2].isoformat(),
        "promotion_executed": False,
        "rollback_executed": False,
    }


def learning_candidate_timeline(principal, limit: int = 50) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    bounded = max(1, min(limit, 100))
    scope = principal.scope.model_dump(mode="json")
    with connection(principal.scope, repeatable_read=True) as conn:
        conn.execute("SELECT set_config('finai.exact_scope',%s,true)", (json.dumps(scope),))
        rows = conn.execute(
            "SELECT DISTINCT ON (candidate_id) payload,event_id,content_hash,recorded_at "
            "FROM learning_candidate_events WHERE tenant_id=%s AND exact_scope=%s "
            "ORDER BY candidate_id,recorded_at DESC,event_id DESC LIMIT %s",
            (principal.scope.tenant_id, Jsonb(scope), bounded),
        ).fetchall()
    items = []
    for payload, event_id, content_hash, recorded_at in rows:
        if (
            sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            != content_hash
        ):
            raise WorkspaceError(409, "Learning candidate timeline integrity failed")
        items.append(
            {
                "event": dict(payload),
                "event_id": event_id,
                "content_hash": content_hash,
                "recorded_at": recorded_at.isoformat(),
            }
        )
    return {
        "contract": "learning-candidate-timeline/1",
        "scope": {"legal_entity_id": str(principal.scope.legal_entity_id)},
        "items": items,
        "limit": bounded,
    }
