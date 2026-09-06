"""Canonical typed filters cannot turn operator mistakes into empty analytical sets."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from test_definition_history import DB
from test_definition_history import retained as retained

from finai_api.domain.object_sets import ObjectSetQuery, PropertyFilter
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceMutation, ResourceProposal, ResourceReview
from finai_api.services import resources
from finai_api.services.object_filter_contract import validate_filters
from finai_api.services.object_sets import query_objects
from finai_api.services.ontology_definition_validation import validate_definition
from finai_api.services.ontology_definitions import definition, run_set
from finai_api.services.temporal_definition_dependency import TemporalDependencyUnavailable
from finai_api.services.workspace import WorkspaceError


@pytest.mark.parametrize(
    "kind,value",
    [
        ("integer", True),
        ("integer", "1"),
        ("boolean", "true"),
        ("reference", "not-an-id"),
        ("date", "2026-02-30"),
        ("datetime", "2026-01-01T00:00:00"),
        ("decimal", "NaN"),
        ("text", 1),
    ],
)
def test_filter_values_use_canonical_scalar_validation(kind, value):
    with pytest.raises(WorkspaceError, match="requires a canonical"):
        validate_filters([PropertyFilter(field="value", value=value)], {"value": {"kind": kind}})


def test_null_does_not_bypass_required_property_contract():
    query = [PropertyFilter(field="value", value=None)]
    validate_filters(query, {"value": {"kind": "text", "required": False}})
    with pytest.raises(WorkspaceError, match="requires a canonical"):
        validate_filters(query, {"value": {"kind": "text", "required": True}})


def test_historical_incoming_traversal_ignores_types_not_yet_known():
    schema_ids = {name: str(uuid4()) for name in ("LegalEntity", "Chart", "FutureType")}
    inverse = {value: name for name, value in schema_ids.items()}
    saved = ResourceMutation(
        object_type="ObjectSetDefinition",
        identity_key=uuid4().hex,
        display_name="Historical incoming references",
        valid_from=datetime.now(UTC),
        attributes={
            "definition": {
                "object_type": "LegalEntity",
                "known_at": "2026-01-01T00:00:00Z",
                "traversal": [{"kind": "reference", "direction": "incoming", "name": "owner"}],
            }
        },
    )

    def target(identifier, source, relation):
        name = inverse[identifier]
        if name == "FutureType":
            raise TemporalDependencyUnavailable()
        return {
            "attributes": {
                "fields": {"owner": {"kind": "reference", "target_type": "LegalEntity"}}
                if name == "Chart"
                else {}
            }
        }

    validate_definition(saved, schema_ids, {}, target)


@DB
def test_query_and_saved_definition_share_effective_and_known_schema_contract(
    retained, monkeypatch
):
    reader, _ = retained
    operator = reader.model_copy(
        update={
            "permissions": (
                "ontology_read",
                "ontology_admin",
                "ontology_propose",
                "ontology_review",
            )
        }
    )
    reviewer = operator.model_copy(update={"actor_id": "synthetic-filter-reviewer"})

    def publish(*items):
        proposal = ResourceProposal(
            title="Synthetic typed query contract",
            rationale="Synthetic schema time validation",
            access_entity="__TENANT__",
            mutations=[
                value.model_copy(
                    update={
                        "access_entity": "__PLATFORM__"
                        if value.object_type == "SchemaDefinition"
                        else reader.scope.legal_entity_id
                    }
                )
                for value in items
            ],
        )
        resources.propose(operator, proposal)
        resources.review(
            reviewer,
            proposal.proposal_id,
            ResourceReview(
                decision="APPROVED", rationale="Independent synthetic typed query validation"
            ),
        )
        return [resources.get_resource(reader, value.resource_id)["resource"] for value in items]

    kind = "FilterContract" + uuid4().hex[:10]
    tenant = reader.scope.tenant_id
    start = datetime(2026, 1, 1, tzinfo=UTC)

    def field(kind, semantic, required=False):
        return {
            "field_id": str(uuid4()),
            "kind": kind,
            "required": required,
            "semantic_id": str(canonical_id(tenant, "SemanticContract", semantic)),
        }

    schema = ResourceMutation(
        object_type="SchemaDefinition",
        identity_key=kind,
        display_name="Synthetic filter schema",
        valid_from=start,
        attributes={
            "additional_fields": False,
            "fields": {"count": field("integer", "Count", True)},
        },
    )
    record = ResourceMutation(
        object_type=kind,
        identity_key=uuid4().hex,
        display_name="Synthetic filter subject",
        valid_from=start,
        attributes={"count": 7},
        evidence_class="REFERENCE_TEMPLATE",
    )
    first, _ = publish(schema, record)
    known_first = datetime.now(UTC)
    good = ObjectSetQuery(object_type=kind, filters=[PropertyFilter(field="count", value=7)])
    result = query_objects(reader, good)
    assert result.total == 1
    assert result.objects[0]["resource_id"] == str(record.resource_id)
    assert result.filter_schema_versions[0].version_id == UUID(first["version_id"])
    for bad in (PropertyFilter(field="typo", value=7), PropertyFilter(field="count", value="7")):
        with pytest.raises(WorkspaceError):
            query_objects(reader, good.model_copy(update={"filters": [bad]}))
        saved = ResourceMutation(
            object_type="ObjectSetDefinition",
            identity_key=uuid4().hex,
            display_name="Synthetic invalid filter definition",
            valid_from=start,
            attributes={"definition": {"object_type": kind, "filters": [bad.model_dump()]}},
        )
        with pytest.raises(WorkspaceError):
            publish(saved)
    future = datetime.now(UTC) + timedelta(days=30)
    fields = {**schema.attributes["fields"], "future_label": field("text", "Text")}
    updated = schema.model_copy(
        update={
            "expected_version_id": UUID(first["version_id"]),
            "valid_from": future,
            "attributes": {"additional_fields": False, "fields": fields},
        }
    )
    second = publish(updated)[0]
    later = ObjectSetQuery(
        object_type=kind,
        filters=[PropertyFilter(field="future_label", value="x")],
        valid_at=future + timedelta(days=1),
    )
    with pytest.raises(WorkspaceError, match="undeclared"):
        query_objects(reader, later.model_copy(update={"known_at": known_first}))
    with pytest.raises(WorkspaceError, match="undeclared"):
        query_objects(reader, later.model_copy(update={"valid_at": datetime.now(UTC)}))
    after = query_objects(reader, later)
    assert after.total == 0  # A valid filter with no matches is a genuine empty set.
    assert after.filter_schema_versions[0].version_id == UUID(second["version_id"])
    # Publication after a schema correction must bind the query's original schema,
    # not the latest head, when its effective and knowledge times are fixed.
    frozen = ResourceMutation(
        object_type="ObjectSetDefinition",
        identity_key=uuid4().hex,
        display_name="Synthetic frozen typed query",
        valid_from=start,
        attributes={
            "definition": good.model_copy(
                update={
                    "valid_at": start,
                    "known_at": known_first,
                }
            ).model_dump(mode="json")
        },
    )
    frozen_version = publish(frozen)[0]
    accepted = definition(reader, frozen.resource_id)
    schema_pin = next(
        value
        for value in accepted["dependencies"]
        if value["relation"] == f"DEFINITION_TYPE:{kind}"
    )
    assert str(schema_pin["version_id"]) == first["version_id"]
    replay = run_set(reader, frozen.resource_id, UUID(frozen_version["version_id"]), 0, 50)
    assert replay["total"] == 1
    assert replay["filter_schema_versions"][0]["version_id"] == first["version_id"]
    invalid_frozen = frozen.model_copy(
        update={
            "resource_id": uuid4(),
            "identity_key": uuid4().hex,
            "attributes": {
                "definition": later.model_copy(
                    update={
                        "known_at": known_first,
                    }
                ).model_dump(mode="json")
            },
        }
    )
    with pytest.raises(WorkspaceError, match="undeclared"):
        publish(invalid_frozen)
    # A fixed knowledge boundary with a moving business date can cross an already
    # known future schema between proposal and review without any head change.
    moving = frozen.model_copy(
        update={
            "resource_id": uuid4(),
            "identity_key": uuid4().hex,
            "access_entity": reader.scope.legal_entity_id,
            "attributes": {
                "definition": good.model_copy(
                    update={
                        "known_at": datetime.now(UTC),
                        "valid_at": None,
                    }
                ).model_dump(mode="json")
            },
        }
    )
    pending = ResourceProposal(
        title="Synthetic moving business time",
        rationale="Verify exact reviewed temporal pins",
        access_entity="__TENANT__",
        mutations=[moving],
    )
    resources.propose(operator, pending)

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return future + timedelta(days=1)

    with monkeypatch.context() as context:
        context.setattr(resources, "datetime", Later)
        with pytest.raises(WorkspaceError, match="Reviewed dependency versions changed"):
            resources.review(
                reviewer,
                pending.proposal_id,
                ResourceReview(
                    decision="APPROVED", rationale="Review after effective schema boundary"
                ),
            )
    assert resources.proposal_detail(operator, pending.proposal_id).decision is None
