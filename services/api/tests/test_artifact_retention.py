# ruff: noqa: F811
"""Synthetic native retention evaluation; no deletion or legal compliance claim."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_definition_history import DB, item, retained  # noqa: F401

from finai_api.domain.artifact_retention import RetentionEvaluationRequest
from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.services import artifact_retention as retention
from finai_api.services import fact_runs, resources
from finai_api.services.source_documents import document_bytes, retain_document
from finai_api.services.workspace import WorkspaceError


def policy_attributes(days=0, hold=False, state="DECLARED"):
    return {
        "definition": {
            "artifact_classes": ["REPRODUCIBLE_DERIVED_ARTIFACT"],
            "minimum_retention_days": days,
            "legal_hold": hold,
            "legal_basis_state": state,
            "legal_basis": "SYNTHETIC policy test; no actual legal determination",
        }
    }


def setup(retained, **kwargs):
    reader, publish = retained
    run = fact_runs.retain_run(reader, {"synthetic_acceptance": str(uuid4())})
    policy = item("RetentionPolicy", policy_attributes(**kwargs))
    published = publish(policy)[0]
    request = RetentionEvaluationRequest(
        artifact={"kind": "FACT_RUN", "run_id": run["run_id"]},
        policy=VersionReference(
            resource_id=published["resource_id"], version_id=published["version_id"]
        ),
        requested_action="DELETE",
    )
    return reader, publish, policy, request


@DB
@pytest.mark.parametrize(
    "conditions,reason",
    [
        ({"days": 1}, "MINIMUM_RETENTION_NOT_ELAPSED"),
        ({"hold": True}, "LEGAL_HOLD_DECLARED"),
        ({"state": "NOT_ESTABLISHED"}, "LEGAL_BASIS_NOT_ESTABLISHED"),
    ],
)
def test_native_retention_conditions_preserve_existing_artifact(retained, conditions, reason):
    reader, _, _, request = setup(retained, **conditions)
    result = retention.evaluate(reader, request)
    assert result["proof"]["status"] == "BLOCKED"
    assert reason in result["proof"]["reasons"]
    assert result["proof"]["effective_disposition"] == "PRESERVE"
    assert result["execution_authorized"] is False
    assert fact_runs.read_run(reader, request.artifact.run_id)
    if conditions.get("hold"):
        proof = {**result["proof"], "reasons": []}
        with (
            pytest.raises(psycopg.Error, match="policy conditions"),
            resources.resource_connection(reader) as conn,
        ):
            conn.execute(
                "SELECT set_config('finai.exact_scope',%s,true)",
                (json.dumps(reader.scope.model_dump(mode="json")),),
            )
            conn.execute(
                "INSERT INTO artifact_retention_evaluations SELECT tenant_id,%s,exact_scope,"
                "actor_id,request_hash,%s,%s,recorded_at FROM artifact_retention_evaluations "
                "WHERE evaluation_id=%s",
                (uuid4(), retention._digest(proof), Jsonb(proof), request.request_id),
            )


@DB
def test_retention_conditions_met_is_not_execution_and_replay_preserves_old_policy(retained):
    reader, publish, policy, request = setup(retained)
    result = retention.evaluate(reader, request)
    assert result["proof"]["status"] == "POLICY_CONDITIONS_MET"
    assert result["execution_authorized"] is False
    assert result["proof"]["legal_compliance_established"] is False
    publish(
        policy.model_copy(
            update={
                "expected_version_id": request.policy.version_id,
                "authority_state": "REVOKED",
                "valid_from": datetime.now(UTC) - timedelta(seconds=1),
            }
        )
    )
    assert retention.evaluate(reader, request) == result
    fresh = retention.evaluate(reader, request.model_copy(update={"request_id": uuid4()}))
    assert fresh["proof"]["status"] == "BLOCKED"
    assert fresh["proof"]["reasons"] == ["POLICY_UNAVAILABLE_FOR_CURRENT_USE"]
    assert retention.history(reader, request.request_id) == result
    with pytest.raises(WorkspaceError, match="already used differently"):
        retention.evaluate(reader, request.model_copy(update={"requested_action": "ARCHIVE"}))
    other = reader.model_copy(
        update={"scope": reader.scope.model_copy(update={"period": "2025-01"})}
    )
    with pytest.raises(WorkspaceError, match="unavailable"):
        retention.history(other, request.request_id)


@DB
def test_unconfigured_policy_and_sql_forged_classification_fail_closed(retained):
    reader, _, _, request = setup(retained)
    request = request.model_copy(update={"policy": None})
    result = retention.evaluate(reader, request)
    assert result["proof"]["reasons"] == ["POLICY_NOT_ESTABLISHED"]
    proof = {
        **result["proof"],
        "artifact": {
            **result["proof"]["artifact"],
            "artifact_class": "DISPOSABLE_CACHE_MATERIALIZATION",
        },
    }
    with (
        pytest.raises(psycopg.Error, match="exact artifact"),
        resources.resource_connection(reader) as conn,
    ):
        conn.execute(
            "SELECT set_config('finai.exact_scope',%s,true)",
            (json.dumps(reader.scope.model_dump(mode="json")),),
        )
        conn.execute(
            "INSERT INTO artifact_retention_evaluations SELECT tenant_id,%s,exact_scope,"
            "actor_id,request_hash,%s,%s,recorded_at FROM artifact_retention_evaluations "
            "WHERE evaluation_id=%s",
            (uuid4(), retention._digest(proof), Jsonb(proof), request.request_id),
        )


@DB
def test_real_source_document_preserves_bytes_and_server_classification(retained):
    reader, _ = retained
    operator = reader.model_copy(update={"permissions": ("ontology_read", "ingest")})
    content = ("SYNTHETIC retention test " + uuid4().hex).encode()
    document = retain_document(operator, "synthetic-retention.txt", content)
    request = RetentionEvaluationRequest(
        artifact={"kind": "SOURCE_DOCUMENT", "document_id": document["document_id"]},
        requested_action="DELETE",
    )
    result = retention.evaluate(operator, request)
    assert result["proof"]["artifact"]["artifact_class"] == "IMMUTABLE_SOURCE_EVIDENCE"
    assert result["proof"]["status"] == "BLOCKED"
    assert document_bytes(operator, document["document_id"])[1] == content
