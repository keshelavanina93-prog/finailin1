"""Offline shared Action boundaries; persistence dependencies are replaced explicitly."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid5

import pytest

from finai_api.domain.authority import canonical_sha256
from finai_api.domain.investigation import InvestigationAction
from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.domain.review import Principal
from finai_api.domain.source_reconciliation_exception import SourceExceptionObservation
from finai_api.services import investigation_actions as investigations
from finai_api.services import ontology_operations as operations
from finai_api.services.workspace import WorkspaceError


@pytest.fixture
def actor():
    return Principal(
        actor_id="maker",
        display_name="Maker",
        scope=dict(
            tenant_id=UUID(int=1),
            legal_entity_id=str(UUID(int=2)),
            period="2026-09",
            currency="GEL",
        ),
        permissions=("ontology_read", "ontology_propose"),
    )


@pytest.fixture
def action():
    return InvestigationAction(
        request_id=UUID(int=3),
        exception_run_id="fcr_" + "a" * 64,
        rationale="Retain this exact exception for investigation",
    )


@pytest.fixture
def prepared(actor):
    return ResourceProposal(
        proposal_id=UUID(int=0),
        title="Retained source exception",
        rationale="First maker rationale",
        access_entity=actor.scope.legal_entity_id,
        mutations=[
            ResourceMutation(
                resource_id=UUID(int=4),
                object_type="Finding",
                identity_key="offline",
                display_name="Offline fixture",
                attributes={},
                valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            )
        ],
    )


def workflow_memory(monkeypatch):
    rows = {}

    class Conn:
        def execute(self, sql, parameters):
            if sql.startswith("INSERT"):
                key = parameters[1]
                assert key not in rows
                rows[key] = parameters[5].obj
                return None
            if sql.startswith("SELECT payload"):
                found = rows.get(parameters[1])
                return SimpleNamespace(fetchone=lambda: (found,) if found else None)
            assert "pg_advisory_xact_lock" in sql

    @contextmanager
    def connection(*args):
        yield Conn()

    monkeypatch.setattr(operations.report_workflows, "scope_connection", connection)
    monkeypatch.setattr(operations.report_workflows, "set_scope", lambda *args: None)
    monkeypatch.setattr(
        operations,
        "resume",
        lambda principal, identity: {
            "operation_id": identity,
            "state": "PENDING_REVIEW",
            "frozen_rationale": rows[identity]["prepared_proposal"]["rationale"],
        },
    )
    return rows


def test_cross_actor_requests_share_effect_but_retain_distinct_intents(
    actor, action, prepared, monkeypatch
):
    rows = workflow_memory(monkeypatch)
    first = operations.invoke_prepared(
        actor, action, lambda *args: (prepared, {"kind": "SOURCE_EXCEPTION"})
    )
    other = actor.model_copy(update={"actor_id": "second-maker"})
    second_action = action.model_copy(
        update={"request_id": UUID(int=5), "rationale": "A separate maker explanation"}
    )
    second = operations.invoke_prepared(
        other,
        second_action,
        lambda *args: (
            prepared.model_copy(update={"rationale": second_action.rationale}),
            {"kind": "SOURCE_EXCEPTION"},
        ),
    )
    assert first["operation_id"] == second["operation_id"]
    assert first["intent_id"] != second["intent_id"]
    assert len(rows) == 3  # Two immutable intents and exactly one proposal effect.
    assert second["frozen_rationale"] == "First maker rationale"
    assert rows[second["intent_id"]]["invocation"]["rationale"] == second_action.rationale


def test_retry_and_request_conflict_checked_before_preparation(
    actor, action, prepared, monkeypatch
):
    workflow_memory(monkeypatch)
    callback = Mock(return_value=(prepared, {"kind": "SOURCE_EXCEPTION"}))
    first = operations.invoke_prepared(actor, action, callback)
    assert operations.invoke_prepared(actor, action, callback) == first
    callback.assert_called_once()
    changed = action.model_copy(update={"exception_run_id": "fcr_" + "b" * 64})
    with pytest.raises(WorkspaceError):
        operations.invoke_prepared(actor, changed, callback)
    callback.assert_called_once()


def test_semantic_identity_changes_with_expected_head_not_rationale(prepared):
    same = prepared.model_copy(
        update={"proposal_id": UUID(int=900), "rationale": "Different reason"}
    )
    assert operations.proposal_effect(prepared) == operations.proposal_effect(same)
    changed = prepared.model_copy(
        update={
            "mutations": [
                prepared.mutations[0].model_copy(update={"expected_version_id": UUID(int=901)})
            ]
        }
    )
    assert operations.proposal_effect(prepared) != operations.proposal_effect(changed)


def test_timeout_after_frozen_effect_recovers_without_repreparation(
    actor, action, prepared, monkeypatch
):
    rows = workflow_memory(monkeypatch)
    callback = Mock(return_value=(prepared, {"kind": investigations.KIND}))
    monkeypatch.setattr(
        operations, "resume", Mock(side_effect=TimeoutError("commit acknowledgement lost"))
    )
    with pytest.raises(TimeoutError):
        operations.invoke_prepared(actor, action, callback)
    assert len(rows) == 2
    effect = next(key for key in rows if key.startswith("opa_"))
    monkeypatch.setattr(
        operations,
        "resume",
        lambda principal, identity: {"operation_id": identity, "state": "PENDING_REVIEW"},
    )
    recovered = operations.invoke_prepared(actor, action, callback)
    assert recovered["operation_id"] == effect
    callback.assert_called_once()


def pin(n):
    return {
        "resource_id": str(UUID(int=n)),
        "version_id": str(UUID(int=n + 100)),
        "content_hash": f"{n:064x}",
    }


@pytest.fixture
def observation(actor, monkeypatch):
    context = [pin(n) for n in [2, 10, 11, 12, 13, 14, 15]]
    value = SourceExceptionObservation(
        company=pin(2),
        binding=pin(20),
        source_function=pin(21),
        context_versions=context,
        selection={
            str(i): {k: v for k, v in p.items() if k != "content_hash"}
            for i, p in enumerate(context)
        },
        source={
            "invocation_id": UUID(int=23),
            "invocation_receipt_hash": "a" * 64,
            "source_receipt_hash": "b" * 64,
            "sha256": "c" * 64,
            "evidence": pin(22),
            "document_id": "doc_" + "c" * 64,
            "sheet": "Base",
            "row": 2,
            "coordinate": "Base!S2",
        },
        source_valid_at="2025-01-31T00:00:00Z",
        source_known_at="2026-01-01T00:00:00Z",
        journal_observed_at="2026-01-02T00:00:00Z",
        reconciliation={"receipt_hash": "d" * 64, "status": "PARTIAL"},
        state="UNMATCHED_AT_SNAPSHOT",
        finding_eligible=True,
        receipt_hash="e" * 64,
    )
    monkeypatch.setattr(
        investigations.exceptions, "read", Mock(return_value=value.model_dump(mode="json"))
    )

    @contextmanager
    def resource_connection(*args, **kwargs):
        yield None

    monkeypatch.setattr(investigations.resources, "resource_connection", resource_connection)
    monkeypatch.setattr(
        investigations.resources, "_get", Mock(side_effect=WorkspaceError(404, "No head"))
    )
    return value


def test_prepare_exact_canonical_pair_from_retained_seed(actor, action, observation):
    result, contract = investigations.prepare(actor, action)
    assert [m.object_type for m in result.mutations] == ["Finding", "Investigation"]
    assert result.mutations[1].attributes["finding_id"] == str(result.mutations[0].resource_id)
    assert result.mutations[0].attributes["definition"]["evidence"] == observation.model_dump(
        mode="json"
    )
    assert result.mutations[0].attributes["definition"]["financial_impact"] is None
    assert result.mutations[0].valid_from == observation.journal_observed_at
    assert contract["exception_run_id"] == action.exception_run_id
    investigations.exceptions.read.assert_called_once_with(actor, action.exception_run_id)


def test_identity_survives_binding_revision_but_compatibility_does_not(
    actor, action, observation, monkeypatch
):
    proposal = investigations.proposal_for(actor, action, observation)
    changed = observation.model_copy(
        update={"binding": observation.binding.model_copy(update={"version_id": UUID(int=900)})}
    )
    assert investigations.identities(actor, observation) == investigations.identities(
        actor, changed
    )
    old = {"attributes": proposal.mutations[0].attributes}
    with pytest.raises(WorkspaceError, match="compatibility"):
        investigations.compatible(old, changed)
    new_source = observation.model_copy(
        update={"source": observation.source.model_copy(update={"sha256": "f" * 64})}
    )
    assert investigations.identities(actor, observation) != investigations.identities(
        actor, new_source
    )


def test_publication_reopens_seed_and_refuses_forged_definition(actor, action, observation):
    proposal = investigations.proposal_for(actor, action, observation)
    refs = {
        identity: ref.model_dump(mode="json")
        for identity, ref in investigations.evidence_pins(observation).items()
    }

    def target(identity, *args):
        if identity == str(proposal.mutations[0].resource_id):
            return {"attributes": proposal.mutations[0].attributes}
        return refs[identity]

    for mutation in proposal.mutations:
        investigations.validate_publication(mutation, target, actor)
    assert investigations.exceptions.read.call_count == 2
    forged = deepcopy(proposal.mutations[0].attributes)
    forged["definition"]["evidence"]["source"]["coordinate"] = "Base!S999"
    with pytest.raises(WorkspaceError):
        investigations.validate_publication(
            proposal.mutations[0].model_copy(update={"attributes": forged}), target, actor
        )
    with pytest.raises(WorkspaceError):
        investigations.validate_publication(proposal.mutations[0], target, None)


def test_foreign_or_excluded_seed_cannot_prepare(actor, action, observation, monkeypatch):
    foreign = actor.model_copy(
        update={"scope": actor.scope.model_copy(update={"legal_entity_id": str(UUID(int=999))})}
    )
    with pytest.raises(WorkspaceError):
        investigations.prepare(foreign, action)
    payload = observation.model_dump(mode="json")
    payload.update(
        state="EXCLUDED_SOURCE_VALUE",
        finding_eligible=False,
        exclusion_reason="MISSING_LITERAL_POSTED_AMOUNT",
    )
    monkeypatch.setattr(investigations.exceptions, "read", Mock(return_value=payload))
    with pytest.raises(WorkspaceError):
        investigations.prepare(actor, action)


def publication_versions(proposal):
    return [
        {
            "resource_id": str(m.resource_id),
            "version_id": str(uuid5(proposal.proposal_id, str(m.resource_id))),
            "proposal_id": str(proposal.proposal_id),
            "object_type": m.object_type,
            "attributes": m.model_dump(mode="json")["attributes"],
            "content_hash": canonical_sha256(m),
            "access_entity": proposal.access_entity,
            "authority_state": "APPROVED",
        }
        for m in proposal.mutations
    ]


def test_publication_requires_both_exact_proposal_owned_versions(actor, action, observation):
    proposal = investigations.proposal_for(actor, action, observation)
    versions = publication_versions(proposal)
    assert set(investigations.publication_bundle(proposal, versions)) == {
        "finding",
        "investigation",
    }
    for key, value in [
        ("proposal_id", str(UUID(int=999))),
        ("version_id", str(UUID(int=999))),
        ("content_hash", "f" * 64),
        ("access_entity", "foreign"),
    ]:
        changed = deepcopy(versions)
        changed[0][key] = value
        with pytest.raises(WorkspaceError):
            investigations.publication_bundle(proposal, changed)
    with pytest.raises(WorkspaceError):
        investigations.publication_bundle(proposal, versions[:1])


def test_approval_without_exact_readback_is_not_publication(
    actor, action, observation, monkeypatch
):
    proposal = investigations.proposal_for(actor, action, observation)
    result = {
        "operation_id": "opa_test",
        "state": "PUBLISHED",
        "proposal": {},
        "prepared_proposal_id": str(proposal.proposal_id),
        "definition": {"kind": investigations.KIND},
        "events": [],
    }
    monkeypatch.setattr(
        investigations,
        "publication",
        Mock(side_effect=WorkspaceError(409, "Missing exact version")),
    )
    detail = investigations.operation_detail(actor, result, proposal)
    assert detail["state"] == "PUBLICATION_UNAVAILABLE" and detail["publication"] is None
    assert detail["finding_id"] == str(proposal.mutations[0].resource_id)
    assert detail["business_effect_authorized"] is False
