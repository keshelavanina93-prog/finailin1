"""Actual generic review over synthetic retained finance evidence and memory SQL."""

import socket
from copy import deepcopy
from uuid import uuid4, uuid5

import pytest
from investigation_full_review_support import full_graph

from finai_api.domain.investigation_resolution import InvestigationResolutionAction
from finai_api.domain.resources import ResourceReview
from finai_api.services import accounting_consumption, resources
from finai_api.services import investigation_resolution as resolution
from finai_api.services import source_reconciliation_exception as exceptions
from finai_api.services.workspace import WorkspaceError


@pytest.fixture
def graph(monkeypatch):
    def deny_network(*args, **kwargs):
        raise AssertionError("Full review regression must not access native services")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(socket, "create_connection", deny_network)
    result = full_graph()
    for module in (resources, accounting_consumption):
        monkeypatch.setattr(module, "resource_connection", result.connection)
    monkeypatch.setattr(exceptions.fact_runs, "read_run", lambda p, k: deepcopy(result.runs[k]))
    return result


def request_for(graph):
    finding, investigation = graph.opened.mutations
    return InvestigationResolutionAction(
        request_id=uuid4(),
        finding=resolution.hash_pin(graph.rows[str(finding.resource_id)]),
        investigation=resolution.hash_pin(graph.rows[str(investigation.resource_id)]),
        matched_exception_run_id=graph.ns["new_run"]["run_id"],
        rationale="Complete synthetic accounting graph review regression",
    )


def test_complete_resolution_propose_review_readback_and_retry(graph):
    principal = graph.principal
    proposal, _ = resolution.prepare(principal, request_for(graph))
    detail = resources.propose(principal, proposal)
    assert detail.decision is None
    audit = detail.validation["co_publication_constraints"]
    assert len(audit) == 2
    assert {c["relation"] for c in audit} == {"RESOLUTION_PAIRED_MUTATION"}
    deps = detail.validation["dependencies"]
    assert not any(
        d["relation"] == "RESOLUTION_PAIRED_MUTATION" for ds in deps.values() for d in ds
    )
    assert any(d["relation"] == "FIELD:finding_id" for ds in deps.values() for d in ds)
    approval = ResourceReview(decision="APPROVED", rationale="Independent synthetic review")
    with pytest.raises(WorkspaceError, match="separate identity steward") as caught:
        resources.review(principal, proposal.proposal_id, approval)
    assert caught.value.status == 403
    assert not graph.decisions
    checker = principal.model_copy(
        update={
            "actor_id": "independent-synthetic-checker",
            "permissions": (*principal.permissions, "ontology_review"),
        }
    )
    accepted = resources.review(checker, proposal.proposal_id, approval)
    assert accepted.decision == "APPROVED"
    assert len(graph.decisions) == 1
    for mutation in proposal.mutations:
        row = graph.rows[str(mutation.resource_id)]
        assert row["version_id"] == uuid5(proposal.proposal_id, str(mutation.resource_id))
        assert row["attributes"] == mutation.attributes
        assert row["proposal_id"] == proposal.proposal_id
    before = deepcopy((graph.rows, graph.edges, graph.decisions))
    assert resources.review(checker, proposal.proposal_id, approval) == accepted
    assert resources.proposal_detail(checker, proposal.proposal_id).decision == "APPROVED"
    assert (graph.rows, graph.edges, graph.decisions) == before


@pytest.mark.parametrize(
    "change,reason",
    [
        ("currency", "incompatible active bindings"),
        ("source", "contradicts its exact parent or source"),
        ("manifest", "invalid canonical journal manifest"),
        ("head", "exact approved current company pair"),
        ("pair", "reviewed together"),
        ("cycle", "cycle"),
    ],
)
def test_complete_review_rejects_changed_accounting_or_resolution_context(graph, change, reason):
    request = request_for(graph)
    if change == "currency":
        graph.entry["attributes"]["currency_id"] = str(uuid4())
    elif change == "source":
        graph.entry["attributes"]["evidence_id"] = str(uuid4())
    elif change == "manifest":
        graph.entry["attributes"]["definition"]["line_ids"] = []
    elif change == "head":
        graph.rows[str(graph.opened.mutations[0].resource_id)]["version_id"] = uuid4()
    elif change == "cycle":
        finding = graph.rows[str(graph.opened.mutations[0].resource_id)]
        graph.edges.append(
            {
                "version_id": graph.entry["version_id"],
                "target_resource_id": finding["resource_id"],
                "target_version_id": finding["version_id"],
                "relation": "FIELD:causal_input",
            }
        )
    with pytest.raises(WorkspaceError, match=reason):
        proposal, _ = resolution.prepare(graph.principal, request)
        if change == "pair":
            proposal = proposal.model_copy(update={"mutations": proposal.mutations[:1]})
        resources.propose(graph.principal, proposal)
    assert not graph.decisions
