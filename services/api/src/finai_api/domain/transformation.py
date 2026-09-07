"""Typed Function DAG definitions; dependencies are completion barriers, not data ports."""

from datetime import datetime
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from finai_api.domain.resource_lifecycle import VersionReference

NodeId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


class TransformationNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    node_id: NodeId
    function_id: UUID
    depends_on: list[NodeId] = Field(default_factory=list, max_length=31)
    offset: int = Field(default=0, ge=0, le=1000000)
    limit: int = Field(default=50, ge=1, le=200)


class TransformationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    output_id: NodeId
    node_id: NodeId


class TransformationGraph(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    nodes: list[TransformationNode] = Field(min_length=1, max_length=32)
    outputs: list[TransformationOutput] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def valid_graph(self) -> "TransformationGraph":
        ids = {node.node_id for node in self.nodes}
        if len(ids) != len(self.nodes):
            raise ValueError("Transformation node IDs must be unique")
        if len({output.output_id for output in self.outputs}) != len(self.outputs):
            raise ValueError("Transformation output IDs must be unique")
        if any(output.node_id not in ids for output in self.outputs):
            raise ValueError("Transformation output must identify an existing node")
        for node in self.nodes:
            if len(set(node.depends_on)) != len(node.depends_on):
                raise ValueError("Transformation dependency edges must be unique")
            if node.node_id in node.depends_on or not set(node.depends_on).issubset(ids):
                raise ValueError("Transformation dependency must identify another existing node")
        self.topological_order()
        return self

    def topological_order(self) -> list[str]:
        pending = {node.node_id: set(node.depends_on) for node in self.nodes}
        order = []
        while pending:
            ready = sorted(name for name, dependencies in pending.items() if not dependencies)
            if not ready:
                raise ValueError("Transformation dependencies contain a cycle")
            for name in ready:
                order.append(name)
                del pending[name]
            for dependencies in pending.values():
                dependencies.difference_update(ready)
        return order


class TransformationResourceBudget(BaseModel):
    """Returned results and evaluations, not database scan, memory or storage quotas."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    max_returned_rows: int = Field(strict=True, ge=1, le=6400)
    max_derived_evaluations: int = Field(strict=True, ge=0, le=51200)
    max_published_result_bytes: int = Field(strict=True, ge=1, le=16000000)


class TransformationDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    definition: TransformationGraph
    resource_budget: TransformationResourceBudget
    evidence_id: UUID | None = None


class TransformationRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: UUID = Field(default_factory=uuid4)
    transformation: VersionReference
    valid_at: datetime
    known_at: datetime

    @field_validator("valid_at", "known_at")
    @classmethod
    def aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Transformation timestamps must include a timezone")
        return value
