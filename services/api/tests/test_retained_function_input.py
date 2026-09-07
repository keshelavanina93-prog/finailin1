# ruff: noqa: F811
"""Explicit retained result transfer, with no new source query."""

from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_definition_history import DB, retained  # noqa: F401
from test_function_execution import function_case

from finai_api.domain.function_execution import FunctionInvocation, RetainedResultInput
from finai_api.domain.transformation import TransformationGraph
from finai_api.services import function_execution, function_invocations
from finai_api.services.workspace import WorkspaceError


def test_optional_inputs_preserve_existing_serialization():
    raw = {
        "request_id": str(uuid4()),
        "function": {"resource_id": str(uuid4()), "version_id": str(uuid4())},
        "valid_at": "2026-09-01T00:00:00Z",
        "known_at": "2026-09-01T00:00:00Z",
        "offset": 0,
        "limit": 10,
    }
    request = FunctionInvocation.model_validate(raw)
    assert request.model_dump(mode="json") == raw
    assert "input_result" not in request.model_dump()
    graph = {
        "nodes": [
            {
                "node_id": "source",
                "function_id": str(uuid4()),
                "depends_on": [],
                "offset": 0,
                "limit": 10,
            }
        ],
        "outputs": [{"output_id": "result", "node_id": "source"}],
    }
    assert TransformationGraph.model_validate(graph).model_dump(mode="json") == graph
    graph["nodes"].append(
        {
            "node_id": "derived",
            "function_id": str(uuid4()),
            "depends_on": [],
            "limit": 10,
            "input_binding": {"upstream_node_id": "source"},
        }
    )
    with pytest.raises(ValueError, match="explicit dependency"):
        TransformationGraph.model_validate(graph)


@DB
def test_retained_page_consumed_without_requery_and_replayed(retained, monkeypatch):
    reader, request, company, _, _ = function_case(retained)
    source = function_invocations.invoke(reader, request)
    assert source["status"] == "SUCCEEDED"
    bound = request.model_copy(
        update={
            "request_id": uuid4(),
            "input_result": RetainedResultInput(invocation_id=request.request_id),
        }
    )
    monkeypatch.setattr(
        function_execution.ontology_definitions,
        "run_set",
        lambda *_: pytest.fail("Bound input must never requery"),
    )
    result = function_invocations.invoke(reader, bound)
    assert result["status"] == "SUCCEEDED", result
    assert result["output"]["objects"] == source["output"]["objects"]
    assert result["output"]["query"] == source["output"]["query"]
    assert result["output"]["coverage"] == "RETAINED_INPUT_PAGE_ONLY"
    assert result["output"]["input_result"] == {
        "invocation_id": source["invocation_id"],
        "receipt_hash": source["receipt_hash"],
        "run_id": source["output"]["run_id"],
    }
    assert function_invocations.invoke(reader, bound) == result
    stranger = reader.model_copy(
        update={
            "scope": reader.scope.model_copy(
                update={"legal_entity_id": "synthetic-retained-input-other-" + uuid4().hex}
            )
        }
    )
    with pytest.raises(WorkspaceError) as hidden:
        function_execution._retained_input(stranger, bound, function_execution.plan(reader, bound))
    assert hidden.value.status == 404
    with pytest.raises(WorkspaceError, match="incompatible"):
        function_execution.plan(reader, bound.model_copy(update={"limit": 1}))
    # A correctly hashed intent still cannot invent a successful upstream receipt.
    from finai_api.domain.authority import canonical_sha256

    forged = bound.model_copy(
        update={"request_id": uuid4(), "input_result": RetainedResultInput(invocation_id=uuid4())}
    )
    forged_plan = function_execution.plan(reader, forged, defer_input=True)
    with pytest.raises(psycopg.errors.RaiseException), function_invocations._database(reader) as c:
        c.execute(
            "INSERT INTO function_invocations "
            "(tenant_id,request_id,exact_scope,actor_id,request_hash,request,plan,plan_hash) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                reader.scope.tenant_id,
                forged.request_id,
                Jsonb(reader.scope.model_dump(mode="json")),
                reader.actor_id,
                canonical_sha256(forged),
                Jsonb(forged.model_dump(mode="json")),
                Jsonb(forged_plan),
                forged_plan["plan_hash"],
            ),
        )
    # This fixture explicitly pins its object as a static Object Set dependency.
    # Correction invalidates new execution, while completed evidence stays unchanged.
    retained[1](
        company.model_copy(
            update={
                "expected_version_id": UUID(source["output"]["objects"][0]["version_id"]),
                "display_name": "SYNTHETIC corrected after input capture",
            }
        )
    )
    assert function_invocations.invoke(reader, bound) == result
    with pytest.raises(WorkspaceError, match="current use"):
        function_execution.plan(reader, bound.model_copy(update={"request_id": uuid4()}))
