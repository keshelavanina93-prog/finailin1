# ruff: noqa: F811
"""Additional artifact discovery and live local-observer refusal boundaries.

Native fixtures are isolated synthetic definitions, not company financial authority.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from psycopg.rows import dict_row
from pydantic import ValidationError
from test_definition_history import DB, item, retained  # noqa: F401

from finai_api.domain.artifact_retention import (
    RetentionEvaluationRequest,
    RetentionPolicyDiscoveryRequest,
)
from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.services import artifact_retention as retention
from finai_api.services import fact_runs
from finai_api.services import runtime_observations as runtime
from finai_api.services.resources import resource_connection
from finai_api.services.workspace import WorkspaceError


def policy(kind):
    return item(
        "RetentionPolicy",
        {
            "definition": {
                "artifact_classes": [kind],
                "minimum_retention_days": 0,
                "legal_basis_state": "NOT_ESTABLISHED",
                "legal_hold": False,
            }
        },
    )


@DB
def test_policy_discovery_pages_only_matching_reviewed_company_definitions(retained):
    reader, publish = retained
    run = fact_runs.retain_run(reader, {"synthetic_discovery_fixture": uuid4().hex})
    policies = [policy("REPRODUCIBLE_DERIVED_ARTIFACT") for _ in range(2)]
    excluded = policy("IMMUTABLE_SOURCE_EVIDENCE")
    rows = publish(*policies, excluded)
    reference = {"kind": "FACT_RUN", "run_id": run["run_id"]}
    first = retention.discover_policies(
        reader,
        RetentionPolicyDiscoveryRequest(
            artifact=reference,
            limit=1,
        ),
    )
    second = retention.discover_policies(
        reader,
        RetentionPolicyDiscoveryRequest(
            artifact=reference,
            limit=1,
            after_resource_id=first["next_cursor"],
        ),
    )
    assert first["execution_authorized"] is False and second["execution_authorized"] is False
    assert second["next_cursor"] is None
    matches = first["items"] + second["items"]
    assert [m["reference"]["resource_id"] for m in matches] == sorted(
        row["resource_id"] for row in rows[:2]
    )
    assert all(m["definition"]["legal_basis_state"] == "NOT_ESTABLISHED" for m in matches)
    # Discovery is a candidate list; an unestablished legal basis still blocks deletion.
    evaluated = retention.evaluate(
        reader,
        RetentionEvaluationRequest(
            artifact=reference,
            policy=matches[0]["reference"],
            requested_action="DELETE",
        ),
    )
    assert evaluated["proof"]["reasons"] == ["LEGAL_BASIS_NOT_ESTABLISHED"]
    assert evaluated["proof"]["effective_disposition"] == "PRESERVE"
    other = reader.model_copy(
        update={"scope": reader.scope.model_copy(update={"period": "2026-07"})}
    )
    with pytest.raises(WorkspaceError) as denied:
        retention.discover_policies(other, RetentionPolicyDiscoveryRequest(artifact=reference))
    assert denied.value.status == 404


@DB
def test_artifact_integrity_mismatch_cannot_be_rendered_as_retained_proof(retained):
    reader, _ = retained
    run = fact_runs.retain_run(reader, {"synthetic_integrity_fixture": uuid4().hex})
    request = RetentionEvaluationRequest(artifact={"kind": "FACT_RUN", "run_id": run["run_id"]})
    original = retention.evaluate(reader, request)
    with resource_connection(reader) as conn, conn.cursor(row_factory=dict_row) as cursor:
        runtime._scope(conn, reader)
        row = cursor.execute(
            "SELECT * FROM artifact_retention_evaluations WHERE evaluation_id=%s",
            (request.request_id,),
        ).fetchone()
    assert row is not None
    # Corruption is injected into the retrieved envelope only; immutable rows stay untouched.
    corrupted = {**row, "payload": {**row["payload"], "effective_disposition": "DELETE"}}
    with pytest.raises(WorkspaceError, match="integrity"):
        retention._envelope(corrupted)
    assert retention.history(reader, request.request_id) == original


@pytest.mark.parametrize(
    "artifact",
    [
        {"kind": "SOURCE_DOCUMENT", "document_id": "../../private/source.xlsx"},
        {"kind": "SOURCE_RECEIPT", "receipt_id": "D:\\outside\\source.csv"},
        {"kind": "FACT_RUN", "run_id": "fcr_" + "z" * 64},
        {
            "kind": "PUBLICATION_MANIFEST",
            "workflow_id": "fixture",
            "generation": -1,
            "publication_id": "pub_" + "a" * 64,
        },
    ],
)
def test_artifact_request_requires_canonical_reference_not_paths(artifact):
    with pytest.raises(ValidationError):
        RetentionEvaluationRequest(artifact=artifact)


def reviewed_controls(retained):
    reader, publish = retained
    admin = reader.model_copy(update={"permissions": (*reader.permissions, "ontology_admin")})
    loaded = runtime.function_execution._STARTUP_MANIFEST
    target = item(
        "DeploymentTarget",
        {
            "definition": {
                "environment_class": "LOCAL_DEVELOPMENT",
                "component": "api",
                "label": "TEST observer",
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
                "expected_code_sha256": loaded["code_sha256"],
                "expected_dependency_sha256": loaded["dependency_sha256"],
                "required_schema_version": 62,
                "max_observation_age_seconds": 300,
            },
        },
    )
    rows = publish(target, agent, desired)
    return admin, [
        VersionReference(resource_id=row["resource_id"], version_id=row["version_id"])
        for row in rows
    ]


@DB
def test_live_observer_collects_real_local_state_without_deployment_authority(retained):
    admin, references = reviewed_controls(retained)
    request = runtime.ObservationRequest(desired_state=references[-1])
    result = runtime.capture(admin, request)
    actual = result["reported_state"]["observation"]
    assert actual["database_schema_version"] >= 62
    assert actual["health"]["database"] == "ready"
    assert actual["health"]["evidence_store"] == "ready"
    assert actual["loaded_identity"] == {
        key: runtime.function_execution._STARTUP_MANIFEST[key]
        for key in ("code_sha256", "dependency_sha256")
    }
    assert result["reported_state"]["release_provenance"] == "LOCAL_DEVELOPMENT_UNATTESTED"
    assert result["deployment_authorized"] is False and result["current_use_authorized"] is False
    with resource_connection(admin) as conn, conn.cursor(row_factory=dict_row) as cursor:
        runtime._scope(conn, admin)
        row = cursor.execute(
            "SELECT * FROM runtime_observations WHERE request_id=%s", (request.request_id,)
        ).fetchone()
    for changed in ({"request_hash": "0" * 64}, {"proof_hash": "0" * 64}, {"request_id": uuid4()}):
        with pytest.raises(WorkspaceError, match="evidence mismatch"):
            runtime._envelope(admin, {**row, **changed})
    other_actor = admin.model_copy(update={"actor_id": "different-fixture-observer"})
    with pytest.raises(WorkspaceError, match="already used differently"):
        runtime.capture(other_actor, request)
    with pytest.raises(WorkspaceError, match="already used differently"):
        runtime.capture(admin, request.model_copy(update={"desired_state": references[0]}))


@DB
def test_reviewed_control_type_owner_and_missing_exact_edge_are_refused(retained):
    admin, references = reviewed_controls(retained)
    with resource_connection(admin) as conn, conn.cursor(row_factory=dict_row) as cursor:
        with pytest.raises(WorkspaceError, match="DesiredState"):
            runtime.controls(cursor, admin, references[0])
        wrong_owner = admin.model_copy(update={"actor_id": "unrelated-fixture-observer"})
        with pytest.raises(WorkspaceError, match="does not match"):
            runtime.controls(cursor, wrong_owner, references[-1])

        class MissingEdge:
            def execute(self, query, params=None):
                if "FROM resource_dependencies" in query and params[-1] == "FIELD:runtime_agent_id":
                    return self
                return cursor.execute(query, params)

            def fetchall(self):
                return []

        with pytest.raises(WorkspaceError, match="exact dependency"):
            runtime.controls(MissingEdge(), admin, references[-1])


@DB
def test_collector_degrades_when_disk_identity_or_database_is_unavailable(retained, monkeypatch):
    reader, _ = retained

    def unavailable(*args, **kwargs):
        raise OSError("controlled fixture unavailable")

    monkeypatch.setattr(runtime.function_execution, "_disk_manifest", unavailable)
    disk_failure = runtime.collect(reader)
    assert disk_failure["disk_identity"] is None and not disk_failure["disk_matches_loaded"]
    assert disk_failure["database_schema_version"] >= 62
    assert runtime.classify({}, disk_failure) == "DEGRADED"
    monkeypatch.setattr(runtime, "resource_connection", unavailable)
    database_failure = runtime.collect(reader)
    assert database_failure["health"]["database"] == "unavailable"
    assert database_failure["database_schema_version"] == 0
    assert runtime.classify({}, database_failure) == "DEGRADED"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 0},
        {"limit": 51},
        {"before_recorded_at": datetime.now(UTC)},
        {"before_request_id": uuid4()},
        {"before_recorded_at": datetime(2026, 1, 1), "before_request_id": uuid4()},
    ],
)
def test_observation_cursor_refuses_unbounded_or_ambiguous_pages(retained, kwargs):
    reader, _ = retained
    admin = reader.model_copy(update={"permissions": ("ontology_admin",)})
    with pytest.raises(WorkspaceError) as invalid:
        runtime.listing(admin, **kwargs)
    assert invalid.value.status == 422
