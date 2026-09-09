"""Mounted shared projection keeps revisions and drill controls over retained values."""

from contextlib import nullcontext
from uuid import UUID, uuid4

import pytest
from test_semantic_analysis_accepted_movements import case  # noqa: F401

from finai_api.domain.authority import ExactScope
from finai_api.domain.review import Principal
from finai_api.domain.semantic_analysis import ProjectionRequest
from finai_api.services import company_financial_metrics, journal_reconciliation, semantic_analysis
from finai_api.services.workspace import WorkspaceError


def test_dispatch_and_exact_evidence_drill_never_recompute(case, monkeypatch):  # noqa: F811
    history, plan, resolver, company, *_ = case
    principal = Principal(
        actor_id="worksheet-reader",
        display_name="Reader",
        permissions=("ontology_read",),
        scope=ExactScope(
            tenant_id=uuid4(), legal_entity_id=str(company), period="2025-01", currency="GEL"
        ),
    )
    invocation = UUID(history["invocation_id"])
    resolver.principal = principal
    resolver.read_session = nullcontext
    plan["implementation"] = {"implementation_id": "finance.accepted-journal-movements/v1"}

    def load(actor, identity):
        assert actor is principal
        if identity == invocation:
            return history, plan, resolver
        assert str(identity) == plan["accepted_movements"]["source_invocation_id"]
        return resolver.source_history, resolver.source_plan, resolver.source_resolver

    def denied(*args, **kwargs):
        raise AssertionError("A retained worksheet cannot execute financial calculations")

    monkeypatch.setattr(semantic_analysis, "load", load)
    monkeypatch.setattr(company_financial_metrics, "produce", denied)
    monkeypatch.setattr(journal_reconciliation, "reconcile", denied)
    request = ProjectionRequest(invocation_id=invocation, company_id=company)
    projection = semantic_analysis.project(principal, request)
    assert projection.descriptor.contract == "semantic-analysis/2"
    assert len(projection.rows) == 2
    drill = request.model_copy(
        update={
            "descriptor_sha256": projection.descriptor_sha256,
            "selected_row": projection.rows[0].key,
        }
    )
    selected = semantic_analysis.project(principal, drill).selection
    assert selected and selected.contributor_count > 0
    with pytest.raises(WorkspaceError) as stale:
        semantic_analysis.project(
            principal, drill.model_copy(update={"descriptor_sha256": "f" * 64})
        )
    assert stale.value.status == 409
    with pytest.raises(WorkspaceError) as foreign:
        semantic_analysis.project(principal, request.model_copy(update={"company_id": uuid4()}))
    assert foreign.value.status == 404
    with pytest.raises(WorkspaceError) as aggregate:
        semantic_analysis.project(principal, drill.model_copy(update={"group_by": "net"}))
    assert aggregate.value.status == 422
