"""Synthetic parser outputs isolate the reviewed company-consumption boundary."""

from copy import deepcopy
from hashlib import sha256
from uuid import UUID, uuid4, uuid5

import pytest

from finai_api.domain.authority import ExactScope
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.review import Principal
from finai_api.services import source_accounting_context as context
from finai_api.services import source_company_alias as aliases
from finai_api.services import source_financial_facts as facts
from finai_api.services.workspace import WorkspaceError


def fixture(monkeypatch):
    principal = Principal(
        actor_id="synthetic-refresh",
        display_name="Synthetic refresh",
        scope=ExactScope(
            tenant_id=uuid4(), legal_entity_id="synthetic", period="2026-09", currency="GEL"
        ),
        permissions=("ontology_read", "ontology_propose"),
    )
    company_id = uuid4()
    company = {
        "resource_id": str(company_id),
        "version_id": str(uuid4()),
        "object_type": "LegalEntity",
        "display_name": "Reviewed existing company",
        "authority_state": "APPROVED",
        "evidence_class": "SOURCE_BOUND",
        "attributes": {
            "evidence_id": str(
                canonical_id(
                    principal.scope.tenant_id, "SourceEvidence", sha256(b"original").hexdigest()
                )
            )
        },
    }
    chart_id = uuid5(company_id, "1c-observed-chart")
    accounts = {
        str(uuid5(chart_id, code)): {
            "resource_id": str(uuid5(chart_id, code)),
            "version_id": str(uuid4()),
            "object_type": "LocalAccount",
            "authority_state": "APPROVED",
            "attributes": {"chart_id": str(chart_id), "account_code": code},
        }
        for code in ("7310.02.1", "3110")
    }
    alias = {"resource_id": str(uuid4()), "version_id": str(uuid4())}
    calls = []

    def inspect(_p, document, sheet, profile, target):
        calls.append((document, sheet, profile, target))
        return {
            "accepted": document == "later-reviewed",
            "reason": "Snapshot alias not reviewed",
            "company": company,
            "alias": alias,
        }

    monkeypatch.setattr(aliases, "inspect", inspect)
    monkeypatch.setattr(aliases, "_effective_resources", lambda *_: {str(company_id): company})
    monkeypatch.setattr(
        facts,
        "document_bytes",
        lambda _p, document: (
            {"source_sha256": sha256(document.encode()).hexdigest()},
            document.encode(),
        ),
    )
    monkeypatch.setattr(
        facts,
        "_read_rows_cached",
        lambda content, *_: {
            "company_label": company["display_name"],
            "object_type": "SourceJournalMovement",
            "duplicate_account_rows": {},
            "rows": [
                {
                    "row": 3,
                    "debit_code": "7310.02.1",
                    "credit_code": "3110",
                    "attributes": {
                        "posting_date": "2025-11-01" if content == b"original" else "2025-12-01",
                        "amount": "15.25",
                        "source_row_key": "TR!3",
                    },
                }
            ],
        },
    )
    monkeypatch.setattr(
        facts.resources,
        "current_resources",
        lambda _p, ids: {str(i): accounts[str(i)] for i in ids if str(i) in accounts},
    )
    monkeypatch.setattr(facts.resources, "propose", lambda _p, proposal: proposal)
    monkeypatch.setattr(context, "published_context", lambda *_: {"binding": None})
    return principal, company_id, company, accounts, alias, calls


def test_new_snapshot_reuses_company_accounts_and_pins_reviewed_alias(monkeypatch):
    p, company_id, company, accounts, alias, calls = fixture(monkeypatch)
    original = facts.prepare(p, "original", "TR", "1c_journal", company_id, 0)
    frozen = deepcopy(original)
    assert not calls
    later = facts.prepare(p, "later-reviewed", "TR", "1c_journal", company_id, 0)
    first, second = original["rows"][0], later["rows"][0]
    for field in ("legal_entity_id", "debit_account_id", "credit_account_id"):
        assert first["attributes"][field] == second["attributes"][field]
    for field in ("evidence_id", "source_record_id", "source_family", "posting_date"):
        assert first["attributes"][field] != second["attributes"][field]
    assert first["resource_id"] != second["resource_id"]
    assert original == frozen
    assert second["source_versions"][alias["resource_id"]] == alias["version_id"]
    assert second["source_versions"][company["resource_id"]] == company["version_id"]
    assert later["financial_publication_status"] == "CURRENCY_AND_LEDGER_UNESTABLISHED"
    proposal = facts.propose(p, "later-reviewed", "TR", "1c_journal", company_id, 0)
    assert {m.object_type for m in proposal.mutations} == {"SourceRecord", "SourceJournalMovement"}
    assert proposal.source_versions[UUID(second["resource_id"])][
        UUID(alias["resource_id"])
    ] == UUID(alias["version_id"])
    assert all(
        UUID(a["version_id"]) in proposal.source_versions[UUID(second["resource_id"])].values()
        for a in accounts.values()
    )
    assert calls[-1] == ("later-reviewed", "TR", "1c_journal", company_id)


@pytest.mark.parametrize(
    "document", ["later-unreviewed", "other-snapshot", "wrong-company-snapshot"]
)
def test_unreviewed_snapshot_never_inherits_earlier_company_attribution(monkeypatch, document):
    p, company_id, *_ = fixture(monkeypatch)
    with pytest.raises(WorkspaceError, match="Review this source snapshot"):
        facts.prepare(p, document, "TR", "1c_journal", company_id, 0)


def test_withdrawn_alias_and_parser_refusal_propagate(monkeypatch):
    p, company_id, *_, calls = fixture(monkeypatch)

    def withdrawn(*_):
        raise WorkspaceError(409, "Company alias authority or availability was withdrawn")

    monkeypatch.setattr(aliases, "inspect", withdrawn)
    with pytest.raises(WorkspaceError, match="withdrawn"):
        facts.prepare(p, "later-reviewed", "TR", "1c_journal", company_id, 0)

    def invalid_layout(*_):
        raise WorkspaceError(422, "Journal date fields disagree")

    monkeypatch.setattr(facts, "_read_rows_cached", invalid_layout)
    with pytest.raises(WorkspaceError, match="date fields disagree"):
        facts.prepare(p, "later-reviewed", "TR", "1c_journal", company_id, 0)
    assert not calls


def test_changed_account_chart_still_refused(monkeypatch):
    p, company_id, _, accounts, *_ = fixture(monkeypatch)
    next(iter(accounts.values()))["attributes"]["chart_id"] = str(uuid4())
    with pytest.raises(WorkspaceError, match="account binding is inconsistent"):
        facts.prepare(p, "later-reviewed", "TR", "1c_journal", company_id, 0)
