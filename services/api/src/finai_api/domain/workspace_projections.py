"""Server-owned projection taxonomy and exact cross-canvas selection contract."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


ProjectionKind = Literal[
    "ACTION",
    "CHART",
    "FIELD",
    "GRID",
    "HIERARCHY",
    "IMAGE",
    "KPI",
    "MAP",
    "NETWORK",
    "TABLE",
    "TEXT",
    "WATERFALL",
]
WorkspaceKind = Literal[
    "TABLE_FIRST",
    "GRAPH_FIRST",
    "TIMELINE_FIRST",
    "BRIDGE_FIRST",
    "COMMAND_EXECUTIVE",
    "REPORT",
]


class WorkspaceSelection(Model):
    """Selection context shared by projections; it never grants authority."""

    selected_object_id: str | None = Field(default=None, min_length=1, max_length=256)
    company_id: str = Field(min_length=1, max_length=256)
    product_id: str | None = Field(default=None, min_length=1, max_length=256)
    station_id: str | None = Field(default=None, min_length=1, max_length=256)
    period: str | None = Field(default=None, min_length=1, max_length=64)
    scenario_id: str | None = Field(default=None, min_length=1, max_length=256)
    version_id: str | None = Field(default=None, min_length=1, max_length=256)
    comparison_baseline: str | None = Field(default=None, min_length=1, max_length=256)
    replay_as_of: str | None = Field(default=None, min_length=1, max_length=128)


class ProjectionDefinition(Model):
    projection_id: str = Field(min_length=1, max_length=128)
    kind: ProjectionKind
    label: str = Field(min_length=1, max_length=128)
    workspaces: tuple[WorkspaceKind, ...]
    selection_fields: tuple[str, ...]
    backend_contracts: tuple[str, ...]
    status: Literal["IMPLEMENTED", "PARTIAL", "REGISTERED"]
    authority_effect: Literal["NONE"] = "NONE"


def _projection(
    projection_id: str,
    kind: ProjectionKind,
    label: str,
    workspaces: tuple[WorkspaceKind, ...],
    selection_fields: tuple[str, ...],
    backend_contracts: tuple[str, ...],
    status: Literal["IMPLEMENTED", "PARTIAL", "REGISTERED"],
) -> ProjectionDefinition:
    return ProjectionDefinition(
        projection_id=projection_id,
        kind=kind,
        label=label,
        workspaces=workspaces,
        selection_fields=selection_fields,
        backend_contracts=backend_contracts,
        status=status,
    )


PROJECTIONS: tuple[ProjectionDefinition, ...] = (
    _projection("executive-kpi", "KPI", "Executive KPI", ("COMMAND_EXECUTIVE", "REPORT"), ("company_id", "period", "scenario_id", "comparison_baseline"), ("planning-catalog/1", "planning-comparison/1"), "PARTIAL"),  # noqa: E501
    _projection("variance-waterfall", "WATERFALL", "Variance waterfall", ("BRIDGE_FIRST", "REPORT"), ("company_id", "product_id", "station_id", "period", "scenario_id", "comparison_baseline"), ("planning-comparison/1",), "REGISTERED"),  # noqa: E501
    _projection("planning-grid", "GRID", "Planning grid", ("TABLE_FIRST", "REPORT"), ("company_id", "period", "scenario_id", "version_id"), ("planning-catalog/1",), "IMPLEMENTED"),  # noqa: E501
    _projection("hierarchy-drilldown", "HIERARCHY", "Hierarchy drill-down", ("TABLE_FIRST", "GRAPH_FIRST"), ("company_id", "product_id", "station_id", "period", "replay_as_of"), ("operations-map/1",), "PARTIAL"),  # noqa: E501
    _projection("movement-network", "NETWORK", "Movement network", ("GRAPH_FIRST", "TIMELINE_FIRST"), ("company_id", "product_id", "station_id", "period", "replay_as_of"), ("operations-map/1",), "PARTIAL"),  # noqa: E501
    _projection("operations-map", "MAP", "Operations map", ("GRAPH_FIRST", "TIMELINE_FIRST"), ("company_id", "station_id", "period", "replay_as_of"), ("operations-map/1",), "IMPLEMENTED"),  # noqa: E501
    _projection("evidence-table", "TABLE", "Evidence and lineage table", ("TABLE_FIRST", "REPORT"), ("company_id", "selected_object_id", "replay_as_of"), ("workspace/constructions",), "IMPLEMENTED"),  # noqa: E501
    _projection("nyx-context", "TEXT", "NYX governed explanation", ("COMMAND_EXECUTIVE", "REPORT"), ("company_id", "selected_object_id", "period", "scenario_id", "version_id", "replay_as_of"), ("nyx/context",), "PARTIAL"),  # noqa: E501
)


def projection_catalog() -> list[dict[str, object]]:
    return [item.model_dump(mode="json") for item in PROJECTIONS]
