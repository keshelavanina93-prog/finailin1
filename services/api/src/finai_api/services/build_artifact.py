"""Validate canonical Artifact publication against existing exact-scope retained bytes."""

from collections.abc import Callable
from hashlib import sha256

from finai_api.domain.build_artifact import Artifact
from finai_api.domain.resources import ResourceMutation
from finai_api.domain.review import Principal
from finai_api.services.source_documents import document_bytes
from finai_api.services.workspace import WorkspaceError


def validate_artifact(
    principal: Principal, item: ResourceMutation, target: Callable[[str, str, str], dict]
) -> None:
    try:
        artifact = Artifact.model_validate(item.attributes)
    except ValueError as exc:
        raise WorkspaceError(422, "Artifact requires the retained-byte contract") from exc
    if item.identity_key != "sha256:" + artifact.sha256:
        raise WorkspaceError(422, "Artifact identity must equal its retained content hash")
    if item.evidence_class != "SOURCE_BOUND":
        raise WorkspaceError(422, "Retained artifacts require source-bound evidence classification")
    evidence = target(str(artifact.evidence_id), str(item.resource_id), "ARTIFACT_EVIDENCE")
    if (
        evidence["object_type"] != "SourceEvidence"
        or evidence["attributes"].get("sha256") != artifact.sha256
    ):
        raise WorkspaceError(422, "Artifact requires matching canonical source evidence")
    metadata, content = document_bytes(principal, artifact.document_id)
    if (
        metadata["source_sha256"] != artifact.sha256
        or len(content) != artifact.byte_length
        or sha256(content).hexdigest() != artifact.sha256
    ):
        raise WorkspaceError(409, "Artifact differs from its exact-scope retained document bytes")
