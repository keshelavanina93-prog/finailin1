"""Reviewed exact external meaning profiles; no enterprise or accounting authority."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from finai_api.domain.external_ontology import ReleaseDefinition
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.ontology_validation import (
    ConstraintProfileDefinition,
    GraphSelection,
    OntologyProfileDefinition,
    ValidationReportDefinition,
    ValidationRunRequest,
)
from finai_api.domain.resources import ProposalDetail, ResourceMutation, ResourceProposal
from finai_api.domain.review import Principal
from finai_api.domain.semantic_analysis import Pin
from finai_api.security import require_permission
from finai_api.services import ontology_import, resources
from finai_api.services.resource_lifecycle import require_available_version
from finai_api.services.workspace import WorkspaceError

MODELS: dict[str, type[BaseModel]] = {
    "OntologyProfile": OntologyProfileDefinition,
    "ExternalConstraintProfile": ConstraintProfileDefinition,
    "OntologyValidationReport": ValidationReportDefinition,
}


def _definition(item: ResourceMutation) -> Any:
    try:
        return MODELS[item.object_type].model_validate(item.attributes["definition"])
    except (ValueError, KeyError) as exc:
        raise WorkspaceError(422, "A strict versioned ontology profile/report is required") from exc


def checked_profile(
    principal: Principal,
    pin: Pin,
    kind: str,
    *,
    conn: Any = None,
) -> Any:
    require_permission(principal, "ontology_read")
    if conn is None:
        with resources.resource_connection(principal) as connection:
            return checked_profile(principal, pin, kind, conn=connection)
    row = require_available_version(conn, principal, pin.resource_id, pin.version_id)
    if (
        row["object_type"] != kind
        or row["content_hash"] != pin.content_hash
        or row["access_entity"] != principal.scope.legal_entity_id
    ):
        raise WorkspaceError(409, "The exact scoped ontology dependency is unavailable")
    model = ReleaseDefinition if kind == "ExternalOntologyRelease" else MODELS[kind]
    return model.model_validate(row["attributes"]["definition"])


def checked_graph_selection(
    principal: Principal,
    selection: GraphSelection,
    *,
    conn: Any = None,
) -> ReleaseDefinition:
    if conn is None:
        with resources.resource_connection(principal) as connection:
            return checked_graph_selection(principal, selection, conn=connection)
    release: ReleaseDefinition = checked_profile(
        principal,
        selection.release,
        "ExternalOntologyRelease",
        conn=conn,
    )
    if not set(selection.graph_iris).issubset(
        module.artifact_iri for module in release.request.modules
    ):
        raise WorkspaceError(409, "Selected graphs are not members of the exact release")
    publishers = {}
    for pin in (release.request.source, *(module.source for module in release.request.modules)):
        row = require_available_version(conn, principal, pin.resource_id, pin.version_id)
        if row["access_entity"] != principal.scope.legal_entity_id:
            raise WorkspaceError(409, "The exact scoped publisher is unavailable")
        publishers[pin.version_id] = ontology_import.checked_source(row, pin)
    for module in release.request.modules:
        ontology_import.check_module_publisher(module, publishers[module.source.version_id])
    return release


def resolve_run(
    principal: Principal,
    request: ValidationRunRequest,
    *,
    conn: Any = None,
) -> tuple[
    OntologyProfileDefinition, ConstraintProfileDefinition, ReleaseDefinition, ReleaseDefinition
]:
    if conn is None:
        with resources.resource_connection(principal) as connection:
            return resolve_run(principal, request, conn=connection)
    constraint: ConstraintProfileDefinition = checked_profile(
        principal,
        request.constraint_profile,
        "ExternalConstraintProfile",
        conn=conn,
    )
    profile: OntologyProfileDefinition = checked_profile(
        principal,
        constraint.ontology_profile,
        "OntologyProfile",
        conn=conn,
    )
    for member in profile.members:
        checked_graph_selection(principal, member, conn=conn)
    if not any(
        member.release == request.data.release
        and set(request.data.graph_iris).issubset(member.graph_iris)
        for member in profile.members
    ):
        raise WorkspaceError(409, "Validation data is outside the reviewed profile membership")
    data = checked_graph_selection(principal, request.data, conn=conn)
    shapes = checked_graph_selection(principal, constraint.shapes, conn=conn)
    return profile, constraint, data, shapes


def identity_key(kind: str, definition: Any) -> str:
    return kind + ":" + ontology_import.digest(definition.model_dump(mode="json"))


def mutation(principal: Principal, kind: str, definition: Any) -> ResourceMutation:
    key = identity_key(kind, definition)
    attributes: dict[str, Any] = {"definition": definition.model_dump(mode="json")}
    if kind == "OntologyValidationReport":
        attributes["evidence_id"] = str(
            canonical_id(
                principal.scope.tenant_id,
                "SourceEvidence",
                definition.report.sha256,
            )
        )
    return ResourceMutation(
        resource_id=canonical_id(
            principal.scope.tenant_id,
            kind,
            principal.scope.legal_entity_id + ":" + key,
        ),
        object_type=kind,
        identity_key=key,
        display_name=kind,
        attributes=attributes,
        valid_from=datetime.now(UTC),
        evidence_class="SOURCE_BOUND" if kind == "OntologyValidationReport" else "USER_ASSERTED",
    )


def _propose(principal: Principal, kind: str, definition: Any) -> ProposalDetail:
    require_permission(principal, "ontology_propose")
    item = mutation(principal, kind, definition)
    identifier = canonical_id(
        principal.scope.tenant_id,
        kind + "Proposal",
        principal.scope.legal_entity_id + ":" + item.identity_key,
    )
    proposal = ResourceProposal(
        proposal_id=identifier,
        title="Review " + kind,
        rationale="Review exact external meaning and graph membership without business authority",
        access_entity=principal.scope.legal_entity_id,
        mutations=[item],
    )
    preflight(principal, proposal)

    def same_proposal(existing: ProposalDetail) -> bool:
        return (
            existing.proposal.access_entity == proposal.access_entity
            and len(existing.proposal.mutations) == 1
            and existing.proposal.mutations[0].model_dump(exclude={"valid_from"})
            == item.model_dump(exclude={"valid_from"})
            and existing.proposal.mutations[0].valid_from <= datetime.now(UTC)
        )

    try:
        existing = resources.proposal_detail(principal, identifier)
    except WorkspaceError as exc:
        if exc.status != 404:
            raise
    else:
        if not same_proposal(existing):
            raise WorkspaceError(409, "Profile proposal identity is reserved for other content")
        return existing
    try:
        return resources.propose(principal, proposal)
    except WorkspaceError as exc:
        if exc.status != 409:
            raise
        # The content-addressed proposal may have raced another identical preparation.
        try:
            existing = resources.proposal_detail(principal, identifier)
        except WorkspaceError:
            raise exc from None
        if not same_proposal(existing):
            raise exc
        return existing


def propose_profile(principal: Principal, definition: OntologyProfileDefinition) -> ProposalDetail:
    return _propose(principal, "OntologyProfile", definition)


def propose_constraint_profile(
    principal: Principal,
    definition: ConstraintProfileDefinition,
) -> ProposalDetail:
    return _propose(principal, "ExternalConstraintProfile", definition)


def propose_report(principal: Principal, workflow_id: str) -> ProposalDetail:
    """Prepare independent canonical review of a published retained observation."""
    require_permission(principal, "ontology_propose")
    from finai_api.services.ontology_validation_runs import publication_context

    _, _, definition = publication_context(principal, workflow_id)
    report = mutation(principal, "OntologyValidationReport", definition)
    evidence = ResourceMutation(
        resource_id=canonical_id(
            principal.scope.tenant_id, "SourceEvidence", definition.report.sha256
        ),
        object_type="SourceEvidence",
        identity_key=definition.report.sha256,
        display_name="Retained ontology document",
        attributes={"sha256": definition.report.sha256, "source_system": "RETAINED_DOCUMENT"},
        valid_from=datetime.now(UTC),
        evidence_class="SOURCE_BOUND",
    )
    identifier = canonical_id(
        principal.scope.tenant_id,
        "OntologyValidationReportProposal",
        principal.scope.legal_entity_id + ":" + report.identity_key,
    )

    def checked_replay(detail: ProposalDetail) -> ProposalDetail:
        expected = {item.resource_id: item for item in (report, evidence)}
        actual = {item.resource_id: item for item in detail.proposal.mutations}
        if (
            detail.proposal.access_entity != principal.scope.legal_entity_id
            or report.resource_id not in actual
            or not actual.keys() <= expected.keys()
            or any(
                item.model_dump(exclude={"valid_from"})
                != expected[key].model_dump(exclude={"valid_from"})
                or item.valid_from > datetime.now(UTC)
                for key, item in actual.items()
            )
        ):
            raise WorkspaceError(409, "Report proposal identity is reserved for other content")
        preflight(principal, detail.proposal)
        return detail

    try:
        existing_proposal = resources.proposal_detail(principal, identifier)
    except WorkspaceError as exc:
        if exc.status != 404:
            raise
    else:
        return checked_replay(existing_proposal)

    existing = resources.current_resources(principal, [report.resource_id, evidence.resource_id])
    prior = existing.get(str(report.resource_id))
    if prior is not None:
        if (
            prior["attributes"] != report.attributes
            or prior["object_type"] != report.object_type
            or prior["authority_state"] != "APPROVED"
            or not prior.get("proposal_id")
        ):
            raise WorkspaceError(
                409, "Report identity already records different or revoked content"
            )
        return checked_replay(resources.proposal_detail(principal, UUID(str(prior["proposal_id"]))))
    prior_evidence = existing.get(str(evidence.resource_id))
    items = [report]
    if prior_evidence is None:
        items.insert(0, evidence)
    elif (
        prior_evidence["object_type"] != "SourceEvidence"
        or prior_evidence["attributes"].get("sha256") != definition.report.sha256
        or prior_evidence["authority_state"] != "APPROVED"
        or prior_evidence["evidence_class"] != "SOURCE_BOUND"
    ):
        raise WorkspaceError(409, "Report evidence identity is incompatible or revoked")
    proposal = ResourceProposal(
        proposal_id=identifier,
        title="Review retained ontology validation observation",
        rationale=(
            "Independently review exact validation evidence "
            "without business or accounting authority"
        ),
        access_entity=principal.scope.legal_entity_id,
        mutations=items,
    )
    try:
        return resources.propose(principal, proposal)
    except WorkspaceError as exc:
        if exc.status != 409:
            raise
        try:
            replay = resources.proposal_detail(principal, identifier)
        except WorkspaceError:
            raise exc from None
        return checked_replay(replay)


def _dependencies(
    principal: Principal,
    definition: Any,
    *,
    conn: Any = None,
) -> list[tuple[Pin, str, str]]:
    if conn is None:
        with resources.resource_connection(principal) as connection:
            return _dependencies(principal, definition, conn=connection)
    dependencies: list[tuple[Pin, str, str]] = []

    def graph(selection: GraphSelection, role: str) -> None:
        release = checked_graph_selection(principal, selection, conn=conn)
        dependencies.append((selection.release, "ExternalOntologyRelease", role))
        for index, pin in enumerate(
            (
                release.request.source,
                *(module.source for module in release.request.modules),
            )
        ):
            dependencies.append((pin, "ExternalOntologySource", f"{role}:PUBLISHER:{index}"))

    if isinstance(definition, OntologyProfileDefinition):
        for index, member in enumerate(definition.members):
            graph(member, f"MEMBER:{index}")
    elif isinstance(definition, ConstraintProfileDefinition):
        profile = checked_profile(
            principal,
            definition.ontology_profile,
            "OntologyProfile",
            conn=conn,
        )
        dependencies.append((definition.ontology_profile, "OntologyProfile", "PROFILE"))
        for index, member in enumerate(profile.members):
            graph(member, f"MEMBER:{index}")
        graph(definition.shapes, "SHAPES")
    else:
        from finai_api.services.ontology_validation_runs import publication_context

        request, plan, retained = publication_context(
            principal,
            definition.workflow_id,
            conn=conn,
        )
        if definition != retained:
            raise WorkspaceError(409, "Validation report differs from its retained execution")
        profile, _, _, _ = resolve_run(principal, request, conn=conn)
        dependencies.extend(
            (
                (plan.ontology_profile, "OntologyProfile", "PROFILE"),
                (plan.constraint_profile, "ExternalConstraintProfile", "CONSTRAINT"),
            )
        )
        for index, member in enumerate(profile.members):
            graph(member, f"MEMBER:{index}")
        graph(plan.data, "DATA")
        graph(plan.shapes, "SHAPES")
    return dependencies


def validate_boundaries(
    principal: Principal, proposal: ResourceProposal, *, conn: Any = None
) -> None:
    mutated = {item.resource_id for item in proposal.mutations}
    for item in proposal.mutations:
        if item.object_type not in MODELS:
            continue
        definition = _definition(item)
        dependencies = _dependencies(principal, definition, conn=conn)
        if mutated.intersection(pin.resource_id for pin, _, _ in dependencies):
            raise WorkspaceError(409, "An ontology profile cannot also mutate its dependencies")


def preflight(principal: Principal, proposal: ResourceProposal) -> dict[UUID, str]:
    validate_boundaries(principal, proposal)
    proofs = {}
    for item in proposal.mutations:
        if item.object_type != "OntologyValidationReport":
            continue
        from finai_api.services.ontology_validation_runs import publication_context

        definition = _definition(item)
        _, _, retained = publication_context(principal, definition.workflow_id)
        if definition != retained:
            raise WorkspaceError(409, "Validation report differs from its retained execution")
        proofs[item.resource_id] = ontology_import.digest(item.model_dump(mode="json"))
    return proofs


def publication_preflight(principal: Principal, proposal: ResourceProposal) -> dict[UUID, str]:
    from finai_api.services.external_ontology_validation import preflight as import_preflight

    proofs = preflight(principal, proposal)
    proofs.update(import_preflight(principal, proposal))
    return proofs


def validate(
    principal: Principal,
    item: ResourceMutation,
    target: Callable[..., dict[str, Any]],
    previous: dict[str, Any] | None,
    access_entity: str,
    conn: Any,
    proofs: dict[UUID, str] | None,
) -> None:
    definition = _definition(item)
    key = identity_key(item.object_type, definition)
    if (
        access_entity != principal.scope.legal_entity_id
        or item.resource_id
        != canonical_id(
            principal.scope.tenant_id,
            item.object_type,
            access_entity + ":" + key,
        )
        or item.identity_key != key
    ):
        raise WorkspaceError(422, "Ontology profiles require their exact scoped canonical identity")
    if previous is not None and previous["attributes"] != item.attributes:
        raise WorkspaceError(409, "Reviewed profiles and validation reports are immutable")
    expected_evidence = (
        "SOURCE_BOUND" if isinstance(definition, ValidationReportDefinition) else ("USER_ASSERTED")
    )
    if item.evidence_class != expected_evidence:
        raise WorkspaceError(422, "Ontology profile/report evidence class is incompatible")
    expected_attributes: dict[str, Any] = {"definition": definition.model_dump(mode="json")}
    if isinstance(definition, ValidationReportDefinition):
        expected_attributes["evidence_id"] = str(
            canonical_id(
                principal.scope.tenant_id,
                "SourceEvidence",
                definition.report.sha256,
            )
        )
        if not proofs or proofs.get(item.resource_id) != ontology_import.digest(
            item.model_dump(mode="json")
        ):
            raise WorkspaceError(
                409, "Validation report requires exact retained execution preflight"
            )
        evidence = target(
            item.attributes.get("evidence_id"),
            str(item.resource_id),
            "ONTOLOGY_VALIDATION_EVIDENCE",
        )
        if (
            evidence["object_type"] != "SourceEvidence"
            or evidence["attributes"].get("sha256") != definition.report.sha256
        ):
            raise WorkspaceError(409, "Validation evidence differs from the retained report")
    if item.attributes != expected_attributes:
        raise WorkspaceError(
            422, "Ontology profile/report attributes differ from the strict contract"
        )
    for pin, kind, role in _dependencies(principal, definition, conn=conn):
        row = target(
            str(pin.resource_id),
            str(item.resource_id),
            "ONTOLOGY_PROFILE:" + role,
            str(pin.version_id),
        )
        if row["object_type"] != kind or row["content_hash"] != pin.content_hash:
            raise WorkspaceError(409, "The exact ontology profile dependency differs")
