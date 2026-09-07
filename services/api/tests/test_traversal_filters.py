"""Typed stage predicates operate on retained dependency targets, not current heads."""

# ruff: noqa: F811
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from test_definition_history import DB, item, retained  # noqa:F401

from finai_api.domain.object_sets import ObjectSetQuery, PropertyFilter, Traversal
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceProposal, ResourceReview
from finai_api.services import resources
from finai_api.services.object_sets import query_objects
from finai_api.services.workspace import WorkspaceError


def test_legacy_omission_and_shared_predicate_bound():
    assert Traversal(name="parent_id", filters=[]).model_dump() == {
        "kind": "reference",
        "name": "parent_id",
        "direction": "outgoing",
    }
    with pytest.raises(ValueError):
        ObjectSetQuery(
            object_type="LegalEntity",
            filters=[PropertyFilter(field="name", value="a")] * 20,
            traversal=[
                Traversal(name="parent_id", filters=[PropertyFilter(field="name", value="b")])
            ],
        )


@DB
def test_discovery_does_not_bind_unrelated_withdrawn_schema(retained):
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
    reviewer = author.model_copy(update={"actor_id": "synthetic-discovery-checker"})
    unrelated = item(
        "SchemaDefinition",
        {
            "additional_fields": False,
            "fields": {
                "label": {
                    "field_id": str(uuid4()),
                    "kind": "text",
                    "required": False,
                    "semantic_id": str(
                        canonical_id(reader.scope.tenant_id, "SemanticContract", "Text")
                    ),
                }
            },
        },
    ).model_copy(update={"identity_key": "UnrelatedDiscovery" + uuid4().hex[:12]})
    registry = ResourceProposal(
        title="Synthetic unrelated discovery schema",
        rationale="Verify nonmaterial discovery does not contaminate query lineage",
        access_entity="__PLATFORM__",
        mutations=[unrelated],
    )
    resources.propose(author, registry)
    resources.review(
        reviewer,
        registry.proposal_id,
        ResourceReview(decision="APPROVED", rationale="Independent synthetic schema review"),
    )
    version = resources.get_resource(reader, unrelated.resource_id)["resource"]["version_id"]
    from finai_api.domain.resource_lifecycle import (
        LifecycleRequest,
        LifecycleReview,
        VersionReference,
    )
    from finai_api.services import resource_lifecycle

    ref = VersionReference(resource_id=unrelated.resource_id, version_id=version)
    event = None
    for state in ["OBSERVED", "REVOKED"]:
        request = LifecycleRequest(
            subject=ref,
            expected_event_id=event,
            target_state=state,
            epistemic_state="OBSERVED",
            business_state="PROVISIONAL",
            availability_state="AVAILABLE",
            reason="Withdraw this isolated synthetic discovery-only schema",
        )
        resource_lifecycle.request_transition(author, request)
        resource_lifecycle.review_transition(
            reviewer,
            request.request_id,
            LifecycleReview(decision="APPROVED", reason="Independent synthetic-only withdrawal"),
        )
        event = resource_lifecycle.history(author, ref)["events"][-1]["event_id"]
    now = datetime.now(UTC)
    query = ObjectSetQuery(
        object_type="DimensionMember",
        known_at=now,
        valid_at=now,
        traversal=[Traversal(name="member_id", direction="incoming")],
    )
    saved = item("ObjectSetDefinition", {"definition": query.model_dump(mode="json")})
    canonical = publish(saved)[0]
    with resources.resource_connection(reader) as conn:
        deps = conn.execute(
            "SELECT target_resource_id,target_version_id,relation FROM resource_dependencies "
            "WHERE tenant_id=%s AND version_id=%s",
            (reader.scope.tenant_id, canonical["version_id"]),
        ).fetchall()
        assert not any(str(row[0]) == str(unrelated.resource_id) for row in deps)
        assert not any(row[2].startswith("TRAVERSAL_CANDIDATE:") for row in deps)
        match = canonical_id(
            reader.scope.tenant_id, "SchemaDefinition", "SourceDimensionAssignment"
        )
        assert any(
            row[0] == match and row[2] == "DEFINITION_TYPE:SourceDimensionAssignment"
            for row in deps
        )
    assert resource_lifecycle.history(author, ref)["state"]["target_state"] == "REVOKED"


@DB
def test_native_filtered_hops_exact_corrections_paging_and_empty_validation(retained):
    reader, publish = retained
    kind = "HopFixture" + uuid4().hex[:12]
    schema = item(
        "SchemaDefinition",
        {
            "additional_fields": False,
            "fields": {
                "period_id": {
                    "field_id": str(uuid4()),
                    "kind": "reference",
                    "required": True,
                    "target_type": "FiscalPeriod",
                    "semantic_id": str(
                        canonical_id(
                            reader.scope.tenant_id, "SemanticContract", "CanonicalReference"
                        )
                    ),
                }
            },
        },
    ).model_copy(update={"identity_key": kind})
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
    proposal = ResourceProposal(
        title="Synthetic traversal schema",
        rationale="Isolated typed traversal fixture schema",
        access_entity="__PLATFORM__",
        mutations=[schema],
    )
    resources.propose(author, proposal)
    resources.review(
        author.model_copy(update={"actor_id": "synthetic-hop-reviewer"}),
        proposal.proposal_id,
        ResourceReview(decision="APPROVED", rationale="Independent synthetic schema review"),
    )
    calendars = [
        item("FiscalCalendar", {"code": code})
        for code in ["SYNTHETIC-A", "SYNTHETIC-B", "SYNTHETIC-C"]
    ]
    periods = [
        item(
            "FiscalPeriod",
            {"calendar_id": str(calendar.resource_id), "starts_on": start, "ends_on": "2026-12-31"},
        ).model_copy(update={"display_name": f"SYNTHETIC period {index}"})
        for index, (calendar, start) in enumerate(
            zip(calendars, ["2026-01-01", "2026-01-02", "2026-02-01"], strict=True)
        )
    ]
    roots = [item(kind, {"period_id": str(period.resource_id)}) for period in periods]
    published = publish(*calendars, *periods, *roots)
    original = published[3]
    before = datetime.now(UTC)
    steps = [
        Traversal(
            name="period_id",
            filters=[PropertyFilter(field="starts_on", operator="lt", value="2026-02-01")],
        )
    ]
    query = ObjectSetQuery(object_type=kind, traversal=steps, limit=1)
    first = query_objects(reader, query)
    assert first.total == 2 and first.next_offset == 1 and len(first.objects) == 1
    assert first.traversal_schema_versions[0].step == 1
    assert first.traversal_schema_versions[0].object_type == "FiscalPeriod"
    second = query_objects(reader, first.query.model_copy(update={"offset": 1}))
    assert second.total == 2 and second.next_offset is None
    assert first.objects[0]["version_id"] != second.objects[0]["version_id"]
    path = query.model_copy(
        update={
            "traversal": [
                *steps,
                Traversal(
                    name="calendar_id", filters=[PropertyFilter(field="code", value="SYNTHETIC-A")]
                ),
            ]
        }
    )
    reached = query_objects(reader, path)
    assert reached.total == 1 and reached.objects[0]["resource_id"] == str(calendars[0].resource_id)
    assert [p.step for p in reached.traversal_schema_versions] == [1, 2]
    publish(
        periods[0].model_copy(
            update={
                "expected_version_id": UUID(original["version_id"]),
                "attributes": {**periods[0].attributes, "starts_on": "2026-03-01"},
            }
        )
    )
    current = query_objects(reader, path)
    assert current.total == 1 and current.objects == reached.objects
    frozen = query_objects(reader, path.model_copy(update={"known_at": before, "valid_at": before}))
    assert frozen.objects == reached.objects
    saved = item("ObjectSetDefinition", {"definition": path.model_dump(mode="json")})
    publish(saved)
    for field, value in [("code", "x"), ("starts_on", "2026-02-30")]:
        invalid = query.model_copy(
            update={
                "resource_ids": [],
                "traversal": [
                    Traversal(
                        name="period_id",
                        filters=[PropertyFilter(field=field, operator="gte", value=value)],
                    )
                ],
            }
        )
        with pytest.raises(WorkspaceError):
            query_objects(reader, invalid)
        with pytest.raises(WorkspaceError):
            publish(item("ObjectSetDefinition", {"definition": invalid.model_dump(mode="json")}))

    # A newly declared property must not reinterpret an old reached object's schema.
    old_schema = resources.get_resource(reader, schema.resource_id)["resource"]
    extra = {
        **schema.attributes["fields"],
        "observed_day": {
            "field_id": str(uuid4()),
            "kind": "date",
            "required": False,
            "semantic_id": str(canonical_id(reader.scope.tenant_id, "SemanticContract", "Date")),
        },
    }
    wrapper_kind = "HopWrapper" + uuid4().hex[:12]
    wrapper_schema = item(
        "SchemaDefinition",
        {
            "additional_fields": False,
            "fields": {
                "item_id": {
                    "field_id": str(uuid4()),
                    "kind": "reference",
                    "required": True,
                    "target_type": kind,
                    "semantic_id": str(
                        canonical_id(
                            reader.scope.tenant_id, "SemanticContract", "CanonicalReference"
                        )
                    ),
                }
            },
        },
    ).model_copy(update={"identity_key": wrapper_kind})
    update = ResourceProposal(
        title="Synthetic traversal schema evolution",
        rationale="Prove no reinterpretation of retained target schema",
        access_entity="__PLATFORM__",
        mutations=[
            schema.model_copy(
                update={
                    "expected_version_id": UUID(old_schema["version_id"]),
                    "attributes": {**schema.attributes, "fields": extra},
                }
            ),
            wrapper_schema,
        ],
    )
    resources.propose(author, update)
    resources.review(
        author.model_copy(update={"actor_id": "synthetic-hop-reviewer"}),
        update.proposal_id,
        ResourceReview(decision="APPROVED", rationale="Independent synthetic schema evolution"),
    )
    wrapper = item(wrapper_kind, {"item_id": str(roots[0].resource_id)})
    publish(wrapper)
    with pytest.raises(WorkspaceError, match=r"schema.*step 1"):
        query_objects(
            reader,
            ObjectSetQuery(
                object_type=wrapper_kind,
                traversal=[
                    Traversal(
                        name="item_id",
                        filters=[
                            PropertyFilter(field="observed_day", value="2026-01-01", operator="gte")
                        ],
                    )
                ],
            ),
        )
