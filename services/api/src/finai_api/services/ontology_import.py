"""Offline RDF preparation over retained documents and the shared review authority."""

import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from threading import BoundedSemaphore
from typing import Any
from uuid import UUID

from finai_api.domain.external_ontology import (
    ImportRequest,
    ImportRunDefinition,
    ModuleDefinition,
    ReleaseDefinition,
    RetainedDocument,
    SourceDefinition,
)
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.domain.review import Principal
from finai_api.domain.semantic_analysis import Pin
from finai_api.security import require_permission
from finai_api.services import resources, source_documents
from finai_api.services.workspace import WorkspaceError

_IMPORT_CAPACITY = BoundedSemaphore(1)


def encoded(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def digest(value: Any) -> str:
    return sha256(encoded(value)).hexdigest()


def normalize(request: ImportRequest) -> ImportRequest:
    value = request.model_dump(mode="json")
    value["modules"].sort(key=lambda module: module["artifact_iri"])
    for module in value["modules"]:
        module["owned_namespaces"].sort()
        module["permitted_import_iris"].sort()
        if module.get("foreign_assertions"):
            module["foreign_assertions"].sort(
                key=lambda entry: (
                    entry["subject_iri"],
                    entry["predicate_iri"],
                    entry["object_ntriples"],
                )
            )
    return ImportRequest.model_validate(value)


def identity_key(kind: str, definition: Any, release_id: str | None = None) -> str:
    if kind == "ExternalOntologySource":
        return "external-source:" + digest(definition.source_url)
    if kind == "ExternalOntologyRelease":
        return "external-release:" + digest(
            [str(definition.request.source.resource_id), definition.request.release_label]
        )
    if kind == "ExternalOntologyModule":
        return "external-module:" + digest([release_id, definition.graph_iri])
    return "ontology-import:" + digest([release_id, definition.request_sha256])


def mutation(
    principal: Principal, kind: str, definition: Any, release_id: UUID | None = None
) -> ResourceMutation:
    key = identity_key(kind, definition, str(release_id) if release_id else None)
    attrs: dict[str, Any] = {"definition": definition.model_dump(mode="json")}
    if release_id is not None:
        attrs["release_id"] = str(release_id)
    if kind != "ExternalOntologySource":
        document = (
            definition.canonical_dataset
            if kind == "ExternalOntologyRelease"
            else definition.module.document
            if kind == "ExternalOntologyModule"
            else definition.report
        )
        attrs["evidence_id"] = str(
            canonical_id(principal.scope.tenant_id, "SourceEvidence", document.sha256)
        )
    return ResourceMutation(
        resource_id=canonical_id(
            principal.scope.tenant_id, kind, principal.scope.legal_entity_id + ":" + key
        ),
        identity_key=key,
        object_type=kind,
        display_name=(definition.publisher[:200] if kind == "ExternalOntologySource" else kind),
        attributes=attrs,
        valid_from=datetime.now(UTC),
        evidence_class="USER_ASSERTED" if kind == "ExternalOntologySource" else "SOURCE_BOUND",
    )


def read_document(principal: Principal, ref: RetainedDocument) -> bytes:
    metadata, content = source_documents.document_bytes(principal, ref.document_id)
    if (
        metadata["source_sha256"] != ref.sha256
        or len(content) != ref.byte_length
        or sha256(content).hexdigest() != ref.sha256
    ):
        raise WorkspaceError(409, "Ontology artifact differs from its retained bytes")
    return content


def retained(principal: Principal, filename: str, content: bytes) -> RetainedDocument:
    result = source_documents.retain_document(principal, filename, content)
    return RetainedDocument.model_validate(
        {key: result[key] for key in ("document_id", "sha256", "byte_length")}
    )


def checked_source(row: dict, reference: Pin) -> SourceDefinition:
    if (
        row["object_type"] != "ExternalOntologySource"
        or row["authority_state"] != "APPROVED"
        or str(row["resource_id"]) != str(reference.resource_id)
        or str(row["version_id"]) != str(reference.version_id)
        or row["content_hash"] != reference.content_hash
    ):
        raise WorkspaceError(409, "The exact reviewed external publisher is unavailable")
    return SourceDefinition.model_validate(row["attributes"]["definition"])


def current_sources(principal: Principal, request: ImportRequest) -> None:
    pins = [request.source, *(module.source for module in request.modules)]
    from finai_api.services.resource_lifecycle import require_available_version

    sources = {}
    with resources.resource_connection(principal) as conn:
        for pin in pins:
            row = require_available_version(conn, principal, pin.resource_id, pin.version_id)
            sources[str(pin.version_id)] = checked_source(row, pin)
    for module in request.modules:
        check_module_publisher(module, sources[str(module.source.version_id)])


def check_module_publisher(module: Any, source: SourceDefinition) -> None:
    if (
        module.format not in source.supported_formats
        or module.license != source.license
        or not all(
            any(namespace.startswith(owned) for owned in source.namespaces)
            for namespace in module.owned_namespaces
        )
    ):
        raise WorkspaceError(
            422, "Module format, license or namespace differs from reviewed publisher"
        )


def compile_retained(principal: Principal, request: ImportRequest) -> tuple[Any, dict]:
    from finai_api.services.rdf_engine import (
        RdfArtifact,
        RdfForeignAssertion,
        RdfLimits,
        canonicalize_rdf,
    )

    limits = RdfLimits()
    if sum(module.document.byte_length for module in request.modules) > limits.max_input_bytes:
        raise WorkspaceError(413, "Ontology import exceeds the retained input byte budget")
    artifacts = [
        RdfArtifact(
            artifact_iri=module.artifact_iri,
            format=module.format,
            content=read_document(principal, module.document),
            owned_namespaces=tuple(module.owned_namespaces),
            permitted_import_iris=tuple(module.permitted_import_iris),
            foreign_assertions=tuple(
                RdfForeignAssertion(**assertion.model_dump())
                for assertion in module.foreign_assertions or ()
            ),
        )
        for module in request.modules
    ]
    work_dir = Path(os.environ.get("FINAI_RUNTIME_ROOT", ".finai")).resolve() / "ontology-imports"
    if not _IMPORT_CAPACITY.acquire(blocking=False):
        raise WorkspaceError(429, "An ontology worker is already active; retry this exact request")
    try:
        result = canonicalize_rdf(
            artifacts,
            root_iris=[module.artifact_iri for module in request.modules],
            work_dir=work_dir,
            limits=limits,
        )
    finally:
        _IMPORT_CAPACITY.release()
    if not result.canonical_nquads:
        raise WorkspaceError(422, "An empty RDF dataset cannot publish a usable ontology release")
    report = {
        "contract": "offline-ontology-import-report/1",
        "outcome": "PARSED_ONLY",
        "request_sha256": digest(request.model_dump(mode="json")),
        "canonical_sha256": result.canonical_sha256,
        "artifacts": [asdict(artifact) for artifact in result.artifacts],
        "import_closure": list(result.import_closure),
        "quad_count": result.quad_count,
        "blank_node_count": result.blank_node_count,
        "literal_bytes": result.literal_bytes,
        "engine_manifest": result.manifest,
        "reasoning": "NONE",
        "constraint_validation": "NOT_PERFORMED",
        "business_effect_authorized": False,
    }
    if result.foreign_assertions:
        report["foreign_assertions"] = list(result.foreign_assertions)
    return result, report


def propose_source(principal: Principal, definition: SourceDefinition) -> Any:
    require_permission(principal, "ontology_propose")
    item = mutation(principal, "ExternalOntologySource", definition)
    previous = resources.current_resources(principal, [item.resource_id]).get(str(item.resource_id))
    if previous:
        item = item.model_copy(update={"expected_version_id": UUID(previous["version_id"])})
    proposal = ResourceProposal(
        title="Review external ontology publisher",
        rationale=(
            "Review publisher, namespaces, license and offline retrieval policy; no company facts."
        ),
        access_entity=principal.scope.legal_entity_id,
        mutations=[item],
    )
    return resources.propose(principal, proposal)


def prepare(principal: Principal, request: ImportRequest) -> dict[str, Any]:
    require_permission(principal, "ontology_propose")
    require_permission(principal, "ingest")
    require_permission(principal, "ontology_read")
    request = normalize(request)
    current_sources(principal, request)
    from finai_api.services.rdf_engine import RdfEngineError

    try:
        result, report = compile_retained(principal, request)
    except RdfEngineError as exc:
        refusal = retained(
            principal,
            "ontology-import-refusal.json",
            encoded(
                {
                    "contract": "offline-ontology-import-report/1",
                    "outcome": "REFUSED",
                    "request": request.model_dump(mode="json"),
                    "code": exc.code,
                    "business_effect_authorized": False,
                }
            ),
        )
        return {"status": "REFUSED", "code": exc.code, "report": refusal.model_dump(mode="json")}
    dataset = retained(principal, "ontology-canonical.nq", result.canonical_nquads)
    report_ref = retained(principal, "ontology-import-report.json", encoded(report))
    definition = ReleaseDefinition(
        request=request,
        canonical_dataset=dataset,
        import_report=report_ref,
        request_sha256=digest(request.model_dump(mode="json")),
        engine_manifest=result.manifest,
    )
    release = mutation(principal, "ExternalOntologyRelease", definition)
    modules = [
        mutation(
            principal,
            "ExternalOntologyModule",
            ModuleDefinition(
                module=module,
                graph_iri=module.artifact_iri,
            ),
            release.resource_id,
        )
        for module in request.modules
    ]
    run = mutation(
        principal,
        "OntologyImportRun",
        ImportRunDefinition(
            report=report_ref,
            request_sha256=definition.request_sha256,
        ),
        release.resource_id,
    )
    documents = [dataset, report_ref, *(module.document for module in request.modules)]
    evidence = {
        ref.sha256: ResourceMutation(
            resource_id=canonical_id(principal.scope.tenant_id, "SourceEvidence", ref.sha256),
            object_type="SourceEvidence",
            identity_key=ref.sha256,
            display_name="Retained ontology document",
            attributes={"sha256": ref.sha256, "source_system": "RETAINED_DOCUMENT"},
            valid_from=datetime.now(UTC),
            evidence_class="SOURCE_BOUND",
        )
        for ref in documents
    }
    items = [*evidence.values(), release, *modules, run]
    existing = resources.current_resources(principal, [item.resource_id for item in items])
    pending = []
    for item in items:
        prior = existing.get(str(item.resource_id))
        if prior is None:
            pending.append(item)
        elif (
            item.object_type == "SourceEvidence"
            and prior["object_type"] == "SourceEvidence"
            and prior["attributes"].get("sha256") == item.attributes["sha256"]
            and prior["evidence_class"] == "SOURCE_BOUND"
            and prior["authority_state"] == "APPROVED"
        ):
            continue
        elif prior["attributes"] != item.attributes or prior["authority_state"] != "APPROVED":
            raise WorkspaceError(
                409, "The release identity already records different or revoked content"
            )
    response = {
        "status": "ALREADY_RETAINED",
        "release_id": str(release.resource_id),
        "report": report_ref.model_dump(mode="json"),
        "canonical_dataset": dataset.model_dump(mode="json"),
        "business_effect_authorized": False,
        "constraint_validation": "NOT_PERFORMED",
    }
    if pending:
        proposal_id = canonical_id(
            principal.scope.tenant_id,
            "OntologyImportProposal",
            digest(
                [
                    principal.scope.model_dump(mode="json"),
                    principal.actor_id,
                    request.model_dump(mode="json"),
                ]
            ),
        )
        proposal = ResourceProposal(
            proposal_id=proposal_id,
            title="Review retained external ontology release",
            rationale=(
                "Review exact offline artifacts, import closure and parser report. "
                "No enterprise facts or alignments are created."
            ),
            access_entity=principal.scope.legal_entity_id,
            mutations=pending,
        )
        try:
            detail = resources.proposal_detail(principal, proposal_id)
        except WorkspaceError as exc:
            if exc.status != 404:
                raise
            try:
                detail = resources.propose(principal, proposal)
            except WorkspaceError as conflict:
                if conflict.status != 409:
                    raise
                # A simultaneous identical preparation may win the immutable proposal ID.
                # Reload and compare its semantic payload; never overwrite it.
                try:
                    detail = resources.proposal_detail(principal, proposal_id)
                except WorkspaceError as missing:
                    if missing.status == 404:
                        raise conflict from missing
                    raise
        actual = {str(item.resource_id): item.attributes for item in detail.proposal.mutations}
        expected = {str(item.resource_id): item.attributes for item in pending}
        if actual != expected:
            raise WorkspaceError(409, "Import replay differs from retained preparation")
        response.update(
            status=("REVIEW_REJECTED" if detail.decision == "REJECTED"
                    else "ALREADY_RETAINED" if detail.decision == "APPROVED"
                    else "REVIEW_REQUIRED"),
            proposal=detail.model_dump(mode="json"),
        )
    return response
