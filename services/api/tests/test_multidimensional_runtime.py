from decimal import Decimal

from fastapi.testclient import TestClient

from finai_api.domain.calculation_graph import CalculationGraph, CalculationNode
from finai_api.domain.multidimensional_runtime import (
    AggregationPolicy,
    CalculationBlock,
    Coordinate,
    DimensionalSignature,
    DimensionMapping,
    DimensionMappingRule,
    HierarchyDefinition,
    HierarchyMembership,
    IntersectionSet,
    RuntimeState,
    TransformDefinition,
    TransformType,
    aggregate_by_hierarchy,
    aggregate_sparse_values,
    compile_sparse_plan,
    execute_sparse_decimal_plan,
    execute_transform,
    map_coordinate,
    resolve_hierarchy_parent,
)
from finai_api.main import app


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


def test_financial_aggregation_and_time_conversion_are_explicit() -> None:
    cells = {
        Coordinate(values=(("product", "DIESEL"), ("period", "2026-09"))): Decimal("10"),
        Coordinate(values=(("product", "DIESEL"), ("period", "2026-10"))): Decimal("12"),
    }
    last = aggregate_sparse_values(
        cells,
        frozenset({"product"}),
        policy=AggregationPolicy.LAST_VALID,
    )
    assert last[Coordinate(values=(("product", "DIESEL"),))] == Decimal("12")
    shifted = execute_transform(
        TransformDefinition(
            transform_id="lag-volume",
            transform_type=TransformType.LAG,
            source_signature_id="product-period",
            target_signature_id="product-period",
            implementation_id="trusted.time.lag.v1",
        ),
        cells,
    )
    assert Coordinate(values=(("period", "2026-08"), ("product", "DIESEL"))) in shifted


def test_hierarchy_aggregation_uses_replay_membership() -> None:
    hierarchy = HierarchyDefinition(
        hierarchy_id="station-region",
        version="2",
        child_dimension="station",
        parent_dimension="region",
        valid_from="2026-01-01T00:00:00+00:00",
        known_at="2026-01-01T00:00:00+00:00",
    )
    memberships = (
        HierarchyMembership(
            hierarchy_id="station-region",
            child_value="024",
            parent_value="OLD",
            valid_from="2026-01-01T00:00:00+00:00",
            valid_to="2026-09-01T00:00:00+00:00",
            known_at="2026-01-01T00:00:00+00:00",
        ),
        HierarchyMembership(
            hierarchy_id="station-region",
            child_value="024",
            parent_value="NEW",
            valid_from="2026-09-01T00:00:00+00:00",
            known_at="2026-09-02T00:00:00+00:00",
        ),
    )
    result = aggregate_by_hierarchy(
        {coordinate("024"): Decimal("7")},
        hierarchy,
        memberships,
        valid_at="2026-08-31T00:00:00+00:00",
        replay_as_of="2026-09-01T00:00:00+00:00",
    )
    assert result[
        Coordinate(values=(("company", "SGP"), ("period", "2026-09"), ("region", "OLD")))
    ] == Decimal("7")


def test_transform_dispatch_refuses_unregistered_execution_and_supports_mapping() -> None:
    source = {Coordinate(values=(("station", "024"),)): Decimal("10")}
    transform = TransformDefinition(
        transform_id="map-station-region",
        transform_type=TransformType.MAP,
        source_signature_id="station",
        target_signature_id="region",
        implementation_id="trusted.map.v1",
    )
    result = execute_transform(
        transform,
        source,
        mapping=DimensionMapping(
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
    assert result == {Coordinate(values=(("region", "TBILISI"),)): Decimal("10")}
    unsupported = transform.model_copy(update={"transform_type": TransformType.RECONCILE})
    try:
        execute_transform(unsupported, source)
    except ValueError as error:
        assert "not registered" in str(error)
    else:
        raise AssertionError("Unregistered transform unexpectedly executed")


def test_hierarchy_replay_uses_valid_and_known_time() -> None:
    hierarchy = HierarchyDefinition(
        hierarchy_id="station-region",
        version="2",
        child_dimension="station",
        parent_dimension="region",
        valid_from="2026-01-01T00:00:00+00:00",
        known_at="2026-01-01T00:00:00+00:00",
    )
    memberships = (
        HierarchyMembership(
            hierarchy_id="station-region",
            child_value="024",
            parent_value="OLD",
            valid_from="2026-01-01T00:00:00+00:00",
            valid_to="2026-09-01T00:00:00+00:00",
            known_at="2026-01-01T00:00:00+00:00",
        ),
        HierarchyMembership(
            hierarchy_id="station-region",
            child_value="024",
            parent_value="NEW",
            valid_from="2026-09-01T00:00:00+00:00",
            known_at="2026-09-02T00:00:00+00:00",
        ),
    )
    assert (
        resolve_hierarchy_parent(
            hierarchy,
            memberships,
            "024",
            valid_at="2026-08-31T00:00:00+00:00",
            replay_as_of="2026-09-01T00:00:00+00:00",
        )
        == "OLD"
    )
    assert (
        resolve_hierarchy_parent(
            hierarchy,
            memberships,
            "024",
            valid_at="2026-09-10T00:00:00+00:00",
            replay_as_of="2026-09-10T00:00:00+00:00",
        )
        == "NEW"
    )


def test_compile_endpoint_returns_read_only_sparse_plan() -> None:
    graph, signatures, blocks, intersections = runtime_fixture()
    payload = {
        "graph": graph.model_dump(mode="json"),
        "signatures": [item.model_dump(mode="json") for item in signatures],
        "blocks": [item.model_dump(mode="json") for item in blocks],
        "intersections": [item.model_dump(mode="json") for item in intersections],
        "changed_nodes": ["revenue"],
        "changed_coordinates": [coordinate("024").model_dump(mode="json")],
    }
    with TestClient(app, headers={"Authorization": "Bearer test-token"}) as client:
        response = client.post("/v1/workspace/calculation/compile", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["contract"] == "calculation-compile/1"
    assert body["plan"]["selected_node_ids"] == ["revenue", "margin"]
    assert body["plan"]["affected_coordinates"] == [coordinate("024").model_dump(mode="json")]
    assert body["authority_effect"] == "NONE"
    assert body["execution_performed"] is False


def test_execute_endpoint_runs_only_closed_decimal_operators() -> None:
    graph, signatures, blocks, intersections = runtime_fixture()
    payload = {
        "graph": graph.model_dump(mode="json"),
        "signatures": [item.model_dump(mode="json") for item in signatures],
        "blocks": [item.model_dump(mode="json") for item in blocks],
        "intersections": [item.model_dump(mode="json") for item in intersections],
        "values": [
            {
                "node_id": "revenue",
                "coordinate": coordinate("024").model_dump(mode="json"),
                "value": "100",
            },
            {
                "node_id": "cogs",
                "coordinate": coordinate("024").model_dump(mode="json"),
                "value": "40",
            },
        ],
        "target": "GrossMargin",
        "input_pins": ["fixture:1"],
        "valid_at": "2026-09-30T23:59:59+00:00",
        "known_at": "2026-10-01T08:00:00+00:00",
    }
    with TestClient(app, headers={"Authorization": "Bearer test-token"}) as client:
        response = client.post("/v1/workspace/calculation/execute", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["contract"] == "calculation-execute/1"
    assert body["execution_performed"] is True
    assert body["result"]["state"] == "CALCULATION_FRESH"
    assert body["result"]["authority_state"] == "DERIVED_CANDIDATE"
    assert body["result"]["accounting_authorized"] is False
    assert any(
        cell["node_id"] == "margin" and cell["value"] == "60"
        for cell in body["result"]["cells"]
    )


def test_execute_endpoint_refuses_unregistered_formula_operator() -> None:
    graph, signatures, blocks, intersections = runtime_fixture()
    graph = graph.model_copy(
        update={
            "nodes": (
                graph.nodes[0].model_copy(update={"function_id": "caller_formula"}),
                *graph.nodes[1:],
            )
        }
    )
    payload = {
        "graph": graph.model_dump(mode="json"),
        "signatures": [item.model_dump(mode="json") for item in signatures],
        "blocks": [item.model_dump(mode="json") for item in blocks],
        "intersections": [item.model_dump(mode="json") for item in intersections],
        "values": [],
    }
    with TestClient(app, headers={"Authorization": "Bearer test-token"}) as client:
        response = client.post("/v1/workspace/calculation/execute", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["execution_performed"] is False
    assert body["result"]["state"] == "BLOCKED"
    assert "No evaluator registered" in body["result"]["refusal_reason"]
