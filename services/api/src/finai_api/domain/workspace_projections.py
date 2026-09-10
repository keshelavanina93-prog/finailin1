"""Server-owned projection taxonomy and exact cross-canvas selection contract."""

from datetime import datetime
from typing import Any, Literal

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
ChartType = Literal[
    "AREA", "BAR", "COLUMN", "COMBINATION", "DOT", "GANTT", "LINE",
    "PIE", "SCATTER", "BUBBLE", "WATERFALL",
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
    workspace: WorkspaceKind | None = None


class ProjectionRow(Model):
    """Stable typed envelope shared by every projection renderer."""

    row_id: str
    coordinates: dict[str, str] = Field(default_factory=dict)
    measures: dict[str, str | float | int | None] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)
    authority_state: str = "UNSPECIFIED"
    evidence_refs: tuple[str, ...] = ()
    valid_at: str | None = None
    known_at: str | None = None
    interval_start: str | None = None
    interval_end: str | None = None


def normalize_projection_rows(rows: list[dict[str, Any]]) -> list[ProjectionRow]:
    """Expose stable coordinates/measures without discarding source-shaped rows."""

    result: list[ProjectionRow] = []
    def first_value(sources: tuple[dict[str, Any], ...], keys: tuple[str, ...]) -> str | None:
        for source in sources:
            for key in keys:
                if source.get(key) is not None:
                    return str(source[key])
        return None

    for index, row in enumerate(rows):
        attributes = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
        dimension = row.get("dimension")
        coordinates = {
            key: str(value)
            for key, value in row.items()
            if key.endswith("_id")
            and key not in {"evidence_id", "source_record_id", "resource_id"}
            and isinstance(value, (str, int))
        }
        if isinstance(dimension, dict):
            coordinates.update(
                {str(key): str(value) for key, value in dimension.items() if value is not None}
            )
        if isinstance(attributes, dict):
            coordinates.update(
                {
                    key: str(value)
                    for key, value in attributes.items()
                    if key.endswith("_id") and value is not None
                }
            )
        measures = {
            key: row.get(key)
            for key in ("value", "amount", "delta", "scenario_a", "scenario_b")
            if row.get(key) is not None
        }
        if (
            isinstance(attributes, dict)
            and attributes.get("amount") is not None
            and "amount" not in measures
        ):
            measures["amount"] = attributes["amount"]
        evidence_refs = tuple(
            str(row[key])
            for key in ("evidence_id", "source_record_id", "resource_id")
            if row.get(key) is not None
        )
        result.append(ProjectionRow(
            row_id=str(row.get("row_id") or row.get("id") or row.get("resource_id") or index),
            coordinates=coordinates,
            measures=measures,
            labels={
                key: str(row[key])
                for key in ("label", "period_id", "relation")
                if row.get(key) is not None
            },
            authority_state=str(row.get("authority_state") or "UNSPECIFIED"),
            evidence_refs=evidence_refs,
            valid_at=str(row["valid_at"]) if row.get("valid_at") is not None else None,
            known_at=str(row["known_at"]) if row.get("known_at") is not None else None,
            interval_start=first_value(
                (row, attributes), ("interval_start", "start_at", "period_starts_on")
            ),
            interval_end=first_value(
                (row, attributes), ("interval_end", "end_at", "period_ends_on")
            ),
        ))
    return result


def replay_timestamp(selection: WorkspaceSelection) -> datetime | None:
    """Parse the caller's replay pin for bitemporal read-only projection reads."""
    if selection.replay_as_of is None:
        return None
    value = selection.replay_as_of.strip()
    if not value:
        raise ValueError("replay_as_of must not be blank")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("replay_as_of must be an ISO-8601 timestamp") from exc


class ProjectionDefinition(Model):
    projection_id: str = Field(min_length=1, max_length=128)
    kind: ProjectionKind
    label: str = Field(min_length=1, max_length=128)
    workspaces: tuple[WorkspaceKind, ...]
    selection_fields: tuple[str, ...]
    backend_contracts: tuple[str, ...]
    status: Literal["IMPLEMENTED", "PARTIAL", "REGISTERED"]
    authority_effect: Literal["NONE"] = "NONE"
    chart_type: ChartType | None = None
    synchronization_group: Literal["WORKSPACE_SELECTION"] = "WORKSPACE_SELECTION"


def _projection(
    projection_id: str,
    kind: ProjectionKind,
    label: str,
    workspaces: tuple[WorkspaceKind, ...],
    selection_fields: tuple[str, ...],
    backend_contracts: tuple[str, ...],
    status: Literal["IMPLEMENTED", "PARTIAL", "REGISTERED"],
    chart_type: ChartType | None = None,
) -> ProjectionDefinition:
    return ProjectionDefinition(
        projection_id=projection_id,
        kind=kind,
        label=label,
        workspaces=workspaces,
        selection_fields=selection_fields,
        backend_contracts=backend_contracts,
        status=status,
        chart_type=chart_type,
    )


PROJECTIONS: tuple[ProjectionDefinition, ...] = (
    _projection("executive-kpi", "KPI", "Executive KPI", ("COMMAND_EXECUTIVE", "REPORT"), ("company_id", "period", "scenario_id", "comparison_baseline"), ("planning-catalog/1", "planning-comparison/1"), "PARTIAL"),  # noqa: E501
    _projection("variance-waterfall", "WATERFALL", "Variance waterfall", ("BRIDGE_FIRST", "REPORT"), ("company_id", "product_id", "station_id", "period", "scenario_id", "comparison_baseline"), ("planning-comparison/1",), "REGISTERED", "WATERFALL"),  # noqa: E501
    _projection("planning-grid", "GRID", "Planning grid", ("TABLE_FIRST", "REPORT"), ("company_id", "period", "scenario_id", "version_id"), ("planning-catalog/1",), "IMPLEMENTED"),  # noqa: E501
    _projection("hierarchy-drilldown", "HIERARCHY", "Hierarchy drill-down", ("TABLE_FIRST", "GRAPH_FIRST"), ("company_id", "selected_object_id"), ("operations-map/1",), "PARTIAL"),  # noqa: E501
    _projection("movement-network", "NETWORK", "Movement network", ("GRAPH_FIRST", "TIMELINE_FIRST"), ("company_id", "selected_object_id"), ("operations-map/1",), "PARTIAL"),  # noqa: E501
    _projection("operations-map", "MAP", "Operations map", ("GRAPH_FIRST", "TIMELINE_FIRST"), ("company_id",), ("operations-map/1",), "IMPLEMENTED"),  # noqa: E501
    _projection("evidence-table", "TABLE", "Evidence and lineage table", ("TABLE_FIRST", "REPORT"), ("company_id", "selected_object_id", "replay_as_of"), ("workspace/constructions",), "IMPLEMENTED"),  # noqa: E501
    _projection("nyx-context", "TEXT", "NYX governed explanation", ("COMMAND_EXECUTIVE", "REPORT"), ("company_id", "selected_object_id", "period", "scenario_id", "version_id", "replay_as_of"), ("nyx/context",), "PARTIAL"),  # noqa: E501
    _projection("field-input", "FIELD", "Governed field input", ("TABLE_FIRST", "BRIDGE_FIRST"), ("company_id", "selected_object_id", "scenario_id", "version_id"), ("workspace-selection/1",), "REGISTERED"),  # noqa: E501
    _projection("image-evidence", "IMAGE", "Evidence image", ("REPORT", "COMMAND_EXECUTIVE"), ("company_id", "selected_object_id", "replay_as_of"), ("workspace/constructions",), "REGISTERED"),  # noqa: E501
    _projection("action-control", "ACTION", "Governed action control", ("COMMAND_EXECUTIVE", "REPORT"), ("company_id", "selected_object_id", "scenario_id", "version_id"), ("workflow/control",), "REGISTERED"),  # noqa: E501
    _projection("formatted-table", "TABLE", "Formatted report table", ("REPORT",), ("company_id", "period", "scenario_id", "version_id", "comparison_baseline"), ("planning-comparison/1",), "REGISTERED"),  # noqa: E501
    _projection("chart-area", "CHART", "Area chart", ("REPORT", "TIMELINE_FIRST"), ("company_id", "product_id", "period", "scenario_id", "comparison_baseline"), ("planning-comparison/1",), "REGISTERED", "AREA"),  # noqa: E501
    _projection("chart-bar", "CHART", "Bar chart", ("REPORT", "BRIDGE_FIRST"), ("company_id", "product_id", "period", "scenario_id", "comparison_baseline"), ("planning-comparison/1",), "REGISTERED", "BAR"),  # noqa: E501
    _projection("chart-column", "CHART", "Column chart", ("REPORT", "BRIDGE_FIRST"), ("company_id", "product_id", "period", "scenario_id", "comparison_baseline"), ("planning-comparison/1",), "REGISTERED", "COLUMN"),  # noqa: E501
    _projection("chart-combination", "CHART", "Combination chart", ("REPORT", "BRIDGE_FIRST"), ("company_id", "product_id", "period", "scenario_id", "comparison_baseline"), ("planning-comparison/1",), "REGISTERED", "COMBINATION"),  # noqa: E501
    _projection("chart-dot", "CHART", "Dot chart", ("REPORT", "GRAPH_FIRST"), ("company_id", "product_id", "period", "scenario_id", "comparison_baseline"), ("planning-comparison/1",), "REGISTERED", "DOT"),  # noqa: E501
    _projection("chart-gantt", "CHART", "Gantt timeline", ("REPORT", "TIMELINE_FIRST"), ("company_id", "product_id", "period", "scenario_id", "comparison_baseline"), ("planning-comparison/1",), "REGISTERED", "GANTT"),  # noqa: E501
    _projection("chart-line", "CHART", "Line chart", ("REPORT", "TIMELINE_FIRST"), ("company_id", "product_id", "period", "scenario_id", "comparison_baseline"), ("planning-comparison/1",), "REGISTERED", "LINE"),  # noqa: E501
    _projection("chart-pie", "CHART", "Pie chart", ("REPORT", "COMMAND_EXECUTIVE"), ("company_id", "product_id", "period", "scenario_id", "comparison_baseline"), ("planning-comparison/1",), "REGISTERED", "PIE"),  # noqa: E501
    _projection("chart-scatter", "CHART", "Scatter plot", ("REPORT", "GRAPH_FIRST"), ("company_id", "product_id", "period", "scenario_id", "comparison_baseline"), ("planning-comparison/1",), "REGISTERED", "SCATTER"),  # noqa: E501
    _projection("chart-bubble", "CHART", "Bubble chart", ("REPORT", "GRAPH_FIRST"), ("company_id", "product_id", "period", "scenario_id", "comparison_baseline"), ("planning-comparison/1",), "REGISTERED", "BUBBLE"),  # noqa: E501
)


def projection_catalog() -> list[dict[str, object]]:
    return [item.model_dump(mode="json") for item in PROJECTIONS]


def eligible_projections(selection: WorkspaceSelection) -> list[dict[str, object]]:
    """Return projections whose declared context is present in the selection."""

    values = selection.model_dump(exclude_none=True)
    result: list[dict[str, object]] = []
    for item in PROJECTIONS:
        if selection.workspace is not None and selection.workspace not in item.workspaces:
            continue
        if all(field in values for field in item.selection_fields):
            result.append(item.model_dump(mode="json"))
    return result
