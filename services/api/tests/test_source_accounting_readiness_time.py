"""Effective read readiness and editing heads must not be interchangeable."""

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4, uuid5

import pytest
from test_definition_history import retained  # noqa: F401 - shared native fixture
from test_seg_expense_source import workbook

from finai_api.domain.resources import ResourceMutation, ResourceReview
from finai_api.services import accounting_binding_status, source_company_alias, source_documents
from finai_api.services import source_accounting_context as context
from finai_api.services.workspace import WorkspaceError


@pytest.mark.parametrize("chart_state", ["future_only", "revoked", "approved"])
def test_readiness_uses_effective_chart_scope_and_binding(monkeypatch, chart_state):
    identity, company, chart = uuid4(), uuid4(), uuid4()
    binding = uuid5(identity, "accounting-binding")
    attrs = {"chart_id": str(chart), "evidence_id": str(uuid4())}
    old_scope = {"version_id": str(uuid4())}
    old_binding = {"version_id": str(uuid4())}
    effective = {str(identity): old_scope, str(binding): old_binding}
    if chart_state != "future_only":
        effective[str(chart)] = {
            "authority_state": "APPROVED" if chart_state == "approved" else "REVOKED",
            "object_type": "LocalChartOfAccounts",
            "attributes": {"legal_entity_id": str(company)},
        }
    monkeypatch.setattr(context, "observe", lambda *_: (identity, attrs, "Base!D2", "Label"))
    monkeypatch.setattr(source_company_alias, "_effective_resources", lambda *_: effective)
    monkeypatch.setattr(
        source_company_alias,
        "inspect",
        lambda *_: {
            "company": {
                "authority_state": "APPROVED",
                "object_type": "LegalEntity",
                "evidence_class": "USER_ASSERTED",
            },
            "accepted": True,
        },
    )
    monkeypatch.setattr(context.resources, "list_resources", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(context, "source_observations", lambda *_: {})

    def editing_heads_forbidden(*_):
        raise AssertionError("Readiness must not read publication heads")

    monkeypatch.setattr(context.resources, "current_resources", editing_heads_forbidden)
    monkeypatch.setattr(
        accounting_binding_status,
        "inspect",
        lambda _p, selected: {
            "checked_version": selected["version_id"],
        },
    )
    result = context.inspect(None, "doc_synthetic", "Base", "seg_expense_base", company)
    assert result["canonical_ready"] is (chart_state == "approved")
    assert result["scope"] == old_scope and result["binding"] == old_binding
    assert result["accounting_eligibility"]["checked_version"] == old_binding["version_id"]


def proposal_context(monkeypatch):
    scope, binding = str(uuid4()), str(uuid4())
    result = {
        "canonical_ready": True,
        "scope_id": scope,
        "binding_id": binding,
        "observed": {},
        "scope": {"version_id": str(uuid4()), "authority_state": "APPROVED"},
        "binding": None,
    }
    monkeypatch.setattr(context, "inspect", lambda *_: result)
    return result


def test_future_only_scope_is_not_recreated(monkeypatch):
    result = proposal_context(monkeypatch)
    result["scope"] = None
    monkeypatch.setattr(
        context.resources,
        "current_resources",
        lambda *_: {
            result["scope_id"]: {"version_id": str(uuid4()), "attributes": {}},
        },
    )
    with pytest.raises(WorkspaceError, match="already published or scheduled"):
        context.propose_scope(None, "doc_synthetic", "Base", "seg_expense_base", uuid4())


@pytest.mark.parametrize("changed", ["scope", "binding"])
def test_current_binding_form_cannot_replace_scheduled_publication(monkeypatch, changed):
    result = proposal_context(monkeypatch)
    heads = {result["scope_id"]: result["scope"]}
    heads[result[changed + "_id"]] = {"version_id": str(uuid4())}
    monkeypatch.setattr(context.resources, "current_resources", lambda *_: heads)
    with pytest.raises(WorkspaceError, match="newer or scheduled publication"):
        context.propose_binding(None, "doc_synthetic", "Base", "seg_expense_base", uuid4(), None)


def test_current_binding_edit_retains_expected_version(monkeypatch):
    result = proposal_context(monkeypatch)
    result["binding"] = {"version_id": str(uuid4()), "attributes": {"source_use": "OLD"}}
    heads = {result[name + "_id"]: result[name] for name in ("scope", "binding")}
    monkeypatch.setattr(context.resources, "current_resources", lambda *_: heads)
    monkeypatch.setattr(context.resources, "propose", lambda _p, draft: draft)
    selection = SimpleNamespace(
        rationale="Explicit synthetic reviewed source use",
        model_dump=lambda **_: {"source_use": "STRUCTURAL_REFERENCE"},
    )
    principal = SimpleNamespace(scope=SimpleNamespace(legal_entity_id="synthetic"))
    draft = context.propose_binding(
        principal, "doc_synthetic", "Base", "seg_expense_base", uuid4(), selection
    )
    assert str(draft.mutations[0].expected_version_id) == result["binding"]["version_id"]


@pytest.mark.skipif(os.environ.get("G8_BINDING_DB_TEST") != "1", reason="Opt-in native DB")
def test_native_future_chart_and_binding_readiness(retained):  # noqa: F811
    reader, publish = retained
    p = reader.model_copy(
        update={
            "permissions": (
                "ingest",
                "ontology_read",
                "ontology_admin",
                "ontology_propose",
                "ontology_review",
            )
        }
    )
    reviewer = p.model_copy(update={"actor_id": "synthetic-readiness-reviewer"})

    def approve(detail):
        context.resources.review(
            reviewer,
            detail.proposal.proposal_id,
            ResourceReview(
                decision="APPROVED",
                rationale="Review synthetic current readiness fixture",
            ),
        )

    company = ResourceMutation(
        object_type="LegalEntity",
        identity_key="synthetic:" + uuid4().hex,
        display_name="Synthetic readiness company",
        attributes={},
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
    )
    publish(company)
    content = workbook(replacement={"D2": "Synthetic readiness label " + uuid4().hex})
    document = source_documents.retain_document(p, "SYNTHETIC readiness.xlsx", content)[
        "document_id"
    ]
    approve(
        source_company_alias.propose(
            p,
            document,
            "Base",
            "seg_expense_base",
            company.resource_id,
            "Review existing synthetic company identity against retained source label",
        )
    )
    chart = ResourceMutation(
        resource_id=uuid5(company.resource_id, "1c-observed-chart"),
        object_type="LocalChartOfAccounts",
        identity_key="synthetic:" + uuid4().hex,
        display_name="Synthetic future source chart",
        attributes={"code": "SYNTHETIC", "legal_entity_id": str(company.resource_id)},
        valid_from=datetime.now(UTC) + timedelta(days=30),
    )
    future_chart = publish(chart)[0]
    result = context.inspect(p, document, "Base", "seg_expense_base", company.resource_id)
    assert not result["canonical_ready"]
    assert any("no accepted source chart" in reason for reason in result["unresolved"])
    publish(
        chart.model_copy(
            update={
                "expected_version_id": UUID(future_chart["version_id"]),
                "valid_from": datetime.now(UTC),
            }
        )
    )
    approve(context.propose_scope(p, document, "Base", "seg_expense_base", company.resource_id))
    selection = context.ContextSelection(
        source_use="STRUCTURAL_REFERENCE",
        rationale="Explicit synthetic structural use only",
    )
    approve(
        context.propose_binding(
            p,
            document,
            "Base",
            "seg_expense_base",
            company.resource_id,
            selection,
        )
    )
    before = context.inspect(p, document, "Base", "seg_expense_base", company.resource_id)
    binding = before["binding"]
    scheduled = ResourceMutation(
        resource_id=UUID(binding["resource_id"]),
        expected_version_id=UUID(binding["version_id"]),
        object_type="SourceAccountingBinding",
        identity_key=binding["identity_key"],
        display_name="Future synthetic structural selection",
        attributes={
            **binding["attributes"],
            "rationale": "Scheduled synthetic structural revision",
        },
        valid_from=datetime.now(UTC) + timedelta(days=30),
    )
    publish(scheduled)
    after = context.inspect(p, document, "Base", "seg_expense_base", company.resource_id)
    assert after["binding"] == binding
    assert after["accounting_eligibility"]["eligible_for_accounting"] is False
    with pytest.raises(WorkspaceError, match="newer or scheduled publication"):
        context.propose_binding(
            p, document, "Base", "seg_expense_base", company.resource_id, selection
        )
