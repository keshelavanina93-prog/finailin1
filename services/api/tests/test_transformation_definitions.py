# ruff: noqa: F811
"""Canonical DAG compilation; edges order completion and do not move data."""

from uuid import uuid4, uuid5

import pytest
from pydantic import ValidationError
from test_definition_history import DB, item, retained  # noqa: F401
from test_function_execution import function_case

from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.domain.transformation import (
    TransformationDefinition,
    TransformationGraph,
    TransformationRunRequest,
)
from finai_api.services import transformation_definitions
from finai_api.services.workspace import WorkspaceError


@pytest.mark.parametrize(
    "nodes,outputs",
    [
        (
            [{"node_id": "a", "depends_on": ["b"]}, {"node_id": "b", "depends_on": ["a"]}],
            [{"output_id": "result", "node_id": "a"}],
        ),
        ([{"node_id": "a", "depends_on": ["missing"]}], [{"output_id": "result", "node_id": "a"}]),
        ([{"node_id": "a"}, {"node_id": "a"}], [{"output_id": "result", "node_id": "a"}]),
        (
            [{"node_id": "a"}],
            [{"output_id": "result", "node_id": "a"}, {"output_id": "result", "node_id": "a"}],
        ),
        ([{"node_id": "a"}], [{"output_id": "result", "node_id": "missing"}]),
    ],
)
def test_invalid_dag_contracts_fail_closed(nodes, outputs):
    with pytest.raises(ValidationError):
        TransformationGraph(
            nodes=[{**node, "function_id": uuid4()} for node in nodes], outputs=outputs
        )


@DB
def test_canonical_transformation_compiles_exact_function_plans_and_stable_run_ids(retained):
    reader, invocation, _, _, _ = function_case(retained)
    _, publish = retained
    definition = item(
        "TransformationDefinition",
        {
            "resource_budget": {
                "max_returned_rows": 5,
                "max_derived_evaluations": 0,
                "max_published_result_bytes": 1000000,
            },
            "definition": {
                "nodes": [
                    {
                        "node_id": "second",
                        "function_id": str(invocation.function.resource_id),
                        "depends_on": ["first"],
                        "limit": 3,
                    },
                    {
                        "node_id": "first",
                        "function_id": str(invocation.function.resource_id),
                        "limit": 2,
                    },
                ],
                "outputs": [{"output_id": "observations", "node_id": "second"}],
            },
        },
    )
    row = publish(definition)[0]
    request = TransformationRunRequest(
        transformation=VersionReference(
            resource_id=row["resource_id"], version_id=row["version_id"]
        ),
        valid_at=invocation.valid_at,
        known_at=invocation.known_at,
    )
    compiled = transformation_definitions.plan(reader, request)
    assert compiled == transformation_definitions.plan(reader, request)
    assert compiled["node_order"] == ["first", "second"]
    assert compiled["dependency_semantics"] == "COMPLETION_BARRIER_ONLY"
    assert compiled["coverage"] == "DECLARED_QUERY_PAGES_ONLY"
    assert compiled["business_effect_authorized"] is False
    assert compiled["estimated_work"] == {"returned_rows": 5, "derived_evaluations": 0}
    assert compiled["resource_budget"] == definition.attributes["resource_budget"]
    assert compiled["result_bytes_accounting"] == "POSTGRES_JSONB_TEXT_UTF8_V1"
    for node, limit in zip(compiled["nodes"], [2, 3], strict=True):
        assert node["invocation"]["request_id"] == str(uuid5(request.request_id, node["node_id"]))
        assert node["invocation"]["function"] == invocation.function.model_dump(mode="json")
        assert node["function_plan"]["request"]["limit"] == limit
        assert (
            node["function_plan"]["request"]["known_at"]
            == request.model_dump(mode="json")["known_at"]
        )


@pytest.mark.parametrize(
    "rows,evaluations,node_limit,properties,maximum_rows,reason",
    [
        (3, 10, 2, 1, 200, "returned-row budget"),
        (10, 3, 2, 1, 200, "evaluation budget"),
        (10, 10, 4, 1, 3, "Function capability"),
        (10, 100, 4, 9, 200, "Function capability"),
    ],
)
def test_compiler_admission_uses_aggregate_budget_and_adapter_limits(
    rows, evaluations, node_limit, properties, maximum_rows, reason
):
    definition = TransformationDefinition.model_validate(
        {
            "definition": {
                "nodes": [{"node_id": node, "function_id": str(uuid4())} for node in ("a", "b")],
                "outputs": [{"output_id": "output", "node_id": "a"}],
            },
            "resource_budget": {
                "max_returned_rows": rows,
                "max_derived_evaluations": evaluations,
                "max_published_result_bytes": 1000,
            },
        }
    )
    nodes = [
        {
            "function_plan": {
                "request": {"limit": node_limit},
                "derived_properties": [{}] * properties,
                "implementation": {"maximum_rows": maximum_rows, "maximum_properties": 8},
            }
        }
        for _ in range(2)
    ]
    with pytest.raises(WorkspaceError, match=reason):
        transformation_definitions.estimate_work(definition, nodes)
