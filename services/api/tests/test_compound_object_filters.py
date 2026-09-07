"""Exact stored membership uses the canonical query pipeline at every root and hop."""

# ruff: noqa: F811
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from test_definition_history import DB, item, retained  # noqa: F401

from finai_api.domain.object_sets import FilterExpression, ObjectSetQuery, PropertyFilter, Traversal
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceProposal, ResourceReview
from finai_api.services import ontology_definitions, resources
from finai_api.services.object_sets import query_objects
from finai_api.services.workspace import WorkspaceError


def test_legacy_wire_and_nested_grouping():
    query = ObjectSetQuery(object_type="LegalEntity")
    assert "filter_expression" not in query.model_dump(mode="json")
    assert "filter_expression" not in Traversal(name="owner").model_dump(mode="json")
    leaf = {"field": "code", "value": "A"}
    group = {"op": "all", "conditions": [leaf, {"op": "any", "conditions": [leaf, leaf]}]}
    parsed = ObjectSetQuery(object_type="LegalEntity", filter_expression=group)
    assert len(parsed.filter_expression.leaves()) == 3


@pytest.mark.parametrize("malformed", [False, True])
def test_depth_is_bounded_before_recursive_union(malformed):
    node = {"field": "code", "value": "A"}
    for _ in range(1000):
        node = {
            "conditions": [node, {"field": "code", "value": "B"}],
            **({} if malformed else {"op": "any"}),
        }
    with pytest.raises(ValueError, match="three group levels"):
        FilterExpression.model_validate(node)


def test_cross_stage_leaf_and_membership_budgets():
    leaf = {"field": "code", "value": "A"}
    with pytest.raises(ValueError, match="20-predicate"):
        ObjectSetQuery(
            object_type="LegalEntity",
            filters=[leaf] * 19,
            traversal=[
                {"name": "owner", "filter_expression": {"op": "any", "conditions": [leaf, leaf]}}
            ],
        )
    member = {"field": "code", "operator": "in", "value": [str(i) for i in range(51)]}
    with pytest.raises(ValueError, match="100-value"):
        ObjectSetQuery(
            object_type="LegalEntity",
            filter_expression={"op": "any", "conditions": [member, member]},
        )


@DB
def test_compound_roots_aliases_hops_saved_time_and_page(retained):
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
    kind = "CompoundFixture" + uuid4().hex[:10]

    def field(kind, semantic, **extra):
        return {
            "field_id": str(uuid4()),
            "kind": kind,
            "required": False,
            "semantic_id": str(canonical_id(reader.scope.tenant_id, "SemanticContract", semantic)),
            **extra,
        }

    fields = {
        "column": field("text", "Text"),
        "number": field("decimal", "Amount"),
        "owner": field("reference", "CanonicalReference", target_type="LegalEntity"),
    }
    schema = item("SchemaDefinition", {"additional_fields": False, "fields": fields}).model_copy(
        update={"identity_key": kind}
    )
    proposal = ResourceProposal(
        title="Synthetic membership schema",
        rationale="Isolated exact membership query verification",
        access_entity="__PLATFORM__",
        mutations=[schema],
    )
    resources.propose(author, proposal)
    resources.review(
        author.model_copy(update={"actor_id": "synthetic-membership-checker"}),
        proposal.proposal_id,
        ResourceReview(decision="APPROVED", rationale="Independent synthetic schema review"),
    )
    owner = item("LegalEntity", {})
    publish(owner)
    rows = [
        item(kind, attrs)
        for attrs in [
            {"column": "Y", "number": "1.0", "owner": str(owner.resource_id)},
            {"column": "AA", "number": "1", "owner": str(owner.resource_id)},
            {"column": "Z"},
            {},
        ]
    ]
    stored = publish(*rows)
    frozen = datetime.now(UTC)
    expression = FilterExpression(
        op="any",
        conditions=[
            PropertyFilter(field="column", value="Y"),
            PropertyFilter(field="column", operator="in", value=["Y", "AA"]),
        ],
    )
    query = ObjectSetQuery(object_type=kind, filter_expression=expression, known_at=frozen, limit=1)
    first = query_objects(reader, query)
    second = query_objects(reader, first.query.model_copy(update={"offset": 1}))
    assert (
        first.total == second.total == 2 and first.next_offset == 1 and second.next_offset is None
    )
    assert {first.objects[0]["resource_id"], second.objects[0]["resource_id"]} == {
        str(rows[0].resource_id),
        str(rows[1].resource_id),
    }
    nested = FilterExpression(
        op="all",
        conditions=[
            expression,
            FilterExpression(
                op="any",
                conditions=[
                    PropertyFilter(field="number", operator="gte", value="1"),
                    PropertyFilter(field="column", value="not present"),
                ],
            ),
        ],
    )
    assert query_objects(reader, query.model_copy(update={"filter_expression": nested})).total == 2
    assert (
        query_objects(
            reader,
            query.model_copy(
                update={
                    "filter_expression": nested,
                    "filters": [PropertyFilter(field="column", value="AA")],
                }
            ),
        ).total
        == 1
    )
    excluded = query_objects(
        reader,
        query.model_copy(
            update={
                "filter_expression": None,
                "filters": [PropertyFilter(field="column", operator="not_in", value=["Y", "AA"])],
            }
        ),
    )
    assert excluded.total == 1 and excluded.objects[0]["attributes"]["column"] == "Z"
    exact = query_objects(
        reader,
        query.model_copy(
            update={"filters": [PropertyFilter(field="number", operator="in", value=["1"])]}
        ),
    )
    assert exact.total == 1 and exact.objects[0]["resource_id"] == str(rows[1].resource_id)
    hop = query_objects(
        reader,
        ObjectSetQuery(
            object_type="LegalEntity",
            resource_ids=[owner.resource_id],
            traversal=[Traversal(name="owner", direction="incoming", filter_expression=expression)],
        ),
    )
    assert hop.total == 2
    assert any(pin.object_type == kind and pin.step == 1 for pin in hop.traversal_schema_versions)
    group = item("ObjectTypeGroup", {"definition": {"types": [kind]}})
    group_row = publish(group)[0]
    grouped = query_objects(
        reader,
        ObjectSetQuery(
            object_type="ObjectTypeGroup",
            type_group={"resource_id": group.resource_id, "version_id": group_row["version_id"]},
            filter_expression=expression,
        ),
    )
    assert grouped.total == 2
    interface = item(
        "ObjectInterface",
        {
            "definition": {
                "fields": {
                    "classification": {k: v for k, v in fields["column"].items() if k != "field_id"}
                }
            }
        },
    )
    interface_row = publish(interface)[0]
    implementation = item(
        "ObjectTypeImplementation",
        {
            "interface_id": str(interface.resource_id),
            "schema_id": str(schema.resource_id),
            "definition": {"fields": {"classification": "column"}},
        },
    )
    impl = publish(implementation)[0]
    mapped = ObjectSetQuery(
        object_type="ObjectInterface",
        interface={
            "resource_id": interface.resource_id,
            "version_id": interface_row["version_id"],
            "implementations": [
                {"resource_id": implementation.resource_id, "version_id": impl["version_id"]}
            ],
        },
        filter_expression=FilterExpression(
            op="any",
            conditions=[
                PropertyFilter(field="classification", value="Y"),
                PropertyFilter(field="classification", value="AA"),
            ],
        ),
    )
    assert query_objects(reader, mapped).total == 2
    bad = FilterExpression(
        op="any",
        conditions=[
            PropertyFilter(field="classification", value="Y"),
            PropertyFilter(field="undeclared", value="AA"),
        ],
    )
    with pytest.raises(WorkspaceError, match="undeclared"):
        query_objects(
            reader, mapped.model_copy(update={"resource_ids": [], "filter_expression": bad})
        )
    with pytest.raises(WorkspaceError, match="undeclared"):
        publish(
            item(
                "ObjectSetDefinition",
                {
                    "definition": mapped.model_copy(update={"filter_expression": bad}).model_dump(
                        mode="json"
                    )
                },
            )
        )
    saved = item("ObjectSetDefinition", {"definition": mapped.model_dump(mode="json")})
    saved_row = publish(saved)[0]
    assert (
        ontology_definitions.run_set(
            reader, saved.resource_id, offset=0, limit=50, version=UUID(saved_row["version_id"])
        )["total"]
        == 2
    )
    publish(
        rows[0].model_copy(
            update={
                "expected_version_id": UUID(stored[0]["version_id"]),
                "attributes": {**rows[0].attributes, "column": "Z"},
            }
        )
    )
    assert query_objects(reader, query).total == 2
    assert query_objects(reader, query.model_copy(update={"known_at": None})).total == 1
