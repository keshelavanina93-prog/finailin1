"""Compiled sparse multidimensional calculation runtime.

The runtime is intentionally deterministic and side-effect free. It executes
trusted domain evaluators over populated enterprise coordinates; it does not
promote accounting facts, call external systems, or infer missing cells.
"""

from __future__ import annotations

import json
from collections import defaultdict, deque
from collections.abc import Callable, Mapping
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, model_validator

from finai_api.domain.calculation_graph import CalculationGraph, CalculationNode


class CalculationShape(StrEnum):
    ONE_TO_ONE = "ONE_TO_ONE"
    MANY_TO_ONE = "MANY_TO_ONE"
    ONE_TO_MANY = "ONE_TO_MANY"
    MANY_TO_MANY = "MANY_TO_MANY"


class TransformType(StrEnum):
    DIRECT = "DIRECT"
    MAP = "MAP"
    LOOKUP = "LOOKUP"
    AGGREGATE = "AGGREGATE"
    ALLOCATE = "ALLOCATE"
    SPREAD = "SPREAD"
    COHORT_SHIFT = "COHORT_SHIFT"
    ROLL_FORWARD = "ROLL_FORWARD"
    LAG = "LAG"
    LEAD = "LEAD"
    CONVERT_CURRENCY = "CONVERT_CURRENCY"
    CONVERT_UNIT = "CONVERT_UNIT"
    RECONCILE = "RECONCILE"
    BRIDGE = "BRIDGE"


class AggregationPolicy(StrEnum):
    SUM = "SUM"
    LAST_VALID = "LAST_VALID"
    WEIGHTED_AVERAGE = "WEIGHTED_AVERAGE"
    RATIO = "RATIO"


class TimeOperator(StrEnum):
    PREVIOUS_PERIOD = "PREVIOUS_PERIOD"
    NEXT_PERIOD = "NEXT_PERIOD"
    OPENING = "OPENING"
    CLOSING = "CLOSING"
    YTD = "YTD"
    QTD = "QTD"
    ROLLING_N = "ROLLING_N"
    LAG = "LAG"
    LEAD = "LEAD"
    COHORT_AGE = "COHORT_AGE"
    ACTUAL_FORECAST_CUTOVER = "ACTUAL_FORECAST_CUTOVER"


class RuntimeState(StrEnum):
    CALCULATION_FRESH = "CALCULATION_FRESH"
    DIRTY = "DIRTY"
    RECALCULATING = "RECALCULATING"
    BLOCKED = "BLOCKED"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"
    FAILED = "FAILED"


class DimensionalSignature(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    signature_id: str = Field(min_length=1)
    required_dimensions: tuple[str, ...] = ()
    optional_dimensions: tuple[str, ...] = ()
    forbidden_dimensions: tuple[str, ...] = ()
    ordered_execution_dimensions: tuple[str, ...] = ()
    hierarchy_refs: tuple[str, ...] = ()
    expected_cardinality: int | None = Field(default=None, ge=0)
    sparsity_policy: str = "POPULATED_ONLY"
    grain_policy: str = "EXACT"

    @model_validator(mode="after")
    def validate_dimensions(self) -> DimensionalSignature:
        groups = (
            self.required_dimensions,
            self.optional_dimensions,
            self.forbidden_dimensions,
        )
        if any(len(set(group)) != len(group) for group in groups):
            raise ValueError("Dimensional signature dimensions must be unique")
        if set(self.required_dimensions) & set(self.forbidden_dimensions):
            raise ValueError("A dimension cannot be both required and forbidden")
        if set(self.ordered_execution_dimensions) - set(
            self.required_dimensions + self.optional_dimensions
        ):
            raise ValueError("Execution dimensions must be declared dimensions")
        return self


class Coordinate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    values: tuple[tuple[str, str], ...] = ()

    @model_validator(mode="after")
    def validate_values(self) -> Coordinate:
        names = tuple(name for name, _ in self.values)
        if len(set(names)) != len(names):
            raise ValueError("Coordinate dimensions must be unique")
        if any(not name or not value for name, value in self.values):
            raise ValueError("Coordinate dimension names and values are required")
        return self

    @property
    def mapping(self) -> dict[str, str]:
        return dict(self.values)


class IntersectionSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    intersection_set_id: str = Field(min_length=1)
    dimensional_signature_id: str = Field(min_length=1)
    populated_coordinates: tuple[Coordinate, ...] = ()
    generation_source: str = Field(min_length=1)
    scenario_scope: tuple[tuple[str, str], ...] = ()
    valid_range: tuple[str, str] | None = None
    generation_reason: str = Field(min_length=1)


class DimensionMappingRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_dimension: str = Field(min_length=1)
    target_dimension: str = Field(min_length=1)
    value_map: tuple[tuple[str, str], ...] = ()
    allow_unmapped: bool = False


class DimensionMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mapping_id: str = Field(min_length=1)
    rules: tuple[DimensionMappingRule, ...] = ()
    shape: CalculationShape = CalculationShape.ONE_TO_ONE


class HierarchyDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    hierarchy_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    child_dimension: str = Field(min_length=1)
    parent_dimension: str = Field(min_length=1)
    valid_from: str
    valid_to: str | None = None
    known_at: str


class HierarchyMembership(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    hierarchy_id: str = Field(min_length=1)
    child_value: str = Field(min_length=1)
    parent_value: str = Field(min_length=1)
    valid_from: str
    valid_to: str | None = None
    known_at: str


class TransformDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    transform_id: str = Field(min_length=1)
    transform_type: TransformType
    source_signature_id: str = Field(min_length=1)
    target_signature_id: str = Field(min_length=1)
    dimension_mapping_id: str | None = None
    aggregation_policy: AggregationPolicy | None = None
    allocation_driver: str | None = None
    time_operator: TimeOperator | None = None
    time_offset: int = Field(default=1, ge=1, le=120)
    null_behavior: str = "BLOCK"
    missing_behavior: str = "BLOCK"
    implementation_id: str = Field(min_length=1)


class CalculationBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    block_id: str = Field(min_length=1)
    dimensional_signature_id: str = Field(min_length=1)
    ordered_dimensions: tuple[str, ...] = ()
    fact_definitions: tuple[str, ...] = ()
    calculation_node_ids: tuple[str, ...] = ()
    sparse_intersection_set_id: str = Field(min_length=1)
    storage_policy: str = "SPARSE"
    materialization_policy: str = "ON_DEMAND"
    partition_key: tuple[str, ...] = ()
    execution_shape: CalculationShape = CalculationShape.ONE_TO_ONE


class CompiledCalculationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    graph_id: str
    graph_version: str
    selected_node_ids: tuple[str, ...]
    stages: tuple[tuple[str, ...], ...]
    affected_coordinates: tuple[Coordinate, ...]
    block_ids: tuple[str, ...]
    state: RuntimeState
    plan_hash: str
    refusal_reason: str | None = None


class SparseCell(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    coordinate: Coordinate
    value: str


class SparseCalculationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan: CompiledCalculationPlan
    cells: tuple[SparseCell, ...]
    state: RuntimeState
    target: str = "UNSPECIFIED"
    input_pins: tuple[str, ...] = ()
    valid_at: str | None = None
    known_at: str | None = None
    authority_state: str = "DERIVED_CANDIDATE"
    accounting_authorized: bool = False
    business_effect_authorized: bool = False
    reproducibility_hash: str
    refusal_reason: str | None = None


def compile_sparse_plan(
    graph: CalculationGraph,
    signatures: tuple[DimensionalSignature, ...],
    blocks: tuple[CalculationBlock, ...],
    intersections: tuple[IntersectionSet, ...],
    changed_nodes: tuple[str, ...] = (),
    changed_coordinates: tuple[Coordinate, ...] = (),
) -> CompiledCalculationPlan:
    """Compile graph stages and exact affected sparse coordinates."""

    signature_by_id = {item.signature_id: item for item in signatures}
    intersection_by_id = {item.intersection_set_id: item for item in intersections}
    if (
        len(signature_by_id) != len(signatures)
        or len(intersection_by_id) != len(intersections)
        or len({item.block_id for item in blocks}) != len(blocks)
    ):
        return _refused_plan(graph, "Duplicate dimensional identity")
    for block in blocks:
        signature = signature_by_id.get(block.dimensional_signature_id)
        intersection = intersection_by_id.get(block.sparse_intersection_set_id)
        if signature is None or intersection is None:
            return _refused_plan(
                graph, f"Block {block.block_id} has an unknown signature or intersection"
            )
        if intersection.dimensional_signature_id != signature.signature_id:
            return _refused_plan(graph, f"Block {block.block_id} signature/intersection mismatch")
    base = _graph_plan(graph, changed_nodes)
    if base is None:
        return _refused_plan(graph, "Calculation graph cannot be topologically planned")
    selected = tuple(item for item in base if not changed_nodes or item in base)
    selected_set = set(selected)
    selected_blocks = tuple(
        block
        for block in sorted(blocks, key=lambda item: item.block_id)
        if selected_set & set(block.calculation_node_ids)
    )
    coordinates = _affected_coordinates(selected_blocks, intersection_by_id, changed_coordinates)
    stages = _stages(graph.nodes, selected)
    return CompiledCalculationPlan(
        graph_id=graph.graph_id,
        graph_version=graph.version,
        selected_node_ids=selected,
        stages=stages,
        affected_coordinates=coordinates,
        block_ids=tuple(block.block_id for block in selected_blocks),
        state=RuntimeState.DIRTY
        if changed_nodes or changed_coordinates
        else RuntimeState.RECALCULATING,
        plan_hash=_plan_hash(
            graph.graph_id,
            graph.version,
            selected,
            stages,
            coordinates,
            tuple(block.block_id for block in selected_blocks),
        ),
    )


def execute_sparse_decimal_plan(
    plan: CompiledCalculationPlan,
    graph: CalculationGraph,
    values: Mapping[tuple[str, Coordinate], Decimal],
    evaluators: Mapping[str, Callable[..., Decimal]],
    *,
    target: str = "UNSPECIFIED",
    input_pins: tuple[str, ...] = (),
    valid_at: str | None = None,
    known_at: str | None = None,
) -> SparseCalculationResult:
    """Execute a compiled plan over populated coordinates using trusted callables."""

    if plan.state is RuntimeState.BLOCKED or plan.refusal_reason:
        return SparseCalculationResult(
            plan=plan,
            cells=_cells(values),
            state=RuntimeState.BLOCKED,
            target=target,
            input_pins=input_pins,
            valid_at=valid_at,
            known_at=known_at,
            reproducibility_hash=_result_hash(plan, target, input_pins, valid_at, known_at, values),
            refusal_reason=plan.refusal_reason,
        )
    nodes = {node.node_id: node for node in graph.nodes}
    result = dict(values)
    coordinates = plan.affected_coordinates
    for stage in plan.stages:
        for node_id in stage:
            node = nodes[node_id]
            for coordinate in coordinates:
                key = (node_id, coordinate)
                if not node.depends_on and key in result:
                    continue
                evaluator = evaluators.get(node.function_id)
                if not callable(evaluator):
                    return _execution_refusal(
                        plan,
                        result,
                        f"No evaluator registered: {node.function_id}",
                        target=target,
                        input_pins=input_pins,
                        valid_at=valid_at,
                        known_at=known_at,
                    )
                try:
                    dependency_values = [
                        result[(dependency, coordinate)] for dependency in node.depends_on
                    ]
                    value = evaluator(*dependency_values)
                except (KeyError, TypeError, ValueError) as exc:
                    return _execution_refusal(
                        plan,
                        result,
                        f"Evaluation failed for {node_id}: {exc}",
                        target=target,
                        input_pins=input_pins,
                        valid_at=valid_at,
                        known_at=known_at,
                    )
                if not isinstance(value, Decimal) or not value.is_finite():
                    return _execution_refusal(
                        plan,
                        result,
                        f"Non-finite Decimal output for {node_id}",
                        target=target,
                        input_pins=input_pins,
                        valid_at=valid_at,
                        known_at=known_at,
                    )
                result[key] = value
    finished = plan.model_copy(update={"state": RuntimeState.CALCULATION_FRESH})
    return SparseCalculationResult(
        plan=finished,
        cells=_cells(result),
        state=RuntimeState.CALCULATION_FRESH,
        target=target,
        input_pins=input_pins,
        valid_at=valid_at,
        known_at=known_at,
        reproducibility_hash=_result_hash(finished, target, input_pins, valid_at, known_at, result),
    )


def map_coordinate(coordinate: Coordinate, mapping: DimensionMapping) -> Coordinate:
    """Apply explicit dimension/value mappings without inventing unmapped values."""

    mapped = coordinate.mapping
    for rule in mapping.rules:
        if rule.source_dimension not in mapped:
            continue
        value = dict(rule.value_map).get(mapped[rule.source_dimension])
        if value is None:
            if not rule.allow_unmapped:
                raise ValueError(f"Unmapped value for {rule.source_dimension}")
            value = mapped[rule.source_dimension]
        mapped[rule.target_dimension] = value
        if rule.target_dimension != rule.source_dimension:
            mapped.pop(rule.source_dimension, None)
    return Coordinate(values=tuple(sorted(mapped.items())))


def aggregate_sparse_values(
    cells: Mapping[Coordinate, Decimal],
    target_dimensions: frozenset[str],
    *,
    policy: AggregationPolicy = AggregationPolicy.SUM,
    weights: Mapping[Coordinate, Decimal] | None = None,
) -> dict[Coordinate, Decimal]:
    """Aggregate at a declared grain using financial, not visual, semantics."""

    grouped: defaultdict[tuple[tuple[str, str], ...], list[tuple[Coordinate, Decimal]]] = (
        defaultdict(list)
    )
    for coordinate, value in cells.items():
        target = tuple(
            sorted((name, item) for name, item in coordinate.values if name in target_dimensions)
        )
        grouped[target].append((coordinate, value))
    result: dict[Coordinate, Decimal] = {}
    for key, items in sorted(grouped.items()):
        if policy is AggregationPolicy.SUM:
            result[Coordinate(values=key)] = sum((value for _, value in items), Decimal(0))
        elif policy is AggregationPolicy.LAST_VALID:
            result[Coordinate(values=key)] = max(items, key=lambda item: item[0].values)[1]
        elif policy is AggregationPolicy.WEIGHTED_AVERAGE:
            if weights is None:
                raise ValueError("Weights are required for weighted average")
            denominator = sum(
                (weights.get(coordinate, Decimal(0)) for coordinate, _ in items), Decimal(0)
            )
            if denominator == 0:
                raise ValueError("Weighted average has a zero denominator")
            result[Coordinate(values=key)] = (
                sum(
                    (value * weights.get(coordinate, Decimal(0)) for coordinate, value in items),
                    Decimal(0),
                )
                / denominator
            )
        else:
            raise ValueError(
                "RATIO aggregation requires an explicit numerator/denominator contract"
            )
    return result


def execute_transform(
    transform: TransformDefinition,
    cells: Mapping[Coordinate, Decimal],
    *,
    mapping: DimensionMapping | None = None,
    target_dimensions: frozenset[str] | None = None,
    conversion_factors: Mapping[Coordinate, Decimal] | None = None,
    weights: Mapping[Coordinate, Decimal] | None = None,
) -> dict[Coordinate, Decimal]:
    """Execute safe transforms with explicit refusal for unregistered operators."""

    if transform.transform_type is TransformType.DIRECT:
        return dict(cells)
    if transform.transform_type in {TransformType.MAP, TransformType.LOOKUP}:
        if mapping is None:
            raise ValueError("Dimension mapping is required for this transform")
        return {map_coordinate(coordinate, mapping): value for coordinate, value in cells.items()}
    if transform.transform_type is TransformType.AGGREGATE:
        if target_dimensions is None:
            raise ValueError("Target dimensions are required for aggregation")
        return aggregate_sparse_values(
            cells,
            target_dimensions,
            policy=transform.aggregation_policy or AggregationPolicy.SUM,
            weights=weights,
        )
    if transform.transform_type in {TransformType.CONVERT_UNIT, TransformType.CONVERT_CURRENCY}:
        if conversion_factors is None:
            raise ValueError("Conversion factors are required for this transform")
        converted: dict[Coordinate, Decimal] = {}
        for coordinate, value in cells.items():
            factor = conversion_factors.get(coordinate)
            if factor is None or not factor.is_finite():
                raise ValueError("Conversion factor is missing or non-finite")
            converted[coordinate] = value * factor
        return converted
    if transform.transform_type in {
        TransformType.LAG,
        TransformType.LEAD,
        TransformType.COHORT_SHIFT,
    }:
        direction = -1 if transform.transform_type is TransformType.LAG else 1
        return {
            _shift_period(coordinate, direction * transform.time_offset): value
            for coordinate, value in cells.items()
        }
    raise ValueError(
        f"Transform implementation is not registered: {transform.transform_type.value}"
    )


def resolve_hierarchy_parent(
    hierarchy: HierarchyDefinition,
    memberships: tuple[HierarchyMembership, ...],
    child_value: str,
    *,
    valid_at: str,
    replay_as_of: str,
) -> str:
    """Resolve a parent using both economic time and knowledge cut-off."""

    target_time = _parse_time(valid_at)
    as_of = _parse_time(replay_as_of)
    candidates = [
        item
        for item in memberships
        if item.hierarchy_id == hierarchy.hierarchy_id
        and item.child_value == child_value
        and _parse_time(item.known_at) <= as_of
        and _parse_time(item.valid_from) <= target_time
        and (item.valid_to is None or target_time < _parse_time(item.valid_to))
    ]
    if not candidates:
        raise ValueError("No hierarchy membership is valid at the requested replay point")
    latest_known = max(_parse_time(item.known_at) for item in candidates)
    resolved = [item for item in candidates if _parse_time(item.known_at) == latest_known]
    parents = {item.parent_value for item in resolved}
    if len(parents) != 1:
        raise ValueError("Hierarchy membership is ambiguous at the requested replay point")
    return next(iter(parents))


def aggregate_by_hierarchy(
    cells: Mapping[Coordinate, Decimal],
    hierarchy: HierarchyDefinition,
    memberships: tuple[HierarchyMembership, ...],
    *,
    valid_at: str,
    replay_as_of: str,
) -> dict[Coordinate, Decimal]:
    """Aggregate through a versioned hierarchy without using current membership."""

    result: dict[Coordinate, Decimal] = {}
    for coordinate, value in cells.items():
        values = coordinate.mapping
        child_value = values.get(hierarchy.child_dimension)
        if child_value is None:
            raise ValueError("Hierarchy child dimension is missing from coordinate")
        values[hierarchy.parent_dimension] = resolve_hierarchy_parent(
            hierarchy,
            memberships,
            child_value,
            valid_at=valid_at,
            replay_as_of=replay_as_of,
        )
        values.pop(hierarchy.child_dimension, None)
        target = Coordinate(values=tuple(sorted(values.items())))
        result[target] = result.get(target, Decimal(0)) + value
    return result


def _parse_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Temporal runtime values must be ISO timestamps") from exc


def _shift_period(coordinate: Coordinate, months: int) -> Coordinate:
    values = coordinate.mapping
    period = values.get("period")
    if period is None or len(period) != 7 or period[4] != "-":
        raise ValueError("Time transforms require a YYYY-MM period coordinate")
    try:
        year, month = int(period[:4]), int(period[5:])
        absolute = year * 12 + month - 1 + months
        values["period"] = f"{absolute // 12:04d}-{absolute % 12 + 1:02d}"
    except ValueError as exc:
        raise ValueError("Time transforms require a valid YYYY-MM period") from exc
    return Coordinate(values=tuple(sorted(values.items())))


def _graph_plan(graph: CalculationGraph, changed_nodes: tuple[str, ...]) -> tuple[str, ...] | None:
    nodes = {node.node_id: node for node in graph.nodes}
    if len(nodes) != len(graph.nodes) or any(
        dependency not in nodes for node in graph.nodes for dependency in node.depends_on
    ):
        return None
    if any(node_id not in nodes for node_id in changed_nodes):
        return None
    indegree = {node_id: len(node.depends_on) for node_id, node in nodes.items()}
    dependents: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    for node in nodes.values():
        for dependency in node.depends_on:
            dependents[dependency].append(node.node_id)
    queue = deque(sorted(node_id for node_id, degree in indegree.items() if degree == 0))
    order: list[str] = []
    while queue:
        node_id = queue.popleft()
        order.append(node_id)
        for dependent in sorted(dependents[node_id]):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                queue.append(dependent)
    if len(order) != len(nodes):
        return None
    if not changed_nodes:
        return tuple(order)
    dirty = set(changed_nodes)
    queue = deque(changed_nodes)
    while queue:
        node_id = queue.popleft()
        for dependent in dependents[node_id]:
            if dependent not in dirty:
                dirty.add(dependent)
                queue.append(dependent)
    return tuple(node_id for node_id in order if node_id in dirty)


def _stages(
    nodes: tuple[CalculationNode, ...], selected: tuple[str, ...]
) -> tuple[tuple[str, ...], ...]:
    remaining = set(selected)
    by_id = {node.node_id: node for node in nodes}
    stages: list[tuple[str, ...]] = []
    while remaining:
        stage = tuple(
            sorted(
                node_id for node_id in remaining if not (set(by_id[node_id].depends_on) & remaining)
            )
        )
        if not stage:
            return ()
        stages.append(stage)
        remaining.difference_update(stage)
    return tuple(stages)


def _affected_coordinates(
    blocks: tuple[CalculationBlock, ...],
    intersections: Mapping[str, IntersectionSet],
    changed: tuple[Coordinate, ...],
) -> tuple[Coordinate, ...]:
    coordinates = {
        coordinate
        for block in blocks
        for coordinate in intersections[block.sparse_intersection_set_id].populated_coordinates
        if not changed or any(_coordinate_intersects(coordinate, item) for item in changed)
    }
    return tuple(sorted(coordinates, key=lambda item: item.values))


def _coordinate_intersects(left: Coordinate, right: Coordinate) -> bool:
    left_values, right_values = left.mapping, right.mapping
    return all(
        left_values.get(name) in (None, value) for name, value in right_values.items()
    ) and all(right_values.get(name) in (None, value) for name, value in left_values.items())


def _cells(values: Mapping[tuple[str, Coordinate], Decimal]) -> tuple[SparseCell, ...]:
    return tuple(
        SparseCell(node_id=node_id, coordinate=coordinate, value=format(value, "f"))
        for (node_id, coordinate), value in sorted(
            values.items(), key=lambda item: (item[0][0], item[0][1].values)
        )
    )


def _refused_plan(graph: CalculationGraph, reason: str) -> CompiledCalculationPlan:
    return CompiledCalculationPlan(
        graph_id=graph.graph_id,
        graph_version=graph.version,
        selected_node_ids=(),
        stages=(),
        affected_coordinates=(),
        block_ids=(),
        state=RuntimeState.BLOCKED,
        plan_hash=_plan_hash(graph.graph_id, graph.version, (), (), (), ()),
        refusal_reason=reason,
    )


def _execution_refusal(
    plan: CompiledCalculationPlan,
    values: Mapping[tuple[str, Coordinate], Decimal],
    reason: str,
    *,
    target: str,
    input_pins: tuple[str, ...],
    valid_at: str | None,
    known_at: str | None,
) -> SparseCalculationResult:
    blocked = plan.model_copy(update={"state": RuntimeState.BLOCKED, "refusal_reason": reason})
    return SparseCalculationResult(
        plan=blocked,
        cells=_cells(values),
        state=RuntimeState.BLOCKED,
        target=target,
        input_pins=input_pins,
        valid_at=valid_at,
        known_at=known_at,
        reproducibility_hash=_result_hash(blocked, target, input_pins, valid_at, known_at, values),
        refusal_reason=reason,
    )


def _plan_hash(
    graph_id: str,
    graph_version: str,
    selected: tuple[str, ...],
    stages: tuple[tuple[str, ...], ...],
    coordinates: tuple[Coordinate, ...],
    blocks: tuple[str, ...],
) -> str:
    material = {
        "graph_id": graph_id,
        "graph_version": graph_version,
        "selected": selected,
        "stages": stages,
        "coordinates": [coordinate.values for coordinate in coordinates],
        "blocks": blocks,
    }
    return sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _result_hash(
    plan: CompiledCalculationPlan,
    target: str,
    input_pins: tuple[str, ...],
    valid_at: str | None,
    known_at: str | None,
    values: Mapping[tuple[str, Coordinate], Decimal],
) -> str:
    material = {
        "plan_hash": plan.plan_hash,
        "target": target,
        "input_pins": input_pins,
        "valid_at": valid_at,
        "known_at": known_at,
        "values": [
            (node_id, coordinate.values, format(value, "f"))
            for (node_id, coordinate), value in sorted(
                values.items(), key=lambda item: (item[0][0], item[0][1].values)
            )
        ],
    }
    return sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


__all__: Final = [
    "AggregationPolicy",
    "CalculationBlock",
    "CalculationShape",
    "CompiledCalculationPlan",
    "Coordinate",
    "DimensionMapping",
    "DimensionMappingRule",
    "DimensionalSignature",
    "HierarchyDefinition",
    "HierarchyMembership",
    "IntersectionSet",
    "RuntimeState",
    "SparseCalculationResult",
    "TimeOperator",
    "TransformDefinition",
    "TransformType",
    "aggregate_by_hierarchy",
    "aggregate_sparse_values",
    "compile_sparse_plan",
    "execute_sparse_decimal_plan",
    "execute_transform",
    "map_coordinate",
    "resolve_hierarchy_parent",
]
