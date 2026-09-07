"""Native readback fixtures do not claim financial publication acceptance."""
# ruff: noqa: F811

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from psycopg.errors import RaiseException
from test_definition_history import DB, item, retained  # noqa: F401

from finai_api.domain.resources import ResourceReview
from finai_api.services import company_journals as journals
from finai_api.services import period_control, resources
from finai_api.services.workspace import WorkspaceError


def test_snapshot_bounds_and_missing_lines_never_balance():
    with pytest.raises(WorkspaceError):
        journals.read_time(datetime.now())
    with pytest.raises(WorkspaceError):
        journals.read_time(datetime.now(UTC) + timedelta(days=1))
    entry = {
        "attributes": {
            "definition": {
                "contract": "balanced-journal/1",
                "line_ids": [str(uuid4()), str(uuid4())],
            }
        }
    }
    integrity = journals.check_integrity(entry, {}, [], [])
    assert integrity["state"] == "INCOMPLETE_OR_UNAVAILABLE" and integrity["balance"] is None


@pytest.mark.parametrize(
    "owner,field",
    [
        ("binding", "ledger_id"),
        ("binding", "period_id"),
        ("binding", "currency_id"),
        ("scope", "legal_entity_id"),
        ("scope", "chart_id"),
        ("book", "ledger_id"),
    ],
)
def test_exact_binding_context_mismatch_refused(owner, field):
    def node(kind):
        return {
            "resource_id": str(uuid4()),
            "version_id": str(uuid4()),
            "object_type": kind,
            "authority_state": "APPROVED",
            "attributes": {},
        }

    selected = {
        key: journals.pin(node(kind))
        for key, kind in [
            ("legal_entity_id", "LegalEntity"),
            ("ledger_id", "Ledger"),
            ("period_id", "FiscalPeriod"),
            ("currency_id", "Currency"),
            ("chart_id", "LocalChartOfAccounts"),
        ]
    }
    entry = node("JournalEntry")
    binding = node("SourceAccountingBinding")
    scope = node("SourceAccountingScope")
    book = node("AccountingBook")
    selected["book_id"] = journals.pin(book)
    cache = {(entry["version_id"], key): pin for key, pin in selected.items()}
    cache[(entry["version_id"], "accounting_binding_id")] = binding
    cache[(binding["version_id"], "book_id")] = book
    cache[(binding["version_id"], "scope_id")] = scope
    for key in ["ledger_id", "period_id", "currency_id"]:
        cache[(binding["version_id"], key)] = selected[key]
    for key in ["legal_entity_id", "chart_id"]:
        cache[(scope["version_id"], key)] = selected[key]
    cache[(book["version_id"], "ledger_id")] = selected["ledger_id"]
    assert journals.belongs(None, None, entry, selected, None, cache)
    target = {"binding": binding, "scope": scope, "book": book}[owner]
    cache[(target["version_id"], field)] = {**selected[field], "version_id": str(uuid4())}
    assert journals.belongs(None, None, entry, selected, None, cache) is None


@DB
def test_native_exact_bundle_book_scope_and_hidden_line(retained, monkeypatch):
    reader, publish = retained
    full = reader.model_copy(update={"permissions": ("ontology_read", "restricted_read")})

    def resource(kind, attrs, **kw):
        return item(kind, attrs, **kw).model_copy(update={"evidence_class": "USER_ASSERTED"})

    company = resource("LegalEntity", {})
    chart = resource(
        "LocalChartOfAccounts", {"code": "SYNTHETIC", "legal_entity_id": str(company.resource_id)}
    )
    currency = resource("Currency", {"code": "XTS"})
    calendar = resource("FiscalCalendar", {"code": "SYNTHETIC"})
    period = resource(
        "FiscalPeriod",
        {
            "calendar_id": str(calendar.resource_id),
            "starts_on": "2026-01-01",
            "ends_on": "2026-01-31",
        },
    )
    ledger = resource(
        "Ledger",
        {
            "legal_entity_id": str(company.resource_id),
            "chart_id": str(chart.resource_id),
            "calendar_id": str(calendar.resource_id),
            "currency_id": str(currency.resource_id),
        },
    )
    book = resource("AccountingBook", {"ledger_id": str(ledger.resource_id), "code": "SYNTHETIC"})
    other_book = resource("AccountingBook", {"ledger_id": str(ledger.resource_id), "code": "OTHER"})
    evidence = resource(
        "SourceEvidence", {"sha256": "b" * 64, "source_system": "SYNTHETIC_READBACK_ONLY"}
    )
    record = resource(
        "SourceRecord", {"evidence_id": str(evidence.resource_id), "coordinate": "SYNTHETIC!A1"}
    )
    scope = resource(
        "SourceAccountingScope",
        {
            "document_id": "synthetic-readback-only",
            "source_record_id": str(record.resource_id),
            "legal_entity_id": str(company.resource_id),
            "chart_id": str(chart.resource_id),
            "worksheet": "SYNTHETIC",
            "source_profile": "1c_journal",
            "observed_from": "2026-01-01",
            "observed_through": "2026-01-31",
            "date_basis": "SYNTHETIC",
            "coverage_state": "UNESTABLISHED",
            "evidence_id": str(evidence.resource_id),
        },
    )
    binding = resource(
        "SourceAccountingBinding",
        {
            "scope_id": str(scope.resource_id),
            "source_use": "REVIEW_CANDIDATE",
            "ledger_id": str(ledger.resource_id),
            "book_id": str(book.resource_id),
            "period_id": str(period.resource_id),
            "currency_id": str(currency.resource_id),
            "rationale": "SYNTHETIC SQL read fixture, not accepted accounting meaning",
        },
    )
    account = resource(
        "LocalAccount", {"chart_id": str(chart.resource_id), "account_code": "SYNTHETIC"}
    )
    line_ids = [uuid4(), uuid4()]
    entry = resource(
        "JournalEntry",
        {
            "legal_entity_id": str(company.resource_id),
            "ledger_id": str(ledger.resource_id),
            "period_id": str(period.resource_id),
            "reference": "SYNTHETIC_READBACK_ONLY",
            "posting_date": "2026-01-15",
            "accounting_binding_id": str(binding.resource_id),
            "definition": {
                "contract": "balanced-journal/1",
                "line_ids": [str(i) for i in line_ids],
            },
        },
    )
    lines = [
        resource(
            "JournalLine",
            {
                "journal_id": str(entry.resource_id),
                "accounting_binding_id": str(binding.resource_id),
                "account_id": str(account.resource_id),
                "source_record_id": str(record.resource_id),
                "side": side,
                "amount": {"amount": "12.50", "currency_id": str(currency.resource_id)},
            },
            resource_id=identity,
        )
        for identity, side in zip(line_ids, ["DEBIT", "CREDIT"], strict=True)
    ]
    # Explicit readback-only fixture construction. All financial guards restored before reads;
    # canonical storage, exact dependency creation, review and RLS remain real throughout.
    with monkeypatch.context() as fixture:
        fixture.setattr(
            "finai_api.services.source_accounting_context.validate_context", lambda *_: None
        )
        fixture.setattr(
            "finai_api.services.accounting_promotion.validate_journal",
            lambda obj, target: target(
                obj.attributes["accounting_binding_id"],
                str(obj.resource_id),
                "ACCOUNTING_INTERPRETATION",
            ),
        )
        fixture.setattr(
            "finai_api.services.accounting_promotion.validate_current_binding", lambda *_: None
        )
        fixture.setattr(
            "finai_api.services.accounting_consumption.validate_accounting_proposal",
            lambda *_: None,
        )
        published = publish(
            company,
            chart,
            currency,
            calendar,
            period,
            ledger,
            book,
            other_book,
            evidence,
            record,
            scope,
            binding,
            account,
        )
        control_maker = full.model_copy(
            update={"permissions": ("ontology_read", "ontology_propose", "ontology_review")}
        )
        selected = journals.selection(
            full,
            company.resource_id,
            ledger.resource_id,
            book.resource_id,
            period.resource_id,
            datetime.now(UTC),
        )
        control_request = period_control.ProposalRequest(
            selection=selected,
            request_id=uuid4(),
            expected_version_id=None,
            state="OPEN",
            reason="SYNTHETIC readback fixture posting gate only",
        )
        control_result = period_control.propose(control_maker, control_request)
        resources.review(
            control_maker.model_copy(update={"actor_id": "synthetic-posting-checker"}),
            UUID(control_result["proposal_id"]),
            ResourceReview(
                decision="APPROVED", rationale="Independent synthetic posting gate approval"
            ),
        )
        published = publish(entry, *lines)
    entry_version = next(
        row["version_id"] for row in published if row["resource_id"] == str(entry.resource_id)
    )
    args = (full, company.resource_id, ledger.resource_id, book.resource_id, period.resource_id)
    listing = journals.list_journals(*args)
    assert listing["total"] == 1 and listing["coverage"]["state"] == "COMPLETE"
    at = datetime.fromisoformat(listing["snapshot_at"])
    detail = journals.detail(*args, entry.resource_id, UUID(entry_version), snapshot_at=at)
    assert detail["integrity"]["state"] == "COMPLETE_BALANCED"
    assert detail["integrity"]["balance"]["debit"] == "12.50"
    assert not detail["binding_eligibility"]["eligible_for_accounting"]
    assert (
        journals.list_journals(
            full,
            company.resource_id,
            ledger.resource_id,
            other_book.resource_id,
            period.resource_id,
        )["total"]
        == 0
    )
    incomplete = journals.check_integrity(
        detail["journal"], detail["binding"], detail["lines"][:1], []
    )
    assert incomplete["state"] == "INCOMPLETE_OR_UNAVAILABLE"
    assert incomplete["balance"] is None
    outsider = reader.model_copy(
        update={
            "scope": reader.scope.model_copy(
                update={"legal_entity_id": "synthetic-other-" + uuid4().hex}
            )
        }
    )
    with pytest.raises(WorkspaceError):
        journals.list_journals(outsider, *args[1:])
    state = period_control.read(control_maker, *args[1:])
    lock_request = control_request.model_copy(
        update={
            "request_id": uuid4(),
            "state": "LOCKED",
            "expected_version_id": UUID(state["control"]["version_id"]),
            "reason": "SYNTHETIC SQL guard refusal verification only",
        }
    )
    period_control.propose(control_maker, lock_request)
    resources.review(
        control_maker.model_copy(update={"actor_id": "synthetic-posting-checker"}),
        lock_request.request_id,
        ResourceReview(decision="APPROVED", rationale="Independent synthetic lock"),
    )
    versions = {row["resource_id"]: UUID(row["version_id"]) for row in published}
    corrections = [
        obj.model_copy(update={"expected_version_id": versions[str(obj.resource_id)]})
        for obj in [entry, *lines]
    ]
    with monkeypatch.context() as bypass:
        bypass.setattr(
            "finai_api.services.accounting_promotion.validate_journal",
            lambda obj, target: target(
                obj.attributes["accounting_binding_id"],
                str(obj.resource_id),
                "ACCOUNTING_INTERPRETATION",
            ),
        )
        bypass.setattr(
            "finai_api.services.accounting_promotion.validate_current_binding", lambda *_: None
        )
        bypass.setattr(
            "finai_api.services.accounting_consumption.validate_accounting_proposal",
            lambda *_: None,
        )
        # Deliberately pin the LOCKED control while bypassing only the application gate.
        bypass.setattr(
            "finai_api.services.period_control.require_open",
            lambda conn, p, obj, binding, target, proposal: target(
                control_result["control_id"], str(obj.resource_id), "PERIOD_POSTING_CONTROL"
            ),
        )
        with pytest.raises(RaiseException, match="Current reviewed OPEN period control required"):
            publish(*corrections)
    assert (
        resources.get_resource(reader, entry.resource_id)["resource"]["version_id"] == entry_version
    )
