"""Offline state/evidence guards for reviewed resolution; no native persistence calls."""

# ruff: noqa: F811

from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid5

import pytest
from test_investigation_actions import action, actor, observation, workflow_memory  # noqa: F401

from finai_api.domain.authority import canonical_sha256
from finai_api.domain.investigation_resolution import InvestigationResolutionAction
from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.domain.resources import ResourceProposal
from finai_api.services import investigation_actions as investigations
from finai_api.services import investigation_resolution as resolution
from finai_api.services import ontology_operations as operations
from finai_api.services.workspace import WorkspaceError


@pytest.fixture
def resolution_case(actor, action, observation, monkeypatch):
    opened = investigations.proposal_for(actor, action, observation)
    heads = {
        m.resource_id: {
            **m.model_dump(mode="json", exclude={"expected_version_id"}),
            "version_id": str(uuid5(opened.proposal_id, str(m.resource_id))),
            "content_hash": canonical_sha256(m),
            "valid_from": m.valid_from,
        }
        for m in opened.mutations
    }
    request = InvestigationResolutionAction(
        request_id=UUID(int=700),
        finding=resolution.hash_pin(heads[opened.mutations[0].resource_id]),
        investigation=resolution.hash_pin(heads[opened.mutations[1].resource_id]),
        matched_exception_run_id="fcr_" + "b" * 64,
        rationale="Review later matching evidence for this source row",
    )
    matched = observation.model_copy(
        update={
            "state": "MATCHED_AT_SNAPSHOT",
            "finding_eligible": False,
            "matched_journals": [
                VersionReference(resource_id=UUID(int=900), version_id=UUID(int=901))
            ],
            "journal_observed_at": observation.journal_observed_at + timedelta(days=1),
            "receipt_hash": "f" * 64,
        }
    )
    evidence = {
        action.exception_run_id: observation.model_dump(mode="json"),
        request.matched_exception_run_id: matched.model_dump(mode="json"),
    }
    monkeypatch.setattr(
        resolution.exceptions, "read", Mock(side_effect=lambda principal, key: evidence[key])
    )

    @contextmanager
    def cursor(**kwargs):
        yield None

    @contextmanager
    def connection(*args, **kwargs):
        yield SimpleNamespace(cursor=cursor)

    monkeypatch.setattr(resolution.resources, "resource_connection", connection)
    monkeypatch.setattr(
        resolution.resources, "_get", lambda conn, tenant, identity: heads[identity]
    )
    monkeypatch.setattr(resolution, "_current", Mock())
    return actor, request, observation, matched, heads, evidence


def test_resolution_prepares_same_ids_and_keeps_open_history(resolution_case):
    principal, request, old, new, heads, _ = resolution_case
    before = deepcopy(heads)
    proposal, definition = resolution.prepare(principal, request)
    assert heads == before
    assert [m.resource_id for m in proposal.mutations] == [
        request.finding.resource_id,
        request.investigation.resource_id,
    ]
    assert [m.expected_version_id for m in proposal.mutations] == [
        request.finding.version_id,
        request.investigation.version_id,
    ]
    assert definition["operation"] == "RESOLVE" and definition["kind"] == investigations.KIND
    for mutation in proposal.mutations:
        value = mutation.attributes["definition"]
        assert value["state"] == "RESOLVED"
        assert value["resolution"]["unmatched_evidence"] == old.model_dump(mode="json")
        assert value["resolution"]["matched_evidence"] == new.model_dump(mode="json")
        assert value["automatic_resolution"] is False
        assert mutation.valid_from == new.journal_observed_at


@pytest.mark.parametrize("failure", ["hash", "company", "authority", "old_evidence"])
def test_resolution_refuses_foreign_or_tampered_current_authority(resolution_case, failure):
    principal, request, _, _, heads, evidence = resolution_case
    if failure == "hash":
        request = request.model_copy(
            update={"finding": request.finding.model_copy(update={"content_hash": "0" * 64})}
        )
    elif failure == "company":
        principal = principal.model_copy(
            update={
                "scope": principal.scope.model_copy(update={"legal_entity_id": str(UUID(int=999))})
            }
        )
    elif failure == "authority":
        heads[request.finding.resource_id]["authority_state"] = "REVOKED"
    else:
        key = heads[request.finding.resource_id]["attributes"]["definition"]["exception_run_id"]
        evidence[key]["receipt_hash"] = "0" * 64
    with pytest.raises(WorkspaceError):
        resolution.prepare(principal, request)


def test_open_refresh_cannot_replace_source_interpretation(resolution_case):
    _, request, old, _, heads, _ = resolution_case
    previous = heads[request.finding.resource_id]
    alternatives = [
        old.model_copy(
            update={
                "source_function": old.source_function.model_copy(
                    update={"version_id": UUID(int=888)}
                )
            }
        ),
        old.model_copy(
            update={"source": old.source.model_copy(update={"invocation_id": UUID(int=889)})}
        ),
        old.model_copy(update={"source_known_at": old.source_known_at + timedelta(seconds=1)}),
    ]
    for changed in alternatives:
        with pytest.raises(WorkspaceError, match="explicit compatibility"):
            investigations.compatible(previous, changed)


@pytest.mark.parametrize(
    "field", ["binding", "source_function", "company", "source", "source_known_at", "selection"]
)
def test_changed_source_context_never_resolves(resolution_case, field):
    _, _, old, new, _, _ = resolution_case
    if field in ("binding", "source_function", "company"):
        changed = getattr(new, field).model_copy(update={"version_id": UUID(int=777)})
    elif field == "source":
        changed = new.source.model_copy(update={"invocation_id": UUID(int=778)})
    elif field == "source_known_at":
        changed = new.source_known_at + timedelta(seconds=1)
    else:
        changed = {}
    with pytest.raises(WorkspaceError, match="incompatible"):
        resolution.compatible(old, new.model_copy(update={field: changed}))


@pytest.mark.parametrize("offset", [0, -1, None])
def test_equal_older_or_future_snapshot_refused(resolution_case, offset):
    _, _, old, new, _, _ = resolution_case
    at = (
        old.journal_observed_at + timedelta(seconds=offset)
        if offset is not None
        else datetime.now(UTC) + timedelta(days=1)
    )
    with pytest.raises(WorkspaceError, match="later nonfuture"):
        resolution.compatible(old, new.model_copy(update={"journal_observed_at": at}))


def target_for(proposal, new):
    references = {
        identity: ref.model_dump(mode="json")
        for identity, ref in investigations.evidence_pins(new).items()
    }
    references.update({str(m.resource_id): m.model_dump(mode="json") for m in proposal.mutations})
    for journal in new.matched_journals:
        references[str(journal.resource_id)] = {
            **journal.model_dump(mode="json"),
            "object_type": "JournalEntry",
            "authority_state": "APPROVED",
        }
    return references


def test_generic_publication_rechecks_exact_pair_and_both_retained_records(resolution_case):
    principal, request, _, new, heads, _ = resolution_case
    proposal, _ = resolution.prepare(principal, request)
    references = target_for(proposal, new)
    for mutation in proposal.mutations:
        investigations.validate_publication(
            mutation, lambda identity, *args: references[identity], principal
        )
    assert resolution.exceptions.read.call_count == 6
    heads[request.finding.resource_id]["version_id"] = str(UUID(int=999))
    with pytest.raises(WorkspaceError, match="current company pair"):
        resolution.validate_publication(
            proposal.mutations[0], lambda identity, *args: references[identity], principal
        )


def test_single_sided_or_forged_resolution_refused(resolution_case):
    principal, request, _, new, heads, _ = resolution_case
    proposal, _ = resolution.prepare(principal, request)
    references = target_for(proposal, new)
    references[str(request.investigation.resource_id)] = heads[request.investigation.resource_id]
    with pytest.raises(WorkspaceError, match="same proposal"):
        resolution.validate_publication(
            proposal.mutations[0], lambda identity, *args: references[identity], principal
        )
    forged = deepcopy(proposal.mutations[0].attributes)
    forged["definition"]["resolution"]["matched_evidence"]["source"]["sha256"] = "0" * 64
    with pytest.raises(WorkspaceError, match="retained old and new"):
        resolution.validate_publication(
            proposal.mutations[0].model_copy(update={"attributes": forged}),
            lambda *args: None,
            principal,
        )


def test_unknown_excluded_and_mismatched_pair_refused(resolution_case):
    principal, request, _, _, heads, evidence = resolution_case
    bad = evidence[request.matched_exception_run_id]
    bad.update(
        state="EXCLUDED_SOURCE_VALUE",
        finding_eligible=False,
        matched_journals=[],
        exclusion_reason="MISSING_LITERAL_POSTED_AMOUNT",
    )
    with pytest.raises(WorkspaceError, match="matched evidence"):
        resolution.prepare(principal, request)
    heads[request.investigation.resource_id]["attributes"]["finding_id"] = str(UUID(int=999))
    with pytest.raises(WorkspaceError, match="another finding"):
        resolution.prepare(principal, request)


def test_replay_recovers_frozen_resolution_without_reopening_advanced_heads(
    resolution_case, monkeypatch
):
    principal, request, _, _, heads, _ = resolution_case
    records = workflow_memory(monkeypatch)

    def resumed(actor, identity):
        record = records[identity]
        prepared = ResourceProposal.model_validate(record["prepared_proposal"])
        result = {
            "operation_id": identity,
            "state": "PREPARED",
            "proposal": None,
            "prepared_proposal_id": str(prepared.proposal_id),
            "definition": record["definition"],
            "events": [],
        }
        return investigations.operation_detail(actor, result, prepared)

    monkeypatch.setattr(operations, "resume", resumed)
    first = resolution.invoke(principal, request)
    assert first["state"] == "PREPARED" and first["publication"] is None
    assert first["intent_request"]["matched_exception_run_id"] == request.matched_exception_run_id
    heads[request.finding.resource_id]["version_id"] = str(UUID(int=999))
    assert resolution.invoke(principal, request) == first
    assert resolution.exceptions.read.call_count == 2
