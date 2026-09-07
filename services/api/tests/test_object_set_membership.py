"""Exact stored membership uses the canonical query pipeline at every root and hop."""

# ruff: noqa: F811
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from test_definition_history import DB, item, retained  # noqa: F401

from finai_api.domain.object_sets import ObjectSetQuery, PropertyFilter, Traversal
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceProposal, ResourceReview
from finai_api.services import ontology_definitions, resources
from finai_api.services.object_filter_contract import validate_filters
from finai_api.services.object_sets import query_objects
from finai_api.services.workspace import WorkspaceError


@pytest.mark.parametrize(
    "value", [[], ["Y", "Y"], [1, True], [1, "1"], [None], "Y", list(range(101))]
)
def test_membership_shape(value):
    with pytest.raises(ValueError):
        PropertyFilter(field="column", operator="in", value=value)


def test_scalar_legacy_and_shared_budget():
    assert PropertyFilter(field="x", value=None).model_dump() == {"field": "x", "value": None}
    for operator in ["eq", "lt", "lte", "gt", "gte"]:
        with pytest.raises(ValueError):
            PropertyFilter(field="x", operator=operator, value=["Y"])
    with pytest.raises(ValueError, match="100-value"):
        ObjectSetQuery(
            object_type="LegalEntity",
            filters=[PropertyFilter(field="x", operator="in", value=list(range(60)))],
            traversal=[
                Traversal(
                    name="owner",
                    filters=[PropertyFilter(field="x", operator="not_in", value=list(range(41)))],
                )
            ],
        )


@pytest.mark.parametrize(
    "kind,value",
    [
        ("integer", ["1"]),
        ("boolean", [1]),
        ("reference", ["bad-uuid"]),
        ("date", ["2026-02-30"]),
        ("datetime", ["2026-01-01T00:00:00"]),
        ("decimal", ["NaN"]),
        ("money", ["1"]),
    ],
)
def test_membership_schema(kind, value):
    with pytest.raises(WorkspaceError):
        validate_filters(
            [PropertyFilter(field="x", operator="in", value=value)], {"x": {"kind": kind}}
        )


@DB
def test_native_membership_roots_aliases_hops_saved_time_and_page(retained):
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
    kind = "MembershipFixture" + uuid4().hex[:10]

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
    filters = [PropertyFilter(field="column", operator="in", value=["Y", "AA"])]
    query = ObjectSetQuery(object_type=kind, filters=filters, known_at=frozen, limit=1)
    first = query_objects(reader, query)
    second = query_objects(reader, first.query.model_copy(update={"offset": 1}))
    assert (
        first.total == second.total == 2 and first.next_offset == 1 and second.next_offset is None
    )
    assert {first.objects[0]["resource_id"], second.objects[0]["resource_id"]} == {
        str(rows[0].resource_id),
        str(rows[1].resource_id),
    }
    excluded = query_objects(
        reader,
        query.model_copy(
            update={
                "filters": [PropertyFilter(field="column", operator="not_in", value=["Y", "AA"])]
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
            traversal=[Traversal(name="owner", direction="incoming", filters=filters)],
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
            filters=filters,
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
        filters=[PropertyFilter(field="classification", operator="in", value=["Y", "AA"])],
    )
    assert query_objects(reader, mapped).total == 2
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


@DB
def test_native_membership_null_and_old_schema_are_excluded(retained):
    """SQL-only historical row shapes; canonical publication disallows explicit nulls."""
    from psycopg.types.json import Jsonb

    from finai_api.services.object_sets import _filter_sql

    reader, _ = retained
    text_schema, old_schema = uuid4(), uuid4()
    current_fields = {"fields": {"column": {"kind": "text", "required": False}}}
    old_fields = {"fields": {"column": {"kind": "integer", "required": False}}}
    with resources.resource_connection(reader) as conn:
        for operator, expected in [("in", ["Y"]), ("not_in", ["Z"])]:
            args = []
            predicate = _filter_sql(
                [PropertyFilter(field="column", operator=operator, value=["Y"])],
                "candidate",
                "schemas",
                args,
            )
            result = conn.execute(
                "WITH versions(version_id,object_type,authority_state,attributes) AS "
                "(VALUES (%s::uuid,'SchemaDefinition','APPROVED',%s::jsonb),"
                "(%s::uuid,'SchemaDefinition','APPROVED',%s::jsonb)), "
                "schemas(identity_key,authority_state,attributes) AS "
                "(VALUES ('Fixture','APPROVED',%s::jsonb)), "
                "candidate(schema_version_id,object_type,attributes) AS "
                "(VALUES (%s::uuid,'Fixture','{\"column\":\"Y\"}'::jsonb),"
                "(%s::uuid,'Fixture','{\"column\":\"Z\"}'::jsonb),"
                "(%s::uuid,'Fixture','{\"column\":null}'::jsonb),"
                "(%s::uuid,'Fixture','{}'::jsonb),"
                "(%s::uuid,'Fixture','{\"column\":7}'::jsonb)) "
                "SELECT attributes->>'column' FROM candidate WHERE true" + predicate,
                [
                    text_schema,
                    Jsonb(current_fields),
                    old_schema,
                    Jsonb(old_fields),
                    Jsonb(current_fields),
                    text_schema,
                    text_schema,
                    text_schema,
                    text_schema,
                    old_schema,
                    *args,
                ],
            ).fetchall()
            assert [row[0] for row in result] == expected
