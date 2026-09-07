# ruff: noqa: F811
"""Canonical artifact content checks; synthetic native fixtures are not release evidence."""

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from test_definition_history import DB, item, retained  # noqa: F401

from finai_api.domain.build_artifact import Artifact
from finai_api.domain.resources import ResourceProposal, ResourceReview
from finai_api.services import build_artifact, resources, source_documents
from finai_api.services.workspace import WorkspaceError


def attributes(document, evidence_id):
    return {
        "sha256": document["sha256"],
        "byte_length": document["byte_length"],
        "document_id": document["document_id"],
        "evidence_id": str(evidence_id),
        "definition": {
            "contract": "retained-build-artifact/1",
            "authority": "RETAINED_BYTES_ONLY",
            "artifact_kind": "API_WHEEL",
        },
    }


@pytest.mark.parametrize(
    "change",
    [
        {"byte_length": 0},
        {"byte_length": 32_000_001},
        {"byte_length": True},
        {"source_commit": "not-content-identity"},
        {
            "definition": {
                "contract": "retained-build-artifact/1",
                "authority": "RELEASE_ACCEPTED",
                "artifact_kind": "API_WHEEL",
            }
        },
    ],
)
def test_artifact_retention_does_not_accept_authority_or_unbounded_bytes(change):
    attrs = attributes(
        {"sha256": "a" * 64, "byte_length": 1, "document_id": "doc_" + "b" * 64}, uuid4()
    )
    with pytest.raises(ValidationError):
        Artifact.model_validate({**attrs, **change})


@DB
def test_retained_artifact_publication_exact_scope_and_promotion_recheck(retained, monkeypatch):
    original_reader, _original_publish = retained
    isolated_scope = original_reader.scope.model_copy(
        update={"legal_entity_id": "synthetic-artifact-" + uuid4().hex}
    )
    reader = original_reader.model_copy(
        update={
            "scope": isolated_scope,
            "actor_id": "synthetic-artifact-proposer",
            "permissions": ("ontology_read",),
        }
    )
    author = reader.model_copy(
        update={"permissions": (*reader.permissions, "ingest", "ontology_propose")}
    )
    reviewer = author.model_copy(
        update={
            "actor_id": "synthetic-artifact-reviewer",
            "permissions": (*author.permissions, "ontology_review"),
        }
    )

    def publish(*mutations):
        proposed = ResourceProposal(
            title="SYNTHETIC isolated Artifact validation",
            rationale="Native retained-byte contract in an explicitly synthetic scope",
            access_entity=isolated_scope.legal_entity_id,
            mutations=list(mutations),
        )
        resources.propose(author, proposed)
        resources.review(
            reviewer,
            proposed.proposal_id,
            ResourceReview(
                decision="APPROVED", rationale="Independent synthetic retained-byte review"
            ),
        )
        return [
            resources.get_resource(reader, mutation.resource_id)["resource"]
            for mutation in mutations
        ]

    document = source_documents.retain_document(author, "SYNTHETIC fixture.bin", uuid4().bytes)
    evidence = item(
        "SourceEvidence",
        {"sha256": document["sha256"], "source_system": "SYNTHETIC"},
    ).model_copy(update={"evidence_class": "SOURCE_BOUND"})
    artifact = item("Artifact", attributes(document, evidence.resource_id)).model_copy(
        update={"identity_key": "sha256:" + document["sha256"], "evidence_class": "SOURCE_BOUND"}
    )
    accepted = publish(evidence, artifact)[1]
    assert accepted["access_entity"] == isolated_scope.legal_entity_id
    assert accepted["access_entity"].startswith("synthetic-artifact-")
    assert accepted["access_entity"] != original_reader.scope.legal_entity_id
    with pytest.raises(WorkspaceError):
        resources.get_resource(
            original_reader.model_copy(update={"permissions": ("ontology_read",)}),
            artifact.resource_id,
        )
    with pytest.raises(WorkspaceError, match="source scope"):
        source_documents.document_bytes(original_reader, document["document_id"])
    assert accepted["attributes"]["definition"]["authority"] == "RETAINED_BYTES_ONLY"
    metadata, content = source_documents.document_bytes(reader, document["document_id"])
    assert (
        source_documents.retain_document(author, "Repeat name.bin", content)["document_id"]
        == document["document_id"]
    )
    other = reader.model_copy(
        update={
            "scope": reader.scope.model_copy(update={"legal_entity_id": "other-artifact-scope"})
        }
    )
    with pytest.raises(WorkspaceError, match="source scope"):
        build_artifact.validate_artifact(
            other,
            artifact,
            lambda *_: {
                "object_type": "SourceEvidence",
                "attributes": {"sha256": document["sha256"]},
            },
        )
    for changes in (
        {"identity_key": "sha256:" + "0" * 64},
        {"attributes": {**artifact.attributes, "byte_length": len(content) + 1}},
    ):
        with pytest.raises(WorkspaceError):
            build_artifact.validate_artifact(
                reader,
                artifact.model_copy(update=changes),
                lambda *_: {
                    "object_type": "SourceEvidence",
                    "attributes": {"sha256": document["sha256"]},
                },
            )
    with pytest.raises(WorkspaceError, match="matching canonical source evidence"):
        build_artifact.validate_artifact(
            reader,
            artifact,
            lambda *_: {"object_type": "SourceEvidence", "attributes": {"sha256": "0" * 64}},
        )
    corrected = artifact.model_copy(
        update={
            "expected_version_id": UUID(accepted["version_id"]),
            "display_name": "SYNTHETIC renamed byte artifact",
        }
    )
    proposal = ResourceProposal(
        title="Revalidate retained artifact bytes",
        rationale="Synthetic promotion check",
        access_entity=reader.scope.legal_entity_id,
        mutations=[corrected],
    )
    resources.propose(author, proposal)
    with monkeypatch.context() as patch:
        patch.setattr(build_artifact, "document_bytes", lambda *_: (metadata, b"changed bytes"))
        with pytest.raises(WorkspaceError, match="retained document bytes"):
            resources.review(
                reviewer,
                proposal.proposal_id,
                ResourceReview(decision="APPROVED", rationale="Synthetic independent byte review"),
            )
    assert (
        resources.get_resource(reader, artifact.resource_id)["resource"]["version_id"]
        == accepted["version_id"]
    )
    resources.review(
        reviewer,
        proposal.proposal_id,
        ResourceReview(decision="APPROVED", rationale="Synthetic independent retained-byte review"),
    )
    assert (
        resources.get_resource(reader, artifact.resource_id)["resource"]["display_name"]
        == corrected.display_name
    )
    current = resources.get_resource(reader, artifact.resource_id)["resource"]
    retired = corrected.model_copy(
        update={"expected_version_id": UUID(current["version_id"]), "authority_state": "REVOKED"}
    )
    assert publish(retired)[0]["authority_state"] == "REVOKED"
