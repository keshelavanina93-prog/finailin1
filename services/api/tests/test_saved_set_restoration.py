"""Saved query restoration reuses canonical proposal authority and immutable execution history."""

# ruff: noqa: F811
from datetime import UTC, datetime
from uuid import UUID

import pytest
from test_definition_history import DB, item, retained  # noqa:F401

from finai_api.domain.resources import ResourceReview
from finai_api.services import ontology_definitions, resources, source_documents
from finai_api.services.resource_rollback import RollbackRequest, rollback_draft
from finai_api.services.workspace import WorkspaceError


@DB
def test_native_saved_set_restoration_execution_cas_and_history(retained):
    reader, publish = retained
    author = reader.model_copy(
        update={"permissions": ("read", "ontology_read", "ontology_propose", "ingest")}
    )
    reviewer = reader.model_copy(
        update={
            "actor_id": "synthetic-set-restoration-checker",
            "permissions": ("read", "ontology_read", "ontology_review"),
        }
    )
    doc = source_documents.retain_document(
        author,
        "SYNTHETIC restoration classification.txt",
        b"Synthetic classifications: A and B. No authentic source claim.",
    )
    evidence = item(
        "SourceEvidence", {"sha256": doc["sha256"], "source_system": "SYNTHETIC"}
    ).model_copy(update={"evidence_class": "SOURCE_BOUND"})
    dimension = item(
        "DimensionDefinition",
        {"code": "SYNTHETIC-RESTORATION", "evidence_id": str(evidence.resource_id)},
    ).model_copy(update={"evidence_class": "SOURCE_BOUND"})
    members = [
        item(
            "DimensionMember",
            {
                "code": code,
                "dimension_id": str(dimension.resource_id),
                "evidence_id": str(evidence.resource_id),
            },
        ).model_copy(update={"evidence_class": "SOURCE_BOUND"})
        for code in ["A", "B"]
    ]
    published = publish(evidence, dimension, *members)
    definition = {
        "object_type": "DimensionMember",
        "resource_ids": [str(member.resource_id) for member in members],
        "filters": [{"field": "code", "value": "A"}],
    }
    saved = item("ObjectSetDefinition", {"definition": definition})
    original = publish(saved)[0]
    original_pin = UUID(original["version_id"])

    def run(version=None):
        return ontology_definitions.run_set(reader, saved.resource_id, version, 0, 20)

    assert [obj["resource_id"] for obj in run()["objects"]] == [str(members[0].resource_id)]
    revised = saved.model_copy(
        update={
            "expected_version_id": original_pin,
            "attributes": {
                "definition": {**definition, "filters": [{"field": "code", "value": "B"}]}
            },
        }
    )
    correction = publish(revised)[0]
    assert [obj["resource_id"] for obj in run()["objects"]] == [str(members[1].resource_id)]
    request = RollbackRequest(
        versions={saved.resource_id: original_pin},
        rationale="Restore the earlier reviewed synthetic classification query",
        valid_from=datetime.now(UTC),
    )
    draft = rollback_draft(author, request)
    assert draft.mutations[0].attributes == original["attributes"]
    assert draft.mutations[0].expected_version_id == UUID(correction["version_id"])
    assert (
        resources.get_resource(reader, saved.resource_id)["resource"]["version_id"]
        == correction["version_id"]
    )
    resources.propose(author, draft)
    with pytest.raises(WorkspaceError):
        resources.review(
            author.model_copy(update={"permissions": (*author.permissions, "ontology_review")}),
            draft.proposal_id,
            ResourceReview(decision="APPROVED", rationale="Self approval must be refused"),
        )
    competing = saved.model_copy(
        update={
            "expected_version_id": UUID(correction["version_id"]),
            "attributes": {"definition": {**definition, "filters": []}},
        }
    )
    competing_row = publish(competing)[0]
    with pytest.raises(WorkspaceError):
        resources.review(
            reviewer,
            draft.proposal_id,
            ResourceReview(
                decision="APPROVED",
                rationale="Stale restoration cannot override concurrent correction",
            ),
        )
    assert (
        resources.get_resource(reader, saved.resource_id)["resource"]["version_id"]
        == competing_row["version_id"]
    )
    fresh = rollback_draft(
        author,
        RollbackRequest(
            versions={saved.resource_id: original_pin},
            rationale=request.rationale,
            valid_from=datetime.now(UTC),
        ),
    )
    resources.propose(author, fresh)
    resources.review(
        reviewer,
        fresh.proposal_id,
        ResourceReview(
            decision="APPROVED", rationale="Independently restore exact retained synthetic query"
        ),
    )
    detail = resources.get_resource(reader, saved.resource_id)
    restored = detail["resource"]
    assert len(detail["versions"]) == 4
    assert restored["attributes"] == original["attributes"]
    assert restored["version_id"] not in {
        original["version_id"],
        correction["version_id"],
        competing_row["version_id"],
    }
    assert [obj["resource_id"] for obj in run()["objects"]] == [str(members[0].resource_id)]
    assert [obj["resource_id"] for obj in run(UUID(correction["version_id"]))["objects"]] == [
        str(members[1].resource_id)
    ]
    assert run(original_pin)["query"]["filters"] == original["attributes"]["definition"]["filters"]
    with resources.resource_connection(reader) as conn:

        def edges(version):
            return conn.execute(
                "SELECT relation,target_resource_id,target_version_id FROM resource_dependencies "
                "WHERE tenant_id=%s AND version_id=%s "
                "ORDER BY relation,target_resource_id,target_version_id",
                (reader.scope.tenant_id, version),
            ).fetchall()

        assert edges(restored["version_id"]) == edges(original["version_id"])
    assert {obj["version_id"] for obj in run(UUID(competing_row["version_id"]))["objects"]} == {
        published[2]["version_id"],
        published[3]["version_id"],
    }
