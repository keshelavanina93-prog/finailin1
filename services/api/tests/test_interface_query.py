"""Native exact interfaces share one globally paged canonical query compiler."""

# ruff: noqa:F811
from uuid import UUID, uuid4

import pytest
from test_definition_history import DB, item, retained  # noqa:F401

from finai_api.domain.object_sets import InterfaceRoot, ObjectSetQuery, PropertyFilter, Traversal
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceProposal, ResourceReview
from finai_api.services import resources
from finai_api.services.object_sets import query_objects
from finai_api.services.workspace import WorkspaceError


def test_interface_root_pins_and_legacy_serialization():
    pin = {"resource_id": str(uuid4()), "version_id": str(uuid4())}
    with pytest.raises(ValueError):
        InterfaceRoot(**pin, implementations=[pin, pin])
    with pytest.raises(ValueError):
        ObjectSetQuery(object_type="LegalEntity", interface={**pin, "implementations": [pin]})
    assert "interface" not in ObjectSetQuery(object_type="LegalEntity").model_dump()


@DB
def test_native_interface_aliases_global_page_traversal_and_schema_refusal(retained):
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
    reviewer = author.model_copy(update={"actor_id": "synthetic-interface-checker"})

    def semantic(name):
        return str(canonical_id(reader.scope.tenant_id, "SemanticContract", name))

    kinds = ["InterfaceAlpha" + uuid4().hex[:10], "InterfaceBeta" + uuid4().hex[:10]]
    field_names = [("number", "company_id"), ("quantity", "owner_id")]
    schemas = []
    for kind, (amount, owner) in zip(kinds, field_names, strict=True):
        schemas.append(
            item(
                "SchemaDefinition",
                {
                    "additional_fields": False,
                    "fields": {
                        amount: {
                            "field_id": str(uuid4()),
                            "kind": "decimal",
                            "required": True,
                            "semantic_id": semantic("Amount"),
                        },
                        owner: {
                            "field_id": str(uuid4()),
                            "kind": "reference",
                            "required": True,
                            "semantic_id": semantic("CanonicalReference"),
                            "target_type": "LegalEntity",
                        },
                    },
                },
            ).model_copy(update={"identity_key": kind})
        )

    def registry(mutations):
        proposal = ResourceProposal(
            title="Synthetic executable interface schema",
            rationale="Isolated canonical interface query acceptance",
            access_entity="__PLATFORM__",
            mutations=mutations,
        )
        resources.propose(author, proposal)
        resources.review(
            reviewer,
            proposal.proposal_id,
            ResourceReview(decision="APPROVED", rationale="Independent synthetic schema review"),
        )

    registry(schemas)
    company_a, company_b = item("LegalEntity", {}), item("LegalEntity", {})
    publish(company_a, company_b)
    interface = item(
        "ObjectInterface",
        {
            "definition": {
                "fields": {
                    "measure": {
                        "kind": "decimal",
                        "required": True,
                        "semantic_id": semantic("Amount"),
                    },
                    "owner": {
                        "kind": "reference",
                        "required": True,
                        "semantic_id": semantic("CanonicalReference"),
                        "target_type": "LegalEntity",
                    },
                }
            }
        },
    )
    interface_row = publish(interface)[0]
    implementations = [
        item(
            "ObjectTypeImplementation",
            {
                "interface_id": str(interface.resource_id),
                "schema_id": str(schema.resource_id),
                "definition": {"fields": {"measure": names[0], "owner": names[1]}},
            },
        )
        for schema, names in zip(schemas, field_names, strict=True)
    ]
    impl_rows = publish(*implementations)
    rows = [
        item(kinds[0], {"number": "2", "company_id": str(company_a.resource_id)}),
        item(kinds[0], {"number": "20", "company_id": str(company_a.resource_id)}),
        item(kinds[1], {"quantity": "10", "owner_id": str(company_b.resource_id)}),
    ]
    stored = publish(*rows)
    selected = InterfaceRoot(
        resource_id=interface.resource_id,
        version_id=interface_row["version_id"],
        implementations=[
            {"resource_id": row["resource_id"], "version_id": row["version_id"]}
            for row in impl_rows
        ],
    )
    query = ObjectSetQuery(
        object_type="ObjectInterface",
        interface=selected,
        limit=1,
        filters=[PropertyFilter(field="measure", value="10", operator="gte")],
    )
    first = query_objects(reader, query)
    assert first.total == 2 and first.next_offset == 1
    assert first.interface_values[0]["status"] == "AVAILABLE"
    second = query_objects(reader, first.query.model_copy(update={"offset": 1}))
    assert second.total == 2 and second.next_offset is None
    assert first.objects[0]["version_id"] != second.objects[0]["version_id"]
    assert {
        first.interface_values[0]["values"]["measure"],
        second.interface_values[0]["values"]["measure"],
    } == {"10", "20"}
    assert len(first.interface_bindings["implementations"]) == 2
    reached = query_objects(
        reader, query.model_copy(update={"traversal": [Traversal(name="owner")], "limit": 10})
    )
    assert {o["resource_id"] for o in reached.objects} == {
        str(company_a.resource_id),
        str(company_b.resource_id),
    }
    assert reached.total == 2 and reached.interface_values == []
    from finai_api.services.ontology_definitions import run_set

    saved = item(
        "ObjectSetDefinition",
        {
            "definition": query.model_copy(
                update={"traversal": [Traversal(name="owner")], "limit": 10}
            ).model_dump(mode="json")
        },
    )
    saved_row = publish(saved)[0]
    saved_result = run_set(reader, saved.resource_id, UUID(saved_row["version_id"]), 0, 10)
    assert (
        saved_result["total"] == 2
        and saved_result["interface_bindings"] == reached.interface_bindings
    )
    assert (
        query_objects(
            reader,
            query.model_copy(
                update={
                    "filters": [PropertyFilter(field="owner", value=str(company_b.resource_id))]
                }
            ),
        ).total
        == 1
    )
    for filters in [
        [PropertyFilter(field="number", value="10")],
        [PropertyFilter(field="measure", operator="gte", value=True)],
    ]:
        with pytest.raises(WorkspaceError):
            query_objects(reader, query.model_copy(update={"resource_ids": [], "filters": filters}))
    wrong = selected.model_copy(update={"version_id": uuid4()})
    with pytest.raises(WorkspaceError):
        query_objects(reader, query.model_copy(update={"interface": wrong}))
    duplicate = item("ObjectTypeImplementation", implementations[0].attributes)
    duplicate_row = publish(duplicate)[0]
    ambiguous = InterfaceRoot(
        resource_id=selected.resource_id,
        version_id=selected.version_id,
        implementations=[
            selected.implementations[0],
            {
                "resource_id": duplicate_row["resource_id"],
                "version_id": duplicate_row["version_id"],
            },
        ],
    )
    with pytest.raises(WorkspaceError, match="ambiguous"):
        query_objects(reader, query.model_copy(update={"interface": ambiguous}))
    # Changed data schema must be explicit, even if a similarly named property remains.
    prior = resources.get_resource(reader, schemas[0].resource_id)["resource"]
    fields = {
        **schemas[0].attributes["fields"],
        "note": {
            "field_id": str(uuid4()),
            "kind": "text",
            "required": False,
            "semantic_id": semantic("Text"),
        },
    }
    registry(
        [
            schemas[0].model_copy(
                update={
                    "expected_version_id": UUID(prior["version_id"]),
                    "attributes": {**schemas[0].attributes, "fields": fields},
                }
            )
        ]
    )
    publish(rows[0].model_copy(update={"expected_version_id": UUID(stored[0]["version_id"])}))
    plain = query_objects(reader, query.model_copy(update={"filters": [], "limit": 10}))
    assert any(
        row["status"] == "SCHEMA_CHANGED" and row["values"] is None
        for row in plain.interface_values
    )
    with pytest.raises(WorkspaceError, match="Interface root schema"):
        query_objects(reader, query)
    with pytest.raises(WorkspaceError, match="Interface root schema"):
        query_objects(
            reader, query.model_copy(update={"filters": [], "traversal": [Traversal(name="owner")]})
        )
