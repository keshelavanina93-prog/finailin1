"""Type groups retain exact schema meaning and share one global query compiler."""

# ruff: noqa:F811
from uuid import UUID, uuid4

import pytest
from test_definition_history import DB, item, retained  # noqa:F401

from finai_api.domain.object_sets import ObjectSetQuery, PropertyFilter, Traversal
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceProposal, ResourceReview
from finai_api.services import ontology_definitions, resources
from finai_api.services.object_sets import query_objects
from finai_api.services.type_group_query import resolve_with_loader
from finai_api.services.workspace import WorkspaceError


def test_group_root_contract_and_semantic_intersection():
    pin = {"resource_id": uuid4(), "version_id": uuid4()}
    assert "type_group" not in ObjectSetQuery(object_type="LegalEntity").model_dump()
    with pytest.raises(ValueError):
        ObjectSetQuery(object_type="LegalEntity", type_group=pin)
    with pytest.raises(ValueError):
        ObjectSetQuery(
            object_type="ObjectTypeGroup",
            type_group=pin,
            interface={**pin, "implementations": [pin]},
        )
    schemas = []
    for kind in ["GroupAlpha", "GroupBeta"]:
        schemas.append(
            {
                "resource_id": uuid4(),
                "version_id": uuid4(),
                "content_hash": "a" * 64,
                "object_type": "SchemaDefinition",
                "authority_state": "APPROVED",
                "identity_key": kind,
                "attributes": {
                    "fields": {
                        "same": {"field_id": str(uuid4()), "kind": "text", "required": True},
                        "changed": {"kind": "text", "semantic_id": str(uuid4())},
                    }
                },
            }
        )
    group = {
        **pin,
        "content_hash": "b" * 64,
        "object_type": "ObjectTypeGroup",
        "authority_state": "APPROVED",
        "attributes": {"definition": {"types": [s["identity_key"] for s in schemas]}},
        "dependencies": [
            {**s, "relation": "DEFINITION_TYPE:" + s["identity_key"]} for s in schemas
        ],
    }
    rows = {r["resource_id"]: r for r in [group, *schemas]}
    binding = resolve_with_loader(pin, lambda identity, version: rows[identity])
    assert binding["fields"] == {"same": {"kind": "text", "required": True}}
    group["dependencies"] = group["dependencies"][:1]
    with pytest.raises(WorkspaceError, match="one exact schema"):
        resolve_with_loader(pin, lambda identity, version: rows[identity])


@DB
def test_native_group_global_page_saved_traversal_and_schema_correction(retained):
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
    reviewer = author.model_copy(update={"actor_id": "synthetic-type-group-checker"})

    def semantic(name):
        return str(canonical_id(reader.scope.tenant_id, "SemanticContract", name))

    def registry(mutations):
        proposal = ResourceProposal(
            title="SYNTHETIC group schema",
            rationale="Isolated reviewed type group schema acceptance",
            access_entity="__PLATFORM__",
            mutations=mutations,
        )
        resources.propose(author, proposal)
        resources.review(
            reviewer,
            proposal.proposal_id,
            ResourceReview(decision="APPROVED", rationale="Independent synthetic schema review"),
        )

    kinds = ["GroupAlpha" + uuid4().hex[:10], "GroupBeta" + uuid4().hex[:10]]
    schemas = [
        item(
            "SchemaDefinition",
            {
                "additional_fields": False,
                "fields": {
                    "number": {
                        "field_id": str(uuid4()),
                        "kind": "decimal",
                        "required": True,
                        "semantic_id": semantic("Amount"),
                    },
                    "company_id": {
                        "field_id": str(uuid4()),
                        "kind": "reference",
                        "required": True,
                        "semantic_id": semantic("CanonicalReference"),
                        "target_type": "LegalEntity",
                    },
                },
            },
        ).model_copy(update={"identity_key": kind})
        for kind in kinds
    ]
    registry(schemas)
    companies = [item("LegalEntity", {}), item("LegalEntity", {})]
    publish(*companies)
    data = [
        item(kind, {"number": number, "company_id": str(company.resource_id)})
        for kind, number, company in [
            (kinds[0], "2", companies[0]),
            (kinds[0], "20", companies[0]),
            (kinds[1], "10", companies[1]),
        ]
    ]
    stored = publish(*data)
    group = item("ObjectTypeGroup", {"definition": {"types": kinds}})
    group_row = publish(group)[0]
    query = ObjectSetQuery(
        object_type="ObjectTypeGroup",
        type_group={"resource_id": group.resource_id, "version_id": group_row["version_id"]},
        filters=[PropertyFilter(field="number", operator="gte", value="10")],
        limit=1,
    )
    first = query_objects(reader, query)
    second = query_objects(reader, first.query.model_copy(update={"offset": 1}))
    assert (
        first.total == second.total == 2 and first.next_offset == 1 and second.next_offset is None
    )
    assert first.objects[0]["resource_id"] != second.objects[0]["resource_id"]
    assert first.counts_by_type == {kinds[0]: 1, kinds[1]: 1}
    assert first.interface_bindings is None and first.interface_values is None
    assert all(v["status"] == "AVAILABLE" for v in first.type_group_values)
    assert "field_id" not in first.type_group_bindings["fields"]["number"]
    traversal = query.model_copy(update={"limit": 10, "traversal": [Traversal(name="company_id")]})
    result = query_objects(reader, traversal)
    assert {o["resource_id"] for o in result.objects} == {str(c.resource_id) for c in companies}
    assert result.type_group_values == []
    saved = item("ObjectSetDefinition", {"definition": traversal.model_dump(mode="json")})
    saved_row = publish(saved)[0]
    rerun = ontology_definitions.run_set(
        reader, saved.resource_id, UUID(saved_row["version_id"]), 0, 10
    )
    assert rerun["total"] == 2 and rerun["type_group_bindings"] == result.type_group_bindings
    assert query_objects(reader, query.model_copy(update={"resource_ids": []})).total == 0
    for condition in [
        PropertyFilter(field="unknown", value="x"),
        PropertyFilter(field="number", operator="gte", value=True),
    ]:
        with pytest.raises(WorkspaceError):
            query_objects(
                reader, query.model_copy(update={"resource_ids": [], "filters": [condition]})
            )
    prior = resources.get_resource(reader, schemas[0].resource_id)["resource"]
    registry(
        [
            schemas[0].model_copy(
                update={
                    "expected_version_id": UUID(prior["version_id"]),
                    "attributes": {
                        **schemas[0].attributes,
                        "fields": {
                            **schemas[0].attributes["fields"],
                            "note": {
                                "field_id": str(uuid4()),
                                "kind": "text",
                                "required": False,
                                "semantic_id": semantic("Text"),
                            },
                        },
                    },
                }
            )
        ]
    )
    publish(data[0].model_copy(update={"expected_version_id": UUID(stored[0]["version_id"])}))
    plain = query_objects(reader, query.model_copy(update={"filters": [], "limit": 10}))
    assert any(v["status"] == "SCHEMA_CHANGED" for v in plain.type_group_values)
    for changed in [query, traversal.model_copy(update={"filters": []})]:
        with pytest.raises(WorkspaceError, match="Type group root schema"):
            query_objects(reader, changed)
