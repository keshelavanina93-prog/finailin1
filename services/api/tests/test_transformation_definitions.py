# ruff: noqa: F811
"""Canonical DAG compilation; edges order completion and do not move data."""

from uuid import uuid4, uuid5

import pytest
from pydantic import ValidationError
from test_definition_history import DB, item, retained  # noqa: F401
from test_function_execution import function_case

from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.domain.transformation import TransformationGraph, TransformationRunRequest
from finai_api.services import transformation_definitions


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
            }
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
    for node, limit in zip(compiled["nodes"], [2, 3], strict=True):
        assert node["invocation"]["request_id"] == str(uuid5(request.request_id, node["node_id"]))
        assert node["invocation"]["function"] == invocation.function.model_dump(mode="json")
        assert node["function_plan"]["request"]["limit"] == limit
        assert (
            node["function_plan"]["request"]["known_at"]
            == request.model_dump(mode="json")["known_at"]
        )
