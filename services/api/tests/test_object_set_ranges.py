# ruff: noqa: F811
"""Ordered filters use declared scalar types and preserve exact query evidence."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from test_definition_history import DB, retained  # noqa: F401

from finai_api.domain.object_sets import ObjectSetQuery, PropertyFilter
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceMutation, ResourceProposal, ResourceReview
from finai_api.services import resources
from finai_api.services.object_filter_contract import validate_filters
from finai_api.services.object_sets import query_objects
from finai_api.services.workspace import WorkspaceError


@pytest.mark.parametrize(
    "kind,value",
    [
        ("text", "12"),
        ("integer", True),
        ("decimal", None),
        ("date", "20260101"),
        ("date", "2026-02-30"),
        ("datetime", "2026-01-01T00:00:00"),
        ("decimal", "Infinity"),
    ],
)
def test_invalid_ordered_scalars_refused(kind, value):
    with pytest.raises(WorkspaceError):
        validate_filters(
            [PropertyFilter(field="value", value=value, operator="gte")], {"value": {"kind": kind}}
        )


def test_equality_serialization_unchanged():
    assert PropertyFilter(field="count", value=7, operator="eq").model_dump() == {
        "field": "count",
        "value": 7,
    }


@DB
def test_native_exact_ranges_dates_offsets_nulls_and_scope(retained):
    reader, _ = retained
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
    kind = "RangeFixture" + uuid4().hex[:12]
    start = datetime(2026, 1, 1, tzinfo=UTC)
    fields = {
        name: {
            "field_id": str(uuid4()),
            "kind": scalar,
            "required": False,
            "semantic_id": str(canonical_id(reader.scope.tenant_id, "SemanticContract", semantic)),
        }
        for name, scalar, semantic in [
            ("number", "decimal", "Amount"),
            ("count", "integer", "Count"),
            ("day", "date", "Date"),
            ("instant", "datetime", "Time"),
        ]
    }
    schema = ResourceMutation(
        object_type="SchemaDefinition",
        identity_key=kind,
        display_name="SYNTHETIC ordered schema",
        attributes={"additional_fields": False, "fields": fields},
        access_entity="__PLATFORM__",
        valid_from=start,
    )
    rows = [
        ResourceMutation(
            object_type=kind,
            identity_key=uuid4().hex,
            display_name=f"SYNTHETIC ordered {index}",
            access_entity=reader.scope.legal_entity_id,
            valid_from=start,
            attributes=attrs,
            evidence_class="REFERENCE_TEMPLATE",
        )
        for index, attrs in enumerate(
            [
                {
                    "number": "2.0000000000000000001",
                    "count": 2,
                    "day": "2026-01-01",
                    "instant": "2026-01-01T04:00:00+04:00",
                },
                {
                    "number": "10",
                    "count": 10,
                    "day": "2026-01-02",
                    "instant": "2026-01-01T00:00:01Z",
                },
                {},
            ]
        )
    ]
    proposal = ResourceProposal(
        title="Synthetic ordered query fixtures",
        rationale="Exact typed query verification",
        access_entity="__TENANT__",
        mutations=[schema, *rows],
    )
    resources.propose(author, proposal)
    resources.review(
        author.model_copy(update={"actor_id": "synthetic-range-reviewer"}),
        proposal.proposal_id,
        ResourceReview(decision="APPROVED", rationale="Independent synthetic typed range review"),
    )
    frozen = datetime.now(UTC)

    def query(field, value, operator="gte", principal=reader):
        return query_objects(
            principal,
            ObjectSetQuery(
                object_type=kind,
                known_at=frozen,
                filters=[PropertyFilter(field=field, value=value, operator=operator)],
            ),
        )

    assert query("number", "2.0000000000000000000", "gt").total == 2
    assert query("number", "2.0000000000000000001", "gt").total == 1
    assert query("count", 10, "lte").total == 2
    assert query("day", "2026-01-02", "lt").total == 1
    assert query("instant", "2026-01-01T00:00:00Z", "lte").total == 1
    with pytest.raises(WorkspaceError, match="representation"):
        query("number", "1e999999999")
    with pytest.raises(WorkspaceError):
        query("day", "2026-02-30")
    hidden = reader.model_copy(
        update={
            "scope": reader.scope.model_copy(update={"legal_entity_id": "other-" + uuid4().hex})
        }
    )
    assert query("count", 0, principal=hidden).total == 0
    # Schema kind reinterpretation itself remains blocked by reviewed compatibility.
    current_schema = resources.get_resource(reader, schema.resource_id)["resource"]
    changed_fields = {
        **fields,
        "number": {
            **fields["number"],
            "kind": "text",
            "semantic_id": str(canonical_id(reader.scope.tenant_id, "SemanticContract", "Text")),
        },
    }
    incompatible = schema.model_copy(
        update={
            "expected_version_id": UUID(current_schema["version_id"]),
            "attributes": {"additional_fields": False, "fields": changed_fields},
        }
    )
    with pytest.raises(WorkspaceError):
        resources.propose(
            author,
            ResourceProposal(
                title="Synthetic incompatible ordered schema",
                rationale="Reject reinterpretation of exact typed values",
                access_entity="__TENANT__",
                mutations=[incompatible],
            ),
        )
    assert query("number", "2", "gt").total == 2
