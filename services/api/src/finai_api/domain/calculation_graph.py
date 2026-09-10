"""Deterministic sparse calculation-graph planning for governed facts.

This is the scheduling layer beneath executable enterprise functions. It
does not decide accounting authority and it does not execute external effects.
Nodes identify enterprise fact coordinates; values and formulas are supplied
by the owning domain engine.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class CalculationNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str = Field(min_length=1)
    function_id: str = Field(min_length=1)
    depends_on: tuple[str, ...] = ()
    coordinate: tuple[tuple[str, str], ...] = ()


class CalculationGraph(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    graph_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    nodes: tuple[CalculationNode, ...] = ()


class CalculationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    graph_id: str
    graph_version: str
    topological_order: tuple[str, ...]
    selected_nodes: tuple[str, ...]
    dirty_inputs: tuple[str, ...]
    refused: bool = False
    refusal_reason: str | None = None


class CalculationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan: CalculationPlan
    values: tuple[tuple[str, str], ...]


def plan_calculation(
    graph: CalculationGraph, changed_nodes: tuple[str, ...] = ()
) -> CalculationPlan:
    """Create a deterministic full or incremental topological execution plan."""

    nodes = {node.node_id: node for node in graph.nodes}
    if len(nodes) != len(graph.nodes):
        return _refused(graph, changed_nodes, "Duplicate calculation node identity")
    unknown = sorted(
        {
            dependency
            for node in graph.nodes
            for dependency in node.depends_on
            if dependency not in nodes
        }
    )
    if unknown:
        return _refused(graph, changed_nodes, f"Unknown dependency node: {unknown[0]}")
    order, cycle = _topological_order(nodes)
    if cycle:
        return _refused(graph, changed_nodes, f"Calculation cycle detected: {' -> '.join(cycle)}")
    changed = tuple(dict.fromkeys(changed_nodes))
    unknown_changed = sorted(set(changed) - nodes.keys())
    if unknown_changed:
        return _refused(graph, changed, f"Changed node is not in graph: {unknown_changed[0]}")
    selected = order if not changed else tuple(_dirty_closure(nodes, changed, order))
    return CalculationPlan(
        graph_id=graph.graph_id,
        graph_version=graph.version,
        topological_order=tuple(order),
        selected_nodes=tuple(selected),
        dirty_inputs=changed,
    )


def evaluate_decimal_graph(
    graph: CalculationGraph,
    values: Mapping[str, Decimal],
    evaluators: Mapping[str, Callable[..., Decimal]],
    changed_nodes: tuple[str, ...] = (),
) -> CalculationResult:
    """Evaluate selected nodes using explicit Decimal functions.

    Evaluators are intentionally passed by the owning service rather than
    deserialized from user input. Each callable receives dependency values in
    declared order and returns a finite Decimal.
    """

    plan = plan_calculation(graph, changed_nodes)
    if plan.refused:
        return CalculationResult(
            plan=plan,
            values=tuple(sorted((key, str(value)) for key, value in values.items())),
        )
    result = dict(values)
    nodes = {node.node_id: node for node in graph.nodes}
    for node_id in plan.selected_nodes:
        node = nodes[node_id]
        if not node.depends_on and node_id in result:
            continue
        evaluator = evaluators.get(node.function_id)
        if not callable(evaluator):
            refused = plan.model_copy(
                update={
                    "refused": True,
                    "refusal_reason": f"No evaluator registered: {node.function_id}",
                }
            )
            return CalculationResult(
                plan=refused,
                values=tuple(sorted((key, str(value)) for key, value in result.items())),
            )
        try:
            dependency_values = [result[dependency] for dependency in node.depends_on]
            value = evaluator(*dependency_values)
        except (KeyError, TypeError, ValueError) as exc:
            refused = plan.model_copy(
                update={
                    "refused": True,
                    "refusal_reason": f"Evaluation failed for {node_id}: {exc}",
                }
            )
            return CalculationResult(
                plan=refused,
                values=tuple(sorted((key, str(value)) for key, value in result.items())),
            )
        if not isinstance(value, Decimal) or not value.is_finite():
            refused = plan.model_copy(
                update={
                    "refused": True,
                    "refusal_reason": f"Evaluator returned a non-finite Decimal for {node_id}",
                }
            )
            return CalculationResult(
                plan=refused,
                values=tuple(sorted((key, str(value)) for key, value in result.items())),
            )
        result[node_id] = value
    return CalculationResult(
        plan=plan,
        values=tuple(sorted((key, str(value)) for key, value in result.items())),
    )


def _topological_order(nodes: Mapping[str, CalculationNode]) -> tuple[list[str], tuple[str, ...]]:
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
    if len(order) == len(nodes):
        return order, ()
    remaining = tuple(sorted(node_id for node_id, degree in indegree.items() if degree > 0))
    return order, remaining


def _dirty_closure(
    nodes: Mapping[str, CalculationNode], changed: tuple[str, ...], order: list[str]
) -> list[str]:
    dependents: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    for node in nodes.values():
        for dependency in node.depends_on:
            dependents[dependency].append(node.node_id)
    dirty = set(changed)
    queue = deque(changed)
    while queue:
        node_id = queue.popleft()
        for dependent in dependents[node_id]:
            if dependent not in dirty:
                dirty.add(dependent)
                queue.append(dependent)
    return [node_id for node_id in order if node_id in dirty]


def _refused(
    graph: CalculationGraph, changed: tuple[str, ...], reason: str
) -> CalculationPlan:
    return CalculationPlan(
        graph_id=graph.graph_id,
        graph_version=graph.version,
        topological_order=(),
        selected_nodes=(),
        dirty_inputs=changed,
        refused=True,
        refusal_reason=reason,
    )
