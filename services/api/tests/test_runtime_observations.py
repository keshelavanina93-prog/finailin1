# ruff: noqa: F811
"""Native exact-control retention using explicitly synthetic collector observations."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from fastapi import HTTPException
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from test_definition_history import DB, item, retained  # noqa: F401

from finai_api.services import fact_runs
from finai_api.services import runtime_observations as runtime
from finai_api.services.resources import resource_connection
from finai_api.services.workspace import WorkspaceError


def observation():
    now = datetime.now(UTC)
    identity = {"code_sha256": "a" * 64, "dependency_sha256": "b" * 64}
    return {
        "observed_at": now.isoformat(),
        "observer_instance_id": str(uuid4()),
        "observer_started_at": (now - timedelta(seconds=60)).isoformat(),
        "loaded_identity": identity,
        "disk_identity": identity,
        "disk_matches_loaded": True,
        "database_schema_version": 47,
        "health": {"database": "ready", "schema": "ready", "evidence_store": "ready"},
        "identity_semantics": "FUNCTION_PACKAGE_STARTUP_SNAPSHOT_NOT_RELEASE_ATTESTATION",
    }


@DB
def test_exact_observation_replay_scope_paging_stale_and_forged_outcome(retained, monkeypatch):
    reader, publish = retained
    admin = reader.model_copy(update={"permissions": (*reader.permissions, "ontology_admin")})
    target = item(
        "DeploymentTarget",
        {
            "definition": {
                "environment_class": "LOCAL_DEVELOPMENT",
                "component": "api",
                "label": "SYNTHETIC API",
            }
        },
    )
    agent = item(
        "RuntimeAgent",
        {
            "deployment_target_id": str(target.resource_id),
            "definition": {"actor_id": admin.actor_id},
        },
    )
    desired = item(
        "DesiredState",
        {
            "deployment_target_id": str(target.resource_id),
            "runtime_agent_id": str(agent.resource_id),
            "definition": {
                "expected_code_sha256": "a" * 64,
                "expected_dependency_sha256": "b" * 64,
                "required_schema_version": 47,
                "max_observation_age_seconds": 1,
            },
        },
    )
    row = publish(target, agent, desired)[2]
    request = runtime.ObservationRequest(
        desired_state={"resource_id": row["resource_id"], "version_id": row["version_id"]}
    )
    captured = observation()
    captured["observed_at"] = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    monkeypatch.setattr(runtime, "collect", lambda _: captured)
    first = runtime.capture(admin, request)
    assert first["reported_state"]["recorded_state"] == "MATCH"
    assert first["assessment"]["state"] == "STALE"
    assert not first["deployment_authorized"]
    second = runtime.capture(admin, request.model_copy(update={"request_id": uuid4()}))
    page = runtime.listing(admin, 1)
    assert page["items"][0]["run_id"] == second["run_id"] and page["has_more"]
    older = runtime.listing(
        admin,
        1,
        datetime.fromisoformat(page["next_cursor"]["recorded_at"]),
        page["next_cursor"]["request_id"],
    )
    assert older["items"][0]["run_id"] == first["run_id"] and not older["has_more"]
    monkeypatch.setattr(runtime, "collect", lambda _: pytest.fail("Replay recollected runtime"))
    monkeypatch.setattr(
        runtime, "controls", lambda *_: pytest.fail("Replay resolved current controls")
    )
    assert runtime.capture(admin, request)["reported_state"] == first["reported_state"]
    assert runtime.history(admin, request.request_id)["reported_state"] == first["reported_state"]
    other = admin.model_copy(
        update={
            "scope": admin.scope.model_copy(update={"legal_entity_id": "other-synthetic-entity"})
        }
    )
    with pytest.raises(WorkspaceError, match="exact scope"):
        runtime.history(other, request.request_id)
    with pytest.raises(HTTPException):
        runtime.capture(reader, request)
    forged = dict(first["reported_state"])
    forged.pop("run_id")
    forged["recorded_state"] = "DRIFT"
    output = fact_runs.retain_run(admin, forged, runtime="local-api-observer/1")
    with pytest.raises(psycopg.errors.RaiseException, match="outcome mismatch"):  # noqa: SIM117
        with resource_connection(admin) as conn, conn.cursor(row_factory=dict_row) as cursor:
            scope = runtime._scope(conn, admin)
            cursor.execute(
                "INSERT INTO runtime_observations "
                "(tenant_id,request_id,exact_scope,actor_id,request_hash,run_id,proof_hash) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (
                    admin.scope.tenant_id,
                    request.request_id,
                    Jsonb(scope),
                    admin.actor_id,
                    runtime.canonical_sha256(request),
                    output["run_id"],
                    output["run_id"][4:],
                ),
            )


def test_drift_and_degraded_are_not_matches():
    actual = observation()
    expected = {
        "expected_code_sha256": "a" * 64,
        "expected_dependency_sha256": "b" * 64,
        "required_schema_version": 47,
    }
    assert runtime.classify(expected, actual) == "MATCH"
    assert runtime.classify(expected, {**actual, "database_schema_version": 45}) == "DRIFT"
    assert runtime.classify(expected, {**actual, "disk_matches_loaded": False}) == "DRIFT"
    assert runtime.classify(expected, {**actual, "disk_identity": None}) == "DEGRADED"
