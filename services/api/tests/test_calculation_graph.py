from decimal import Decimal

from finai_api.domain.calculation_graph import (
    CalculationGraph,
    CalculationNode,
    evaluate_decimal_graph,
    plan_calculation,
)


def graph() -> CalculationGraph:
    return CalculationGraph(
        graph_id="margin",
        version="1",
        nodes=(
            CalculationNode(node_id="revenue", function_id="identity"),
            CalculationNode(node_id="cost", function_id="identity"),
            CalculationNode(
                node_id="margin",
                function_id="subtract",
                depends_on=("revenue", "cost"),
            ),
        ),
    )


def test_topological_plan_selects_only_dirty_downstream_closure() -> None:
    plan = plan_calculation(graph(), ("cost",))
    assert plan.topological_order == ("cost", "revenue", "margin")
    assert plan.selected_nodes == ("cost", "margin")


def test_decimal_evaluation_is_deterministic() -> None:
    result = evaluate_decimal_graph(
        graph(),
        {"revenue": Decimal("100.10"), "cost": Decimal("40.05")},
        {"identity": lambda value: value, "subtract": lambda left, right: left - right},
    )
    assert result.values[-1] == ("revenue", "100.10")
    assert dict(result.values)["margin"] == "60.05"


def test_unknown_dependency_and_cycle_are_refused() -> None:
    unknown = CalculationGraph(
        graph_id="bad",
        version="1",
        nodes=(CalculationNode(node_id="a", function_id="x", depends_on=("missing",)),),
    )
    assert plan_calculation(unknown).refused
    cycle = CalculationGraph(
        graph_id="cycle",
        version="1",
        nodes=(
            CalculationNode(node_id="a", function_id="x", depends_on=("b",)),
            CalculationNode(node_id="b", function_id="x", depends_on=("a",)),
        ),
    )
    assert plan_calculation(cycle).refused
