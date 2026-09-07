"""Local runtime intent uses canonical references and never implies release acceptance."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from finai_api.domain.resources import ResourceMutation
from finai_api.domain.runtime_deployment import (
    DeploymentTarget,
    DesiredStateDefinition,
    validate_runtime_deployment,
)


def test_local_target_rejects_pristine_release_or_unknown_component():
    DeploymentTarget.model_validate(
        {
            "definition": {
                "environment_class": "LOCAL_DEVELOPMENT",
                "component": "api",
                "label": "Local API",
            }
        }
    )
    for environment, component in [("PRODUCTION", "api"), ("LOCAL_DEVELOPMENT", "web")]:
        with pytest.raises(ValidationError):
            DeploymentTarget.model_validate(
                {
                    "definition": {
                        "environment_class": environment,
                        "component": component,
                        "label": "Local",
                    }
                }
            )


def test_desired_state_validates_digest_freshness_and_schema_bounds():
    values = {
        "expected_code_sha256": "a" * 64,
        "expected_dependency_sha256": "b" * 64,
        "required_schema_version": 47,
        "max_observation_age_seconds": 300,
    }
    DesiredStateDefinition.model_validate(values)
    for key, value in [
        ("expected_code_sha256", "HEAD"),
        ("max_observation_age_seconds", 0),
        ("required_schema_version", True),
    ]:
        with pytest.raises(ValidationError):
            DesiredStateDefinition.model_validate({**values, key: value})


def test_desired_state_binds_existing_target_agent_and_denies_mismatch():
    target_id, agent_id = uuid4(), uuid4()
    target_row = {
        "object_type": "DeploymentTarget",
        "attributes": {
            "definition": {
                "environment_class": "LOCAL_DEVELOPMENT",
                "component": "api",
                "label": "Local",
            }
        },
    }
    agent_row = {
        "object_type": "RuntimeAgent",
        "attributes": {
            "deployment_target_id": str(target_id),
            "definition": {"actor_id": "operator"},
        },
    }
    mutation = ResourceMutation(
        object_type="DesiredState",
        identity_key="local-api",
        display_name="Local API",
        valid_from=datetime.now(UTC),
        attributes={
            "deployment_target_id": str(target_id),
            "runtime_agent_id": str(agent_id),
            "definition": {
                "expected_code_sha256": "a" * 64,
                "expected_dependency_sha256": "b" * 64,
                "required_schema_version": 47,
                "max_observation_age_seconds": 300,
            },
        },
    )
    calls = []

    def target(identity, owner, relation):
        calls.append((identity, owner, relation))
        return target_row if identity == str(target_id) else agent_row

    validate_runtime_deployment(mutation, target)
    assert [entry[2] for entry in calls] == ["FIELD:deployment_target_id", "FIELD:runtime_agent_id"]
    agent_row["attributes"]["deployment_target_id"] = str(uuid4())
    with pytest.raises(ValueError, match="same deployment target"):
        validate_runtime_deployment(mutation, target)
