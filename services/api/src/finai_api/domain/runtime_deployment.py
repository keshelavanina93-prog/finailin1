"""Reviewed local deployment intent; neither a release artifact nor an execution grant."""

from collections.abc import Callable
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from finai_api.domain.resources import ResourceMutation


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DeploymentTargetDefinition(Contract):
    environment_class: Literal["LOCAL_DEVELOPMENT"]
    component: Literal["api"]
    label: str = Field(min_length=1, max_length=128)


class DeploymentTarget(Contract):
    definition: DeploymentTargetDefinition
    evidence_id: UUID | None = None


class RuntimeAgentDefinition(Contract):
    actor_id: str = Field(min_length=1, max_length=128)


class RuntimeAgent(Contract):
    deployment_target_id: UUID
    definition: RuntimeAgentDefinition
    evidence_id: UUID | None = None


class DesiredStateDefinition(Contract):
    expected_code_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_dependency_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    required_schema_version: int = Field(strict=True, ge=1, le=1000000)
    max_observation_age_seconds: int = Field(strict=True, ge=1, le=86400)


class DesiredState(Contract):
    deployment_target_id: UUID
    runtime_agent_id: UUID
    definition: DesiredStateDefinition
    evidence_id: UUID | None = None


def validate_runtime_deployment(
    item: ResourceMutation, target: Callable[[str, str, str], dict]
) -> None:
    if item.object_type == "DeploymentTarget":
        DeploymentTarget.model_validate(item.attributes)
        return
    spec = (RuntimeAgent if item.object_type == "RuntimeAgent" else DesiredState).model_validate(
        item.attributes
    )
    selected = target(
        str(spec.deployment_target_id), str(item.resource_id), "FIELD:deployment_target_id"
    )
    if selected["object_type"] != "DeploymentTarget":
        raise ValueError("Runtime intent requires a canonical DeploymentTarget")
    DeploymentTarget.model_validate(selected["attributes"])
    if isinstance(spec, DesiredState):
        agent = target(str(spec.runtime_agent_id), str(item.resource_id), "FIELD:runtime_agent_id")
        if agent["object_type"] != "RuntimeAgent":
            raise ValueError("Desired state requires a canonical RuntimeAgent")
        agent_spec = RuntimeAgent.model_validate(agent["attributes"])
        if agent_spec.deployment_target_id != spec.deployment_target_id:
            raise ValueError(
                "Desired state and runtime agent must identify the same deployment target"
            )
