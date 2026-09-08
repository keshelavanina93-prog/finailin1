"""External ontology metadata is verified through canonical publication and exact dependencies."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from finai_api.domain.external_ontology import (
    EXTERNAL_TYPES,
    ImportRunDefinition,
    ModuleDefinition,
    ReleaseDefinition,
    SourceDefinition,
)
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceMutation
from finai_api.domain.review import Principal
from finai_api.services import ontology_import
from finai_api.services.workspace import WorkspaceError


def validate_boundaries(proposal: Any) -> None:
    """A release cannot change the publisher authority against which it is replayed."""
    releases = [item for item in proposal.mutations
                if item.object_type == "ExternalOntologyRelease"]
    if len(releases) > 1:
        raise WorkspaceError(422, "Review one external ontology release per change set")
    mutations = {item.resource_id for item in proposal.mutations}
    for item in releases:
        try:
            request = ReleaseDefinition.model_validate(item.attributes["definition"]).request
        except (ValueError, KeyError) as exc:
            raise WorkspaceError(422, "Invalid external ontology release declaration") from exc
        publishers = {request.source.resource_id,
                      *(module.source.resource_id for module in request.modules)}
        if mutations & publishers:
            raise WorkspaceError(409, "An ontology release cannot also mutate its publisher")


def preflight(principal: Principal, proposal: Any) -> dict[UUID, str]:
    """Replay immutable bytes before taking the tenant's canonical publication lock."""
    validate_boundaries(proposal)
    proofs = {}
    for item in proposal.mutations:
        if item.object_type != "ExternalOntologyRelease":
            continue
        try:
            definition = ReleaseDefinition.model_validate(item.attributes["definition"])
        except (ValueError, KeyError) as exc:
            raise WorkspaceError(422, "Invalid external ontology release declaration") from exc
        ontology_import.current_sources(principal, definition.request)
        from finai_api.services.rdf_engine import RdfEngineError

        try:
            result, report = ontology_import.compile_retained(principal, definition.request)
        except RdfEngineError as exc:
            raise WorkspaceError(422, "Retained ontology failed bounded replay") from exc
        if (
            result.manifest != definition.engine_manifest
            or ontology_import.read_document(principal, definition.canonical_dataset)
            != result.canonical_nquads
            or ontology_import.read_document(principal, definition.import_report)
            != ontology_import.encoded(report)
        ):
            raise WorkspaceError(409, "Ontology dataset/report differs from retained replay")
        proofs[item.resource_id] = ontology_import.digest(item.model_dump(mode="json"))
    return proofs


def validate(
    principal: Principal,
    item: ResourceMutation,
    target: Callable[..., dict],
    previous: dict | None,
    access_entity: str,
    conn: Any,
    proofs: dict[UUID, str] | None,
) -> None:
    if item.object_type not in EXTERNAL_TYPES:
        return
    models: dict[str, type[BaseModel]] = {
        "ExternalOntologySource": SourceDefinition,
        "ExternalOntologyRelease": ReleaseDefinition,
        "ExternalOntologyModule": ModuleDefinition,
        "OntologyImportRun": ImportRunDefinition,
    }
    try:
        definition: Any = models[item.object_type].model_validate(item.attributes["definition"])
    except (ValueError, KeyError) as exc:
        raise WorkspaceError(
            422, "External ontology metadata requires its strict versioned contract"
        ) from exc
    key = ontology_import.identity_key(
        item.object_type, definition, item.attributes.get("release_id")
    )
    if item.identity_key != key:
        raise WorkspaceError(
            422, "External ontology identity differs from publisher/release/artifact"
        )
    if item.resource_id != canonical_id(
        principal.scope.tenant_id, item.object_type, access_entity + ":" + key
    ):
        raise WorkspaceError(422, "External ontology resource must use its canonical identity")
    if (
        previous
        and item.object_type != "ExternalOntologySource"
        and previous["attributes"] != item.attributes
    ):
        raise WorkspaceError(409, "Retained ontology releases, modules and runs are immutable")
    if item.object_type == "ExternalOntologySource":
        if item.evidence_class != "USER_ASSERTED":
            raise WorkspaceError(422, "Publisher declarations require explicit reviewed metadata")
        return
    if item.evidence_class != "SOURCE_BOUND":
        raise WorkspaceError(422, "Imported ontology resources require retained artifact evidence")
    identifier = str(item.resource_id)
    if isinstance(definition, ReleaseDefinition):
        request = definition.request
        if ontology_import.normalize(request) != request:
            raise WorkspaceError(422, "Ontology release inputs must use deterministic ordering")
        if definition.request_sha256 != ontology_import.digest(request.model_dump(mode="json")):
            raise WorkspaceError(409, "Ontology release input manifest hash differs")
        pins = [request.source, *(module.source for module in request.modules)]
        sources = {}
        for index, pin in enumerate(pins):
            from finai_api.services.resource_lifecycle import require_available_version

            require_available_version(conn, principal, pin.resource_id, pin.version_id)
            source = target(
                str(pin.resource_id),
                identifier,
                f"EXTERNAL_ONTOLOGY_SOURCE:{index}",
                str(pin.version_id),
            )
            now = datetime.now(UTC)
            valid_from, valid_to = source["valid_from"], source.get("valid_to")
            if isinstance(valid_from, str):
                valid_from = datetime.fromisoformat(valid_from)
            if isinstance(valid_to, str):
                valid_to = datetime.fromisoformat(valid_to)
            if valid_from > now or (valid_to is not None and valid_to <= now):
                raise WorkspaceError(409, "External publisher is not currently effective")
            sources[str(pin.version_id)] = ontology_import.checked_source(source, pin)
        for module in request.modules:
            ontology_import.check_module_publisher(module, sources[str(module.source.version_id)])
        if not proofs or proofs.get(item.resource_id) != ontology_import.digest(
            item.model_dump(mode="json")
        ):
            raise WorkspaceError(
                409, "External ontology publication requires exact preflight replay"
            )
        document = definition.canonical_dataset
    else:
        release = target(item.attributes["release_id"], identifier, "EXTERNAL_ONTOLOGY_RELEASE")
        if release["object_type"] != "ExternalOntologyRelease":
            raise WorkspaceError(422, "Ontology module and run must depend on an external release")
        parent = ReleaseDefinition.model_validate(release["attributes"]["definition"])
        if isinstance(definition, ModuleDefinition):
            if definition.module not in parent.request.modules:
                raise WorkspaceError(409, "Module differs from the exact selected release")
            document = definition.module.document
        elif (
            definition.report != parent.import_report
            or definition.request_sha256 != parent.request_sha256
        ):
            raise WorkspaceError(409, "Import run differs from the selected release receipt")
        else:
            document = definition.report
    evidence = target(item.attributes["evidence_id"], identifier, "EXTERNAL_ONTOLOGY_EVIDENCE")
    if (
        evidence["object_type"] != "SourceEvidence"
        or evidence["attributes"].get("sha256") != document.sha256
    ):
        raise WorkspaceError(409, "Ontology evidence does not identify its retained artifact")
