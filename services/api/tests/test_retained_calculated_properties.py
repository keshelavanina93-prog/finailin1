"""Retained calculated values are explicit immutable inputs, never recalculated fallbacks."""

# ruff: noqa:F811
from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4, uuid5

import pytest
from test_definition_history import DB, item, retained  # noqa:F401
from test_derived_property_graph import graph_case
from test_function_execution import function_case

from finai_api.domain.function_execution import FunctionImplementation, FunctionInvocation
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.domain.transformation import TransformationRunRequest
from finai_api.services import function_execution as functions
from finai_api.services import (
    function_invocations,
    ontology_definitions,
    transformation_definitions,
    transformation_runs,
)
from finai_api.services import report_workflows as records
from finai_api.services.derived_property_graph import evaluate_graph, resolve_with_loader
from finai_api.services.workspace import WorkspaceError


def seed_case():
    schema, _, leaf, _, root, obj, _, load = graph_case()
    declared = [leaf]
    config = [{**functions._pin(leaf), "schema": functions._pin(schema)}]
    row = {
        "object_id": obj["resource_id"],
        "object_version_id": obj["version_id"],
        "definition_id": str(leaf["resource_id"]),
        "definition_version_id": str(leaf["version_id"]),
        "name": "calculated",
        "kind": "decimal",
        "epistemic_state": "DERIVED",
        "status": "AVAILABLE",
        "value": "123.45",
    }
    source = {"invocation_id": str(uuid4()), "receipt_hash": "a" * 64, "run_id": "fcr_" + "b" * 64}
    return config, declared, obj, row, source, resolve_with_loader([root], load)


def test_retained_value_seeds_graph_without_source_expression_or_fake_reads(monkeypatch):
    config, declared, obj, row, source, graph = seed_case()
    values = functions._retained_property_values(config, declared, [obj], [row], source)
    original = ontology_definitions.evaluate_expression

    def no_source_rerun(expression, attributes, derived=None, field_value=None):
        if expression.op == "field":
            pytest.fail("An explicitly retained value must not read source fields again")
        return original(expression, attributes, derived, field_value)

    monkeypatch.setattr(ontology_definitions, "evaluate_expression", no_source_rerun)
    result = evaluate_graph(graph, [obj], retained_values=values)[0]
    assert obj["attributes"]["observed"] == "0"  # Recalculation would give a different value.
    assert result["value"] == "123.45"
    dependency = result["dependency_values"][0]
    assert dependency["source_result"] == source and dependency["source_fields"] == []


@pytest.mark.parametrize(
    "failure",
    [
        "version",
        "kind",
        "status",
        "boolean",
        "nonfinite",
        "missing",
        "duplicate",
        "extra",
        "absentvalue",
    ],
)
def test_retained_output_matrix_refuses_malformed_or_unbound_rows(failure):
    config, declared, obj, row, source, _ = seed_case()
    values = [row]
    if failure == "version":
        row["definition_version_id"] = str(uuid4())
    elif failure == "kind":
        row["kind"] = "text"
    elif failure == "status":
        row["status"] = "INVENTED"
    elif failure == "boolean":
        row["value"] = True
    elif failure == "nonfinite":
        row["value"] = "NaN"
    elif failure == "missing":
        values = []
    elif failure == "duplicate":
        values = [row, row]
    elif failure == "extra":
        values = [row, {**row, "object_id": str(uuid4())}]
    else:
        row.pop("value")
    with pytest.raises(WorkspaceError):
        functions._retained_property_values(config, declared, [obj], values, source)


def test_optional_retained_properties_preserves_legacy_definition_shape():
    raw = {
        "implementation_id": "ontology.object-set-derived/v1",
        "determinism": "DETERMINISTIC_FOR_PINNED_INPUTS",
        "code_sha256": "a" * 64,
        "dependency_sha256": "b" * 64,
        "derived_property_ids": [],
    }
    assert FunctionImplementation.model_validate(raw).model_dump(mode="json") == raw
    pin = {"resource_id": str(uuid4()), "version_id": str(uuid4())}
    with pytest.raises(ValueError):
        FunctionImplementation.model_validate(
            {**raw, "derived_property_ids": [str(uuid4())], "retained_properties": [pin, pin]}
        )


def retained_calculation_case(retained, monkeypatch):
    reader, _initial, company, query, original_function = function_case(retained)
    reader = reader.model_copy(update={"permissions": (*reader.permissions, "read", "ingest")})
    _, publish = retained
    schema = canonical_id(reader.scope.tenant_id, "SchemaDefinition", "LegalEntity")
    base = item(
        "DerivedProperty",
        {
            "schema_id": str(schema),
            "definition": {
                "name": "retained_label",
                "result_kind": "text",
                "expression": {"op": "literal", "value": "SYNTHETIC calculated"},
            },
        },
    )
    base_row = publish(base)[0]
    downstream = item(
        "DerivedProperty",
        {
            "schema_id": str(schema),
            "definition": {
                "name": "consumed_label",
                "result_kind": "text",
                "expression": {
                    "op": "concat",
                    "args": [
                        {
                            "op": "derived",
                            "property": {
                                "resource_id": str(base.resource_id),
                                "version_id": base_row["version_id"],
                            },
                        },
                        {"op": "literal", "value": " | retained"},
                    ],
                },
            },
        },
    )
    publish(downstream)
    source_function = item(
        "FunctionDefinition",
        {
            "object_set_id": str(query.resource_id),
            "definition": {
                **original_function.attributes["definition"],
                "derived_property_ids": [str(base.resource_id)],
            },
        },
    )
    destination_function = item(
        "FunctionDefinition",
        {
            "object_set_id": str(query.resource_id),
            "definition": {
                **original_function.attributes["definition"],
                "derived_property_ids": [str(downstream.resource_id)],
                "retained_properties": [
                    {"resource_id": str(base.resource_id), "version_id": base_row["version_id"]}
                ],
            },
        },
    )
    _source_row, destination_row = publish(source_function, destination_function)
    now = datetime.now(UTC)
    bare = FunctionInvocation(
        function=VersionReference(
            resource_id=destination_function.resource_id, version_id=destination_row["version_id"]
        ),
        valid_at=now,
        known_at=now,
        limit=10,
    )
    with pytest.raises(WorkspaceError, match="require an upstream invocation"):
        functions.plan(reader, bare)
    definition = item(
        "TransformationDefinition",
        {
            "resource_budget": {
                "max_returned_rows": 20,
                "max_derived_evaluations": 20,
                "max_published_result_bytes": 16000000,
            },
            "definition": {
                "nodes": [
                    {
                        "node_id": "source",
                        "function_id": str(source_function.resource_id),
                        "limit": 10,
                    },
                    {
                        "node_id": "consumer",
                        "function_id": str(destination_function.resource_id),
                        "limit": 10,
                        "depends_on": ["source"],
                        "input_binding": {"upstream_node_id": "source"},
                    },
                ],
                "outputs": [{"output_id": "calculated", "node_id": "consumer"}],
            },
        },
    )
    published = publish(definition)[0]
    run = TransformationRunRequest(
        transformation=VersionReference(
            resource_id=definition.resource_id, version_id=published["version_id"]
        ),
        valid_at=now,
        known_at=now,
    )
    plan = transformation_definitions.plan(reader, run)
    assert (
        plan["nodes"][1]["function_plan"]["retained_properties"][0]["version_id"]
        == base_row["version_id"]
    )
    identity = transformation_runs.retain(reader, run)
    context = {
        "workflow_id": identity,
        "actor_id": reader.actor_id,
        "scope": reader.scope.model_dump(mode="json"),
    }
    monkeypatch.setattr(records, "current_principal", lambda *_: reader)
    assert (
        transformation_runs.execute_node({**context, "node_id": "source"})["state"] == "COMPLETED"
    )
    return {
        "reader": reader,
        "run": run,
        "plan": plan,
        "context": context,
        "company": company,
        "definition": definition,
        "original_function": original_function,
        "publish": publish,
        "source": function_invocations.history(reader, uuid5(run.request_id, "source")),
        "request": FunctionInvocation.model_validate(plan["nodes"][1]["invocation"]),
    }


@DB
def test_native_transformation_consumes_calculation_without_recompute_and_scope_escape(
    retained, monkeypatch
):
    case = retained_calculation_case(retained, monkeypatch)
    reader, run, plan, context, company, definition, original_function, publish = (
        case[name]
        for name in (
            "reader",
            "run",
            "plan",
            "context",
            "company",
            "definition",
            "original_function",
            "publish",
        )
    )
    original = ontology_definitions.evaluate_expression

    def no_recompute(expression, values, derived=None, field_value=None):
        if expression.op == "literal" and expression.value == "SYNTHETIC calculated":
            pytest.fail("Consumer must use retained calculated output")
        return original(expression, values, derived, field_value)

    monkeypatch.setattr(ontology_definitions, "evaluate_expression", no_recompute)
    monkeypatch.setattr(
        ontology_definitions, "run_set", lambda *_: pytest.fail("Consumer must not requery")
    )
    assert (
        transformation_runs.execute_node({**context, "node_id": "consumer"})["state"] == "COMPLETED"
    )
    publication = transformation_runs.publish(context)
    assert transformation_runs.publish(context) == publication
    invoked = uuid5(run.request_id, "consumer")
    receipt = function_invocations.history(reader, invoked)
    output = receipt["output"]
    assert output["derived_values"][0]["value"] == "SYNTHETIC calculated | retained"
    assert output["derived_values"][0]["dependency_values"][0]["source_fields"] == []
    assert output["consumed_property_values"][0]["source_result"] == output["input_result"]
    assert output["objects"][0]["resource_id"] == str(company.resource_id)
    stranger = reader.model_copy(
        update={
            "scope": reader.scope.model_copy(
                update={"legal_entity_id": "synthetic-other-" + uuid4().hex}
            )
        }
    )
    bound = FunctionInvocation.model_validate(plan["nodes"][1]["invocation"])
    with pytest.raises(WorkspaceError) as hidden:
        functions._retained_input(stranger, bound, plan["nodes"][1]["function_plan"])
    assert hidden.value.status == 404
    assert function_invocations.invoke(reader, bound) == receipt
    # A source Function with the same ObjectSet but no declared calculated root is incompatible.
    bad = deepcopy(definition.attributes)
    bad["definition"]["nodes"][0]["function_id"] = str(original_function.resource_id)
    wrong = item("TransformationDefinition", bad)
    wrong_row = publish(wrong)[0]
    with pytest.raises(WorkspaceError, match="does not declare"):
        transformation_definitions.plan(
            reader,
            run.model_copy(
                update={
                    "request_id": uuid4(),
                    "transformation": VersionReference(
                        resource_id=wrong.resource_id, version_id=wrong_row["version_id"]
                    ),
                }
            ),
        )
