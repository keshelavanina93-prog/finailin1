"""Authorize exact external releases before accessing their disposable RDF projection."""

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from finai_api.domain.external_ontology import (
    ReleaseDefinition,
    ReleaseInspectionRequest,
    TermInspectionRequest,
)
from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services import ontology_import, operator_inspection, resources
from finai_api.services.resource_lifecycle import require_available_version
from finai_api.services.workspace import WorkspaceError


def authorized_release(
    principal: Principal, request: ReleaseInspectionRequest
) -> ReleaseDefinition:
    require_permission(principal, "ontology_read")
    pin = request.release
    if request.mode == "HISTORICAL_INSPECTION":
        row = operator_inspection.inspect(
            principal, pin.resource_id, pin.version_id, request.known_at
        )["resource"]
    else:
        with resources.resource_connection(principal) as conn:
            row = require_available_version(conn, principal, pin.resource_id, pin.version_id)
    if row["object_type"] != "ExternalOntologyRelease" or row["content_hash"] != pin.content_hash:
        raise WorkspaceError(409, "The exact external ontology release is unavailable")
    definition = ReleaseDefinition.model_validate(row["attributes"]["definition"])
    if request.mode == "CURRENT_RELEASE":
        ontology_import.current_sources(principal, definition.request)
    return definition


def release_metadata(principal: Principal, request: ReleaseInspectionRequest) -> dict[str, Any]:
    definition = authorized_release(principal, request)
    return {
        "scope": principal.scope.model_dump(mode="json"),
        "release": request.release.model_dump(mode="json"),
        "definition": definition.model_dump(mode="json"),
        "business_effect_authorized": False,
        "mode": request.mode,
        "known_at": request.known_at,
        "current_use_authorized": False,
    }


def project(
    principal: Principal, request: ReleaseInspectionRequest, *, rebuild: bool
) -> dict[str, Any]:
    from finai_api.services.ontology_index import (
        OntologyIndexError,
        OntologyIndexScope,
        build_index,
        inspect_subject,
    )

    if rebuild:
        require_permission(principal, "ontology_propose")
    definition = authorized_release(principal, request)
    # Retained evidence access remains mandatory even when a local index already exists.
    data = ontology_import.read_document(principal, definition.canonical_dataset)
    scope = OntologyIndexScope(
        tenant_id=str(principal.scope.tenant_id),
        legal_entity_id=principal.scope.legal_entity_id,
        release_id=str(request.release.resource_id),
        release_version_id=str(request.release.version_id),
        release_content_hash=request.release.content_hash,
        dataset_sha256=definition.canonical_dataset.sha256,
    )
    root = Path(os.environ.get("FINAI_RUNTIME_ROOT", ".finai")).resolve() / "ontology-index"
    try:
        if rebuild:
            result: Any = build_index(scope, data, index_root=root)
        else:
            if not isinstance(request, TermInspectionRequest):
                raise WorkspaceError(422, "A bounded subject request is required")
            result = inspect_subject(
                scope, request.subject_iri, index_root=root, limit=request.limit
            )
    except OntologyIndexError as exc:
        # Index files are disposable: never substitute an older version on failure.
        raise WorkspaceError(409, "Ontology index unavailable: " + exc.code) from exc
    # A withdrawal during slow index work must not become a successful authorized read.
    authorized_release(principal, request)
    return {
        "scope": principal.scope.model_dump(mode="json"),
        "release": request.release.model_dump(mode="json"),
        "projection": asdict(result),
        "business_effect_authorized": False,
        "mode": request.mode,
        "known_at": request.known_at,
        "current_use_authorized": False,
        "reasoning": "NONE",
        "constraint_validation": "NOT_PERFORMED",
    }
