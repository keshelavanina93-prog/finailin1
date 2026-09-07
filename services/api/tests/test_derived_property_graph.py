"""Exact composition reuses one evaluator and records only evaluated input paths."""

# ruff: noqa:F811
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from test_definition_history import DB, item, retained  # noqa:F401

from finai_api.domain.object_sets import ObjectSetQuery
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.ontology_definitions import Expression
from finai_api.domain.resources import ResourceProposal, ResourceReview
from finai_api.services import ontology_definitions as definitions
from finai_api.services import resources
from finai_api.services.derived_property_graph import evaluate_graph, resolve_with_loader
from finai_api.services.workspace import WorkspaceError


def ref(row):
    return {"resource_id": str(row["resource_id"]), "version_id": str(row["version_id"])}


def derived(row):
    return {"op": "derived", "property": ref(row)}


def graph_case():
    schema = {
        "resource_id": uuid4(),
        "version_id": uuid4(),
        "content_hash": "b" * 64,
        "object_type": "SchemaDefinition",
        "authority_state": "APPROVED",
        "identity_key": "GraphFixture",
    }

    def node(expression, children=()):
        return {
            "resource_id": uuid4(),
            "version_id": uuid4(),
            "content_hash": "a" * 64,
            "object_type": "DerivedProperty",
            "authority_state": "APPROVED",
            "attributes": {
                "schema_id": str(schema["resource_id"]),
                "definition": {
                    "name": "calculated",
                    "result_kind": "decimal",
                    "expression": expression,
                },
            },
            "dependencies": [
                {**schema, "relation": "FIELD:schema_id"},
                *[
                    {**child, "relation": "DERIVED_PROPERTY:" + str(child["resource_id"])}
                    for child in children
                ],
            ],
        }

    leaf = node({"op": "field", "field": "observed"})
    fallback = node(
        {
            "op": "divide",
            "args": [
                {"op": "field", "field": "numerator"},
                {"op": "field", "field": "denominator"},
            ],
        }
    )
    root = node({"op": "coalesce", "args": [derived(leaf), derived(fallback)]}, [leaf, fallback])
    obj = {
        "resource_id": str(uuid4()),
        "version_id": str(uuid4()),
        "content_hash": "c" * 64,
        "object_type": "GraphFixture",
        "schema_version_id": str(schema["version_id"]),
        "attributes": {"observed": "0", "numerator": "5", "denominator": "0"},
    }
    rows = {str(row["resource_id"]): row for row in [root, leaf, fallback]}

    def load(identity, version):
        return rows[str(identity)]

    return schema, node, leaf, fallback, root, obj, rows, load


def test_expression_shape_and_actual_coalesce_dependency_evidence():
    _, _, leaf, fallback, root, obj, _, load = graph_case()
    assert "property" not in Expression(op="field", field="a").model_dump()
    with pytest.raises(ValueError):
        Expression(op="derived", property=ref(leaf), field="a")
    with pytest.raises(ValueError):
        Expression(op="field", field="a", property=ref(leaf))
    graph = resolve_with_loader([root], load)
    first = evaluate_graph(graph, [obj])[0]
    assert first["value"] == "0" and first["status"] == "AVAILABLE"
    assert first["source_fields"] == []
    assert [r["definition_id"] for r in first["dependency_values"]] == [str(leaf["resource_id"])]
    source = first["dependency_values"][0]["source_fields"][0]
    assert source["field"] == "observed" and source["state"] == "VALUE" and source["value"] == "0"
    assert (
        source["object_version_id"] == obj["version_id"]
        and source["object_content_hash"] == obj["content_hash"]
    )
    obj["attributes"].pop("observed")
    failed = evaluate_graph(graph, [obj])[0]
    assert failed["status"] == "UNAVAILABLE"
    assert {r["definition_id"] for r in failed["dependency_values"]} == {
        str(leaf["resource_id"]),
        str(fallback["resource_id"]),
    }
    assert failed["dependency_values"][0]["source_fields"][0]["state"] == "MISSING"
    obj["attributes"] = {}
    assert evaluate_graph(graph, [obj])[0]["status"] == "MISSING_INPUT"
    # Unavailable evaluated dependency must never be treated as a null fallback.
    root["attributes"]["definition"]["expression"]["args"].reverse()
    obj["attributes"] = {"observed": "7", "numerator": "5", "denominator": "0"}
    assert evaluate_graph(resolve_with_loader([root], load), [obj])[0]["status"] == "UNAVAILABLE"


@pytest.mark.parametrize("failure", ["pin", "schema", "revoked", "cycle", "conflicting_version"])
def test_graph_rejects_missing_pins_schema_mismatch_cycles_and_unavailable(failure):
    _, _, leaf, _, root, _, _rows, load = graph_case()
    if failure == "pin":
        root["dependencies"] = root["dependencies"][:1]
    elif failure == "schema":
        leaf["dependencies"][0]["version_id"] = uuid4()
    elif failure == "revoked":
        leaf["authority_state"] = "REVOKED"
    elif failure == "cycle":
        leaf["attributes"]["definition"]["expression"] = derived(root)
        leaf["dependencies"].append(
            {**root, "relation": "DERIVED_PROPERTY:" + str(root["resource_id"])}
        )
    else:
        alternate = deepcopy(leaf)
        alternate["version_id"] = uuid4()
        with pytest.raises(WorkspaceError, match="multiple versions"):
            resolve_with_loader([leaf, alternate], load)
        return
    with pytest.raises(WorkspaceError):
        resolve_with_loader([root], load)


def test_graph_shared_dependency_memo_and_depth_bound(monkeypatch):
    _, node, leaf, _, _, obj, rows, load = graph_case()
    root = node({"op": "add", "args": [derived(leaf), derived(leaf)]}, [leaf])
    calls = []
    original = definitions.evaluate_expression

    def spy(expression, values, derived=None, field_value=None):
        if expression.op == "field":
            calls.append(expression.field)
        return original(expression, values, derived, field_value)

    monkeypatch.setattr(definitions, "evaluate_expression", spy)
    assert evaluate_graph(resolve_with_loader([root], load), [obj])[0]["value"] == "0"
    assert calls == ["observed"]
    for _ in range(11):
        root = node(derived(leaf), [leaf])
        rows[str(root["resource_id"])] = root
        leaf = root
    with pytest.raises(WorkspaceError, match="depth"):
        resolve_with_loader([root], load)


@DB
def test_native_composition_review_correction_and_retained_schema(retained):
    reader, publish = retained
    author = reader.model_copy(
        update={
            "permissions": (
                "ontology_read",
                "ontology_admin",
                "ontology_propose",
                "ontology_review",
            )
        }
    )
    reviewer = author.model_copy(update={"actor_id": "synthetic-derived-graph-reviewer"})
    kind = "DerivedGraph" + uuid4().hex[:10]
    schema = item(
        "SchemaDefinition",
        {
            "additional_fields": False,
            "fields": {
                "code": {
                    "field_id": str(uuid4()),
                    "kind": "text",
                    "required": True,
                    "semantic_id": str(
                        canonical_id(reader.scope.tenant_id, "SemanticContract", "Text")
                    ),
                },
                "label": {
                    "field_id": str(uuid4()),
                    "kind": "text",
                    "required": True,
                    "semantic_id": str(
                        canonical_id(reader.scope.tenant_id, "SemanticContract", "Text")
                    ),
                },
            },
        },
    ).model_copy(update={"identity_key": kind})
    proposal = ResourceProposal(
        title="SYNTHETIC composed property schema",
        rationale="Isolated exact composition runtime acceptance",
        access_entity="__PLATFORM__",
        mutations=[schema],
    )
    resources.propose(author, proposal)
    resources.review(
        reviewer,
        proposal.proposal_id,
        ResourceReview(decision="APPROVED", rationale="Independent synthetic schema approval"),
    )
    source = item(kind, {"code": "synthetic-A", "label": "retained input"})
    publish(source)
    base = item(
        "DerivedProperty",
        {
            "schema_id": str(schema.resource_id),
            "definition": {
                "name": "source_code",
                "result_kind": "text",
                "expression": {"op": "field", "field": "code"},
            },
        },
    )
    base_row = publish(base)[0]
    composed = item(
        "DerivedProperty",
        {
            "schema_id": str(schema.resource_id),
            "definition": {
                "name": "composed_label",
                "result_kind": "text",
                "expression": {
                    "op": "concat",
                    "args": [
                        derived(base_row),
                        {"op": "literal", "value": " | "},
                        {"op": "field", "field": "label"},
                    ],
                },
            },
        },
    )
    composed_row = publish(composed)[0]
    outer = item(
        "DerivedProperty",
        {
            "schema_id": str(schema.resource_id),
            "definition": {
                "name": "repeated_composition",
                "result_kind": "text",
                "expression": {
                    "op": "concat",
                    "args": [derived(composed_row), derived(composed_row)],
                },
            },
        },
    )
    outer_row = publish(outer)[0]
    retained_outer = definitions.definition(
        reader, outer.resource_id, UUID(outer_row["version_id"])
    )
    assert (
        len(
            [
                edge
                for edge in retained_outer["dependencies"]
                if edge["relation"] == "DERIVED_PROPERTY:" + str(composed.resource_id)
            ]
        )
        == 1
    )
    query = ObjectSetQuery(object_type=kind, resource_ids=[source.resource_id])
    run = definitions.derive_query(
        reader,
        query,
        [composed.resource_id],
        {composed.resource_id: UUID(composed_row["version_id"])},
    )
    assert run["derived_values"][0]["value"] == "synthetic-A | retained input"
    assert len(run["derived_graph"]["nodes"]) == 2
    assert (
        run["derived_values"][0]["dependency_values"][0]["definition_version_id"]
        == base_row["version_id"]
    )
    assert run["derived_values"][0]["source_fields"][0]["field"] == "label"
    deep_run = definitions.derive_query(
        reader, query, [outer.resource_id], {outer.resource_id: UUID(outer_row["version_id"])}
    )
    assert len(deep_run["derived_graph"]["nodes"]) == 3
    assert deep_run["derived_values"][0]["value"] == "synthetic-A | retained input" * 2
    assert len(deep_run["derived_values"][0]["dependency_values"]) == 2
    changed = base.model_copy(
        update={
            "expected_version_id": UUID(base_row["version_id"]),
            "attributes": {
                **base.attributes,
                "definition": {
                    **base.attributes["definition"],
                    "expression": {
                        "op": "concat",
                        "args": [
                            {"op": "field", "field": "code"},
                            {"op": "literal", "value": ":corrected"},
                        ],
                    },
                },
            },
        }
    )
    changed_row = publish(changed)[0]
    assert (
        definitions.derived_values(
            reader,
            run["objects"],
            [base.resource_id],
            {base.resource_id: UUID(changed_row["version_id"])},
        )[0]["value"]
        == "synthetic-A:corrected"
    )
    replay = definitions.derive_query(
        reader,
        query,
        [composed.resource_id],
        {composed.resource_id: UUID(composed_row["version_id"])},
    )
    assert replay["derived_values"] == run["derived_values"]
    assert replay["derived_graph"] == run["derived_graph"]
    deep_replay = definitions.derive_query(
        reader, query, [outer.resource_id], {outer.resource_id: UUID(outer_row["version_id"])}
    )
    assert deep_replay["derived_values"] == deep_run["derived_values"]
    assert deep_replay["derived_graph"] == deep_run["derived_graph"]
