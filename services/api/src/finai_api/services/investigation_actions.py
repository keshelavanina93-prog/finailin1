"""Canonical investigation proposals over retained source exceptions; no financial writes."""

from uuid import UUID, uuid5

from psycopg.rows import dict_row

from finai_api.domain.authority import canonical_sha256
from finai_api.domain.investigation import (
    FindingDefinition,
    InvestigationAction,
    InvestigationDefinition,
    InvestigationOperation,
)
from finai_api.domain.metric_execution import Pin
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.domain.source_reconciliation_exception import SourceExceptionObservation
from finai_api.services import resources
from finai_api.services import source_reconciliation_exception as exceptions
from finai_api.services.entity_movement_review import digest
from finai_api.services.workspace import WorkspaceError

KIND = "SOURCE_EXCEPTION_INVESTIGATION"
FINDING_KIND = "SOURCE_ROW_WITHOUT_ACCEPTED_JOURNAL"


def load_exception(principal, run_id):
    retained = exceptions.read(principal, run_id)
    observation = SourceExceptionObservation.model_validate(
        {key: retained[key] for key in SourceExceptionObservation.model_fields if key in retained}
    )
    if (
        str(observation.company.resource_id) != principal.scope.legal_entity_id
        or observation.state != "UNMATCHED_AT_SNAPSHOT"
        or not observation.finding_eligible
    ):
        raise WorkspaceError(409, "Only this company's retained unmatched row can open a finding")
    return observation


def identities(principal, observation):
    # Binding revisions and refresh clocks are observations, never identity ingredients.
    key = "source-row:" + digest(
        [
            str(observation.company.resource_id),
            observation.source.sha256,
            observation.source.coordinate,
            FINDING_KIND,
        ]
    )
    finding = canonical_id(principal.scope.tenant_id, "Finding", key)
    investigation_key = "finding:" + str(finding)
    return (
        finding,
        key,
        canonical_id(principal.scope.tenant_id, "Investigation", investigation_key),
        investigation_key,
    )


def evidence_pins(observation):
    result = {}
    for reference in [
        observation.company,
        observation.binding,
        observation.source_function,
        observation.source.evidence,
        *observation.context_versions,
    ]:
        identity = str(reference.resource_id)
        if identity in result and result[identity] != reference:
            raise WorkspaceError(409, "Exception evidence contains conflicting exact versions")
        result[identity] = reference
    return result


def proposal_for(principal, request, observation):
    finding, finding_key, investigation, investigation_key = identities(principal, observation)
    finding_definition = FindingDefinition(
        kind=FINDING_KIND,
        exception_run_id=request.exception_run_id,
        exception_receipt_hash=observation.receipt_hash,
        evidence=observation,
    )
    investigation_definition = InvestigationDefinition(
        exception_run_id=request.exception_run_id, exception_receipt_hash=observation.receipt_hash
    )
    common = {
        "legal_entity_id": str(observation.company.resource_id),
        "evidence_id": str(observation.source.evidence.resource_id),
    }
    mutations = [
        ResourceMutation(
            resource_id=finding,
            expected_version_id=request.expected_finding_version_id,
            object_type="Finding",
            identity_key=finding_key,
            display_name="Source row lacks an accepted journal",
            access_entity=principal.scope.legal_entity_id,
            attributes={**common, "definition": finding_definition.model_dump(mode="json")},
            valid_from=observation.journal_observed_at,
            evidence_class="SOURCE_BOUND",
        ),
        ResourceMutation(
            resource_id=investigation,
            expected_version_id=request.expected_investigation_version_id,
            object_type="Investigation",
            identity_key=investigation_key,
            display_name="Investigate source row reconciliation",
            access_entity=principal.scope.legal_entity_id,
            attributes={
                **common,
                "finding_id": str(finding),
                "definition": investigation_definition.model_dump(mode="json"),
            },
            valid_from=observation.journal_observed_at,
            evidence_class="SOURCE_BOUND",
        ),
    ]
    pins = {UUID(identity): ref.version_id for identity, ref in evidence_pins(observation).items()}
    return ResourceProposal(
        proposal_id=UUID(int=0),
        title="Investigate an unmatched source row",
        rationale=request.rationale,
        access_entity=principal.scope.legal_entity_id,
        mutations=mutations,
        source_versions={finding: pins, investigation: pins},
    )


def compatible(previous, observation):
    old = FindingDefinition.model_validate(previous["attributes"]["definition"]).evidence
    if (
        old.binding != observation.binding
        or old.selection != observation.selection
        or evidence_context(old) != evidence_context(observation)
    ):
        raise WorkspaceError(
            409, "Changed binding or accounting context requires explicit compatibility"
        )


def evidence_context(observation):
    return sorted(
        (str(p.resource_id), str(p.version_id), p.content_hash)
        for p in observation.context_versions
    )


def prepare(principal, request: InvestigationAction):
    observation = load_exception(principal, request.exception_run_id)
    prepared = proposal_for(principal, request, observation)
    with resources.resource_connection(principal, repeatable_read=True) as conn:
        previous = []
        for mutation in prepared.mutations:
            try:
                head = resources._get(conn, principal.scope.tenant_id, mutation.resource_id)
            except WorkspaceError as exc:
                if exc.status != 404:
                    raise
                head = None
            previous.append(head)
            if head is None:
                if mutation.expected_version_id is not None:
                    raise WorkspaceError(409, "Expected investigation head is unavailable")
                continue
            if (
                head["object_type"] != mutation.object_type
                or head["access_entity"] != principal.scope.legal_entity_id
                or head["authority_state"] != "APPROVED"
            ):
                raise WorkspaceError(409, "Investigation resource is unavailable for this company")
            if mutation.expected_version_id is None:
                if head["attributes"] != mutation.attributes:
                    raise WorkspaceError(
                        409, "Existing investigation requires paired exact expected heads"
                    )
            elif str(head["version_id"]) != str(mutation.expected_version_id):
                raise WorkspaceError(409, "Investigation changed; reopen its current version")
        if (previous[0] is None) != (previous[1] is None):
            raise WorkspaceError(409, "Finding and Investigation membership is incomplete")
        if previous[0] is not None and previous[1] is not None:
            compatible(previous[0], observation)
            old_investigation = InvestigationDefinition.model_validate(
                previous[1]["attributes"]["definition"]
            )
            old_finding = FindingDefinition.model_validate(previous[0]["attributes"]["definition"])
            if (
                previous[1]["attributes"].get("finding_id")
                != str(prepared.mutations[0].resource_id)
                or old_investigation.exception_run_id != old_finding.exception_run_id
            ):
                raise WorkspaceError(
                    409, "Investigation does not reference the same finding observation"
                )
    return prepared, {
        "kind": KIND,
        "exception_run_id": request.exception_run_id,
        "company_id": str(observation.company.resource_id),
    }


def invoke(principal, request: InvestigationAction):
    from finai_api.services.ontology_operations import invoke_prepared

    return InvestigationOperation.model_validate(
        invoke_prepared(principal, request, prepare)
    ).model_dump(mode="json")


def validate_publication(item, target, principal):
    if principal is None:
        raise WorkspaceError(422, "Retained exception publication requires scoped validation")
    model = FindingDefinition if item.object_type == "Finding" else InvestigationDefinition
    definition = model.model_validate(item.attributes["definition"])
    request = InvestigationAction(
        request_id=UUID(int=0),
        exception_run_id=definition.exception_run_id,
        rationale="Validate retained exception publication",
        expected_finding_version_id=item.expected_version_id,
        expected_investigation_version_id=item.expected_version_id,
    )
    observation = load_exception(principal, request.exception_run_id)
    prepared = proposal_for(principal, request, observation)
    expected = next(m for m in prepared.mutations if m.object_type == item.object_type)
    if (
        item.resource_id != expected.resource_id
        or item.identity_key != expected.identity_key
        or item.attributes != expected.attributes
        or item.valid_from != expected.valid_from
        or item.valid_to is not None
        or item.authority_state != "APPROVED"
        or item.evidence_class != "SOURCE_BOUND"
        or item.access_entity not in (None, principal.scope.legal_entity_id)
    ):
        raise WorkspaceError(409, "Finding publication differs from exact retained source evidence")
    if item.object_type == "Finding" and item.expected_version_id is not None:
        with resources.resource_connection(principal) as conn:
            previous = resources._get(conn, principal.scope.tenant_id, item.resource_id)
        if str(previous["version_id"]) != str(item.expected_version_id):
            raise WorkspaceError(409, "Finding changed before publication")
        compatible(previous, observation)
    for identity, reference in evidence_pins(observation).items():
        resolved = target(identity, str(item.resource_id), "INVESTIGATION_EVIDENCE:" + identity)
        if any(
            str(resolved[key]) != str(getattr(reference, key))
            for key in ("resource_id", "version_id", "content_hash")
        ):
            raise WorkspaceError(409, "Finding evidence changed before publication")
    if item.object_type == "Investigation":
        finding = target(
            str(prepared.mutations[0].resource_id), str(item.resource_id), "INVESTIGATION_FINDING"
        )
        if finding["attributes"] != prepared.mutations[0].attributes:
            raise WorkspaceError(409, "Investigation must bind the exact finding observation")


def publication(principal, proposal):
    with resources.resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cur:
        versions = cur.execute(
            "SELECT * FROM resource_versions WHERE tenant_id=%s AND proposal_id=%s "
            "AND version_id=ANY(%s::uuid[])",
            (
                principal.scope.tenant_id,
                proposal.proposal_id,
                [uuid5(proposal.proposal_id, str(m.resource_id)) for m in proposal.mutations],
            ),
        ).fetchall()
    return publication_bundle(proposal, versions)


def publication_bundle(proposal, versions):
    expected = {str(m.resource_id): m for m in proposal.mutations}
    if (
        len(versions) != 2
        or len(expected) != 2
        or {str(v["resource_id"]) for v in versions} != set(expected)
        or {m.object_type for m in proposal.mutations} != {"Finding", "Investigation"}
    ):
        raise WorkspaceError(409, "Exact Finding and Investigation publication is unavailable")
    result = {}
    for version in versions:
        mutation = expected[str(version["resource_id"])]
        if (
            str(version["proposal_id"]) != str(proposal.proposal_id)
            or str(version["version_id"])
            != str(uuid5(proposal.proposal_id, str(mutation.resource_id)))
            or version["object_type"] != mutation.object_type
            or version["content_hash"] != canonical_sha256(mutation)
            or version["attributes"] != mutation.model_dump(mode="json")["attributes"]
            or version["access_entity"] != proposal.access_entity
            or version["authority_state"] != "APPROVED"
        ):
            raise WorkspaceError(409, "Published investigation differs from the frozen proposal")
        result[mutation.object_type.lower()] = Pin.model_validate(
            {k: version[k] for k in ("resource_id", "version_id", "content_hash")}
        ).model_dump(mode="json")
    return result


def operation_detail(principal, result, prepared):
    ids = {m.object_type: m.resource_id for m in prepared.mutations}
    if set(ids) != {"Finding", "Investigation"} or len(prepared.mutations) != 2:
        raise WorkspaceError(409, "Invalid investigation Action effect")
    result = {
        **result,
        "finding_id": ids["Finding"],
        "investigation_id": ids["Investigation"],
        "frozen_rationale": prepared.rationale,
        "publication": None,
    }
    if result["state"] == "PUBLISHED":
        try:
            result["publication"] = publication(principal, prepared)
        except WorkspaceError as exc:
            if exc.status not in (404, 409):
                raise
            result.update(state="PUBLICATION_UNAVAILABLE", publication_limitation=exc.detail)
    return InvestigationOperation.model_validate(result).model_dump(mode="json")
