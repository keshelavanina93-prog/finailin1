"""Current structural posting controls, not accounting close or ERP effects."""

# ruff: noqa: F811
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from test_definition_history import DB, item, retained  # noqa: F401

from finai_api.domain.resources import ResourceReview
from finai_api.services import period_control as controls
from finai_api.services import resources
from finai_api.services.workspace import WorkspaceError


def test_explicit_state_reason_and_complete_selection():
    for state in ["CLOSED", "open", None]:
        with pytest.raises(ValidationError):
            controls.Definition(state=state, reason="Explicit structural control reason")
    with pytest.raises(ValidationError):
        controls.Definition(state="OPEN", reason="          ")
    with pytest.raises(ValidationError):
        controls.ProposalRequest(
            selection={},
            request_id=uuid4(),
            expected_version_id=None,
            state="OPEN",
            reason="Explicit structural control reason",
        )


@DB
def test_reviewed_lock_reopen_retry_and_optimistic_state(retained):
    reader, publish = retained

    def node(kind, attrs):
        return item(kind, attrs).model_copy(update={"evidence_class": "USER_ASSERTED"})

    company = node("LegalEntity", {})
    chart = node(
        "LocalChartOfAccounts", {"legal_entity_id": str(company.resource_id), "code": "SYNTHETIC"}
    )
    currency = node("Currency", {"code": "XTS"})
    calendar = node("FiscalCalendar", {"code": "SYNTHETIC"})
    period = node(
        "FiscalPeriod",
        {
            "calendar_id": str(calendar.resource_id),
            "starts_on": "2026-01-01",
            "ends_on": "2026-01-31",
        },
    )
    ledger = node(
        "Ledger",
        {
            "legal_entity_id": str(company.resource_id),
            "chart_id": str(chart.resource_id),
            "currency_id": str(currency.resource_id),
            "calendar_id": str(calendar.resource_id),
        },
    )
    book = node("AccountingBook", {"ledger_id": str(ledger.resource_id), "code": "SYNTHETIC"})
    publish(company, chart, currency, calendar, period, ledger, book)
    maker = reader.model_copy(
        update={"permissions": ("ontology_read", "ontology_propose", "ontology_review")}
    )
    checker = maker.model_copy(update={"actor_id": "synthetic-period-checker"})
    args = (company.resource_id, ledger.resource_id, book.resource_id, period.resource_id)
    initial = controls.read(reader, *args)
    assert initial["state"] == "UNESTABLISHED" and initial["control"] is None
    request = controls.ProposalRequest(
        selection=initial["selection"],
        request_id=uuid4(),
        expected_version_id=None,
        state="OPEN",
        reason="Explicit synthetic permission to test publication gate",
    )
    result = controls.propose(maker, request)
    assert result == controls.propose(maker, request)
    assert controls.read(reader, *args)["state"] == "UNESTABLISHED"
    with pytest.raises(WorkspaceError, match="different content"):
        controls.propose(
            maker, request.model_copy(update={"reason": "Changed request identity content"})
        )
    review = ResourceReview(
        decision="APPROVED", rationale="Independent synthetic current posting control review"
    )
    with pytest.raises(WorkspaceError):
        resources.review(maker, request.request_id, review)
    resources.review(checker, request.request_id, review)
    opened = controls.read(reader, *args)
    assert opened["state"] == "OPEN" and opened["current_use_authorized"] is False
    assert controls.propose(maker, request)["decision"] == "APPROVED"
    lock = controls.ProposalRequest(
        selection=opened["selection"],
        request_id=uuid4(),
        expected_version_id=opened["control"]["version_id"],
        state="LOCKED",
        reason="Explicit synthetic stop for new journal publication",
    )
    controls.propose(maker, lock)
    assert controls.read(reader, *args)["state"] == "OPEN"
    resources.review(checker, lock.request_id, review)
    locked = controls.read(reader, *args)
    assert locked["state"] == "LOCKED"
    stale = lock.model_copy(update={"request_id": uuid4(), "state": "OPEN"})
    with pytest.raises(WorkspaceError):
        controls.propose(maker, stale)
    reopen = lock.model_copy(
        update={
            "request_id": uuid4(),
            "expected_version_id": UUID(locked["control"]["version_id"]),
            "state": "OPEN",
            "reason": "Separate independent synthetic reopening reason",
        }
    )
    controls.propose(maker, reopen)
    resources.review(checker, reopen.request_id, review)
    assert controls.read(reader, *args)["state"] == "OPEN"
    # Historical proposal replay cannot change the newly reviewed current control.
    assert controls.propose(maker, lock)["decision"] == "APPROVED"
    assert controls.read(reader, *args)["state"] == "OPEN"
    current = controls.read(reader, *args)
    pending = reopen.model_copy(
        update={
            "request_id": uuid4(),
            "state": "LOCKED",
            "expected_version_id": UUID(current["control"]["version_id"]),
        }
    )
    controls.propose(maker, pending)
    retained_request = resources.proposal_detail(maker, pending.request_id).proposal
    assert len(next(iter(retained_request.source_versions.values()))) == 7
    calendar_row = resources.get_resource(reader, calendar.resource_id)["resource"]
    publish(
        calendar.model_copy(
            update={
                "expected_version_id": UUID(calendar_row["version_id"]),
                "display_name": "SYNTHETIC corrected calendar",
            }
        )
    )
    with pytest.raises(WorkspaceError):
        resources.review(checker, pending.request_id, review)
