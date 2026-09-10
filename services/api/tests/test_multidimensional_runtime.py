from decimal import Decimal

from finai_api.domain.calculation_graph import CalculationGraph, CalculationNode
from finai_api.domain.multidimensional_runtime import (
    CalculationBlock,
    Coordinate,
    DimensionalSignature,
    DimensionMapping,
    DimensionMappingRule,
    IntersectionSet,
    RuntimeState,
    aggregate_sparse_values,
    compile_sparse_plan,
    execute_sparse_decimal_plan,
    map_coordinate,
)


def coordinate(station: str) -> Coordinate:
    return Coordinate(
        values=(
            ("company", "SGP"),
            ("period", "2026-09"),
            ("station", station),
        )
    )


def runtime_fixture() -> tuple[
    CalculationGraph,
    tuple[DimensionalSignature, ...],
    tuple[CalculationBlock, ...],
    tuple[IntersectionSet, ...],
]:
    graph = CalculationGraph(
        graph_id="petroleum-daily-economics",
        version="1",
        nodes=(
            CalculationNode(node_id="revenue", function_id="source"),
            CalculationNode(node_id="cogs", function_id="source"),
            CalculationNode(
                node_id="margin", function_id="subtract", depends_on=("revenue", "cogs")
            ),
        ),
    )
    signature = DimensionalSignature(
        signature_id="company-station-period",
        required_dimensions=("company", "station", "period"),
        ordered_execution_dimensions=("company", "station", "period"),
    )
    intersection = IntersectionSet(
        intersection_set_id="petroleum-populated",
        dimensional_signature_id=signature.signature_id,
        populated_coordinates=(coordinate("024"), coordinate("025")),
        generation_source="accepted_operational_facts",
        generation_reason="Observed revenue and COGS cells",
    )
    block = CalculationBlock(
        block_id="petroleum-margin",
        dimensional_signature_id=signature.signature_id,
        ordered_dimensions=signature.ordered_execution_dimensions,
        calculation_node_ids=("revenue", "cogs", "margin"),
        sparse_intersection_set_id=intersection.intersection_set_id,
    )
    return graph, (signature,), (block,), (intersection,)


def test_compile_selects_only_changed_sparse_coordinates_and_stages() -> None:
    graph, signatures, blocks, intersections = runtime_fixture()
    plan = compile_sparse_plan(
        graph,
        signatures,
        blocks,
        intersections,
        changed_nodes=("revenue",),
        changed_coordinates=(coordinate("024"),),
    )
    assert plan.state is RuntimeState.DIRTY
    assert plan.selected_node_ids == ("revenue", "margin")
    assert plan.stages == (("revenue",), ("margin",))
    assert plan.affected_coordinates == (coordinate("024"),)


def test_sparse_decimal_execution_preserves_coordinate_and_refreshes_only_cell() -> None:
    graph, signatures, blocks, intersections = runtime_fixture()
    plan = compile_sparse_plan(graph, signatures, blocks, intersections)
    cells = {
        ("revenue", coordinate("024")): Decimal("100.10"),
        ("cogs", coordinate("024")): Decimal("40.05"),
        ("revenue", coordinate("025")): Decimal("80"),
        ("cogs", coordinate("025")): Decimal("30"),
    }
    result = execute_sparse_decimal_plan(
        plan,
        graph,
        cells,
        {"subtract": lambda left, right: left - right},
        target="ReplacementMargin",
        input_pins=("revenue:2026-09", "cogs:2026-09"),
        valid_at="2026-09-30T23:59:59+00:00",
        known_at="2026-10-01T08:00:00+00:00",
    )
    values = {(cell.node_id, cell.coordinate): cell.value for cell in result.cells}
    assert result.state is RuntimeState.CALCULATION_FRESH
    assert result.authority_state == "DERIVED_CANDIDATE"
    assert result.accounting_authorized is False
    assert result.plan.plan_hash
    assert result.reproducibility_hash
    assert result.input_pins == ("revenue:2026-09", "cogs:2026-09")
    assert values[("margin", coordinate("024"))] == "60.05"
    assert values[("margin", coordinate("025"))] == "50"


def test_mapping_and_sum_aggregation_are_explicit_and_deterministic() -> None:
    mapped = map_coordinate(
        Coordinate(values=(("station", "024"), ("product", "DIESEL"))),
        DimensionMapping(
            mapping_id="station-region",
            rules=(
                DimensionMappingRule(
                    source_dimension="station",
                    target_dimension="region",
                    value_map=(("024", "TBILISI"),),
                ),
            ),
        ),
    )
    assert mapped.values == (("product", "DIESEL"), ("region", "TBILISI"))
    aggregated = aggregate_sparse_values(
        {
            Coordinate(values=(("region", "TBILISI"), ("station", "024"))): Decimal("10.10"),
            Coordinate(values=(("region", "TBILISI"), ("station", "025"))): Decimal("4.05"),
        },
        frozenset({"region"}),
    )
    assert aggregated[Coordinate(values=(("region", "TBILISI"),))] == Decimal("14.15")
