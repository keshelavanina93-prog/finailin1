"""Reviewable resolution proposals from strictly compatible, later retained journal evidence."""

from datetime import UTC, datetime
from uuid import UUID

from psycopg.rows import dict_row

from finai_api.domain.investigation import (
    FindingDefinition,
    InvestigationDefinition,
    InvestigationOperation,
)
from finai_api.domain.investigation_resolution import (
    InvestigationResolutionAction,
    ResolutionProof,
    ResolvedFindingDefinition,
    ResolvedInvestigationDefinition,
)
from finai_api.domain.metric_execution import Pin
from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.domain.source_reconciliation_exception import SourceExceptionObservation
from finai_api.services import investigation_actions as investigations
from finai_api.services import resources
from finai_api.services import source_reconciliation_exception as exceptions
from finai_api.services.certification import _current
from finai_api.services.workspace import WorkspaceError


def hash_pin(row):
    return Pin.model_validate(
        {key: row[key] for key in ("resource_id", "version_id", "content_hash")}
    )


def current_pair(principal, request):
    rows = []
    with (
        resources.resource_connection(principal, repeatable_read=True) as conn,
        conn.cursor(row_factory=dict_row) as cursor,
    ):
        for reference, kind in [
            (request.finding, "Finding"),
            (request.investigation, "Investigation"),
        ]:
            row = resources._get(conn, principal.scope.tenant_id, reference.resource_id)
            now = datetime.now(UTC)
            if (
                hash_pin(row) != reference
                or row["object_type"] != kind
                or row["authority_state"] != "APPROVED"
                or row["access_entity"] != principal.scope.legal_entity_id
                or row["attributes"].get("legal_entity_id") != principal.scope.legal_entity_id
                or row["valid_from"] > now
                or (row.get("valid_to") and row["valid_to"] <= now)
            ):
                raise WorkspaceError(
                    409, "Resolution requires the exact approved current company pair"
                )
            _current(
                cursor,
                principal,
                VersionReference(
                    resource_id=reference.resource_id, version_id=reference.version_id
                ),
            )
            rows.append(row)
    if rows[1]["attributes"].get("finding_id") != str(request.finding.resource_id):
        raise WorkspaceError(409, "Investigation belongs to another finding")
    return rows


def matched_evidence(principal, run_id):
    retained = exceptions.read(principal, run_id)
    observation = SourceExceptionObservation.model_validate(
        {key: retained[key] for key in SourceExceptionObservation.model_fields if key in retained}
    )
    if (
        observation.state != "MATCHED_AT_SNAPSHOT"
        or observation.finding_eligible
        or not observation.matched_journals
        or str(observation.company.resource_id) != principal.scope.legal_entity_id
    ):
        raise WorkspaceError(409, "Resolution requires retained matched evidence for this company")
    return observation


def compatible(old, new):
    if (
        old.state != "UNMATCHED_AT_SNAPSHOT"
        or new.state != "MATCHED_AT_SNAPSHOT"
        or old.company != new.company
        or old.binding != new.binding
        or old.source_function != new.source_function
        or old.source != new.source
        or old.selection != new.selection
        or investigations.evidence_context(old) != investigations.evidence_context(new)
        or old.source_valid_at != new.source_valid_at
        or old.source_known_at != new.source_known_at
    ):
        raise WorkspaceError(
            409, "Resolution evidence has incompatible source or accounting context"
        )
    if new.journal_observed_at <= old.journal_observed_at or new.journal_observed_at > datetime.now(
        UTC
    ):
        raise WorkspaceError(409, "Resolution requires a later nonfuture journal observation")


def proof_for(principal, request):
    finding, investigation = current_pair(principal, request)
    try:
        opened = FindingDefinition.model_validate(finding["attributes"]["definition"])
        followed = InvestigationDefinition.model_validate(investigation["attributes"]["definition"])
    except ValueError as exc:
        raise WorkspaceError(409, "Only an open Finding and Investigation can be resolved") from exc
    if (
        opened.exception_run_id != followed.exception_run_id
        or opened.exception_receipt_hash != followed.exception_receipt_hash
    ):
        raise WorkspaceError(409, "Open pair does not share one retained exception")
    old = investigations.load_exception(principal, opened.exception_run_id)
    if old != opened.evidence or old.receipt_hash != opened.exception_receipt_hash:
        raise WorkspaceError(409, "Open finding differs from its original retained evidence")
    expected_finding, _, expected_investigation, _ = investigations.identities(principal, old)
    if (
        request.finding.resource_id != expected_finding
        or request.investigation.resource_id != expected_investigation
    ):
        raise WorkspaceError(409, "Resolution cannot change the original issue identity")
    new = matched_evidence(principal, request.matched_exception_run_id)
    compatible(old, new)
    return (
        ResolutionProof(
            prior_finding=request.finding,
            prior_investigation=request.investigation,
            unmatched_exception_run_id=opened.exception_run_id,
            unmatched_evidence=old,
            matched_exception_run_id=request.matched_exception_run_id,
            matched_evidence=new,
        ),
        finding,
        investigation,
    )


def proposal_for(principal, request, proof, finding, investigation):
    original = {
        "exception_run_id": proof.unmatched_exception_run_id,
        "exception_receipt_hash": proof.unmatched_evidence.receipt_hash,
    }
    definitions = [
        ResolvedFindingDefinition(resolution=proof, evidence=proof.unmatched_evidence, **original),
        ResolvedInvestigationDefinition(resolution=proof, **original),
    ]
    mutations = []
    for row, reference, definition in zip(
        [finding, investigation], [request.finding, request.investigation], definitions, strict=True
    ):
        mutations.append(
            ResourceMutation(
                resource_id=reference.resource_id,
                expected_version_id=reference.version_id,
                object_type=row["object_type"],
                identity_key=row["identity_key"],
                display_name=row["display_name"],
                access_entity=principal.scope.legal_entity_id,
                attributes={**row["attributes"], "definition": definition.model_dump(mode="json")},
                valid_from=proof.matched_evidence.journal_observed_at,
                evidence_class="SOURCE_BOUND",
            )
        )
    references = {
        UUID(identity): ref.version_id
        for identity, ref in investigations.evidence_pins(proof.matched_evidence).items()
    }
    for journal in proof.matched_evidence.matched_journals:
        if (
            journal.resource_id in references
            and references[journal.resource_id] != journal.version_id
        ):
            raise WorkspaceError(409, "Matched journal conflicts with retained source dependencies")
        references[journal.resource_id] = journal.version_id
    return ResourceProposal(
        proposal_id=UUID(int=0),
        title="Resolve reviewed source row investigation",
        rationale=request.rationale,
        access_entity=principal.scope.legal_entity_id,
        mutations=mutations,
        source_versions={m.resource_id: references for m in mutations},
    )


def prepare(principal, request: InvestigationResolutionAction):
    proof, finding, investigation = proof_for(principal, request)
    return proposal_for(principal, request, proof, finding, investigation), {
        "kind": investigations.KIND,
        "operation": "RESOLVE",
        "company_id": str(proof.unmatched_evidence.company.resource_id),
        "exception_run_id": proof.unmatched_exception_run_id,
        "matched_exception_run_id": proof.matched_exception_run_id,
        "prior_finding": request.finding.model_dump(mode="json"),
        "prior_investigation": request.investigation.model_dump(mode="json"),
    }


def invoke(principal, request: InvestigationResolutionAction):
    from finai_api.services.ontology_operations import invoke_prepared

    return InvestigationOperation.model_validate(
        invoke_prepared(principal, request, prepare)
    ).model_dump(mode="json")


def validate_publication(item, target, principal):
    if principal is None:
        raise WorkspaceError(
            422, "Resolution publication requires scoped retained-evidence validation"
        )
    model = (
        ResolvedFindingDefinition
        if item.object_type == "Finding"
        else ResolvedInvestigationDefinition
    )
    declared = model.model_validate(item.attributes["definition"])
    request = InvestigationResolutionAction(
        request_id=UUID(int=0),
        finding=declared.resolution.prior_finding,
        investigation=declared.resolution.prior_investigation,
        matched_exception_run_id=declared.resolution.matched_exception_run_id,
        rationale="Validate reviewed resolution",
    )
    proof, finding, investigation = proof_for(principal, request)
    if proof != declared.resolution:
        raise WorkspaceError(
            409, "Declared resolution differs from the retained old and new evidence"
        )
    prepared = proposal_for(principal, request, proof, finding, investigation)
    expected = next(m for m in prepared.mutations if m.object_type == item.object_type)
    if item.model_dump(mode="json") != expected.model_dump(mode="json"):
        raise WorkspaceError(
            409, "Resolution mutation differs from its exact current pair and evidence"
        )
    counterpart = next(m for m in prepared.mutations if m.object_type != item.object_type)
    paired = target(
        str(counterpart.resource_id), str(item.resource_id), "RESOLUTION_PAIRED_MUTATION"
    )
    if (
        paired.get("attributes") != counterpart.attributes
        or str(paired.get("expected_version_id")) != str(counterpart.expected_version_id)
        or paired.get("object_type") != counterpart.object_type
    ):
        raise WorkspaceError(409, "Both resolution mutations must be reviewed in the same proposal")
    for identity, reference in investigations.evidence_pins(proof.matched_evidence).items():
        resolved = target(identity, str(item.resource_id), "RESOLUTION_EVIDENCE:" + identity)
        if any(
            str(resolved[key]) != str(getattr(reference, key))
            for key in ("resource_id", "version_id", "content_hash")
        ):
            raise WorkspaceError(409, "Resolution source dependency changed before review")
    for journal in proof.matched_evidence.matched_journals:
        resolved = target(
            str(journal.resource_id), str(item.resource_id), "RESOLUTION_MATCHED_JOURNAL"
        )
        if (
            str(resolved["version_id"]) != str(journal.version_id)
            or resolved["object_type"] != "JournalEntry"
            or resolved["authority_state"] != "APPROVED"
        ):
            raise WorkspaceError(409, "Matched journal is unavailable for reviewed resolution")
