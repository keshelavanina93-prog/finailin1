"""Synthetic canonical setup review; source parsing is separately integrated."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4, uuid5

import pytest
from pydantic import ValidationError
from test_definition_history import DB, item, retained  # noqa: F401

from finai_api.domain.resources import ResourceProposal, ResourceReview
from finai_api.services import resources
from finai_api.services import source_accounting_setup as setup
from finai_api.services.workspace import WorkspaceError


def selection(**changes):
    return setup.SetupSelection.model_validate(
        {
            "request_id": str(uuid4()),
            "ledger_code": "LOCAL",
            "ledger_name": "SYNTHETIC ledger",
            "book_code": "MAIN",
            "book_name": "SYNTHETIC book",
            "currency_id": str(uuid4()),
            "calendar": {"code": "ANNUAL", "name": "SYNTHETIC calendar"},
            "period": {
                "name": "SYNTHETIC November",
                "starts_on": "2025-11-01",
                "ends_on": "2025-11-30",
            },
            "rationale": "Explicit synthetic accounting structure acceptance",
            **changes,
        }
    )


def test_legacy_proposal_and_strict_setup_choices():
    proposal = ResourceProposal(
        title="Legacy proposal",
        rationale="Legacy serialization acceptance",
        access_entity="synthetic",
        mutations=[item("LegalEntity", {})],
    )
    assert "request_binding" not in proposal.model_dump(mode="json")
    for period in [
        {"name": "Period", "starts_on": "2025-11-30", "ends_on": "2025-11-01"},
        {"name": "Period", "starts_on": True, "ends_on": "2025-11-30"},
        {"name": "Period", "starts_on": "2025-11-01T00:00:00", "ends_on": "2025-11-30"},
    ]:
        with pytest.raises(ValidationError):
            selection(period=period)
    with pytest.raises(ValidationError):
        selection(currency_code="GEL")
    with pytest.raises(ValidationError):
        selection(currency_id=None)
    assert selection(currency_id=None, currency_code="GEL").currency_code == "GEL"


@DB
def test_canonical_setup_review_replay_and_context_refusals(retained, monkeypatch):  # noqa: F811
    reader, publish = retained
    maker = reader.model_copy(
        update={"permissions": ("ontology_read", "ontology_propose", "ontology_review")}
    )
    checker = maker.model_copy(update={"actor_id": "synthetic-accounting-setup-checker"})

    def asserted(kind, attributes, **changes):
        return item(kind, attributes, **changes).model_copy(
            update={"evidence_class": "USER_ASSERTED"}
        )

    company = asserted("LegalEntity", {})
    chart = asserted(
        "LocalChartOfAccounts",
        {"code": "SYNTHETIC", "legal_entity_id": str(company.resource_id)},
        resource_id=uuid5(company.resource_id, "1c-observed-chart"),
    )
    evidence = asserted("SourceEvidence", {"sha256": "a" * 64, "source_system": "SYNTHETIC_SETUP"})
    currency = asserted("Currency", {"code": "GEL"})
    publish(company, chart, evidence, currency)
    context = {
        "canonical_ready": True,
        "observed": {
            "chart_id": str(chart.resource_id),
            "evidence_id": str(evidence.resource_id),
            "observed_from": "2025-11-03",
            "observed_through": "2025-11-28",
        },
    }
    monkeypatch.setattr(setup.source_accounting_context, "inspect", lambda *_: deepcopy(context))
    request = selection(currency_id=str(currency.resource_id))
    args = (maker, "doc_synthetic", "Source", "1c_journal", company.resource_id)
    result = setup.propose(*args, request)
    assert result["review_required"] and result["decision"] is None
    assert {row["object_type"] for row in result["created"]} == {
        "Ledger",
        "AccountingBook",
        "FiscalCalendar",
        "FiscalPeriod",
    }
    assert not resources.current_resources(reader, [UUID(result["planned"]["ledger_id"])])
    assert setup.propose(*args, request) == result
    with pytest.raises(WorkspaceError, match="different content"):
        setup.propose(*args, request.model_copy(update={"ledger_name": "Changed name"}))
    review = ResourceReview(
        decision="APPROVED", rationale="Independent synthetic accounting setup acceptance"
    )
    with pytest.raises(WorkspaceError):
        resources.review(maker, request.request_id, review)
    resources.review(checker, request.request_id, review)
    context["canonical_ready"] = False
    replay = setup.propose(*args, request)
    assert replay["decision"] == "APPROVED" and not replay["review_required"]
    assert replay["planned"] == result["planned"]
    context["canonical_ready"] = True
    with pytest.raises(WorkspaceError, match="extent"):
        setup.propose(
            *args,
            selection(
                currency_id=str(currency.resource_id),
                ledger_code="OTHER",
                calendar={"code": "OTHER", "name": "Other"},
                period={"name": "Short", "starts_on": "2025-11-04", "ends_on": "2025-11-30"},
            ),
        )
    other_company = asserted("LegalEntity", {})
    publish(other_company)
    with pytest.raises(WorkspaceError, match="another company"):
        setup.propose(
            maker,
            "doc_synthetic",
            "Source",
            "1c_journal",
            other_company.resource_id,
            selection(currency_id=str(currency.resource_id)),
        )
    other_calendar = asserted("FiscalCalendar", {"code": "OTHER"})
    other_period = asserted(
        "FiscalPeriod",
        {
            "calendar_id": str(other_calendar.resource_id),
            "starts_on": "2025-11-01",
            "ends_on": "2025-11-30",
        },
    )
    publish(other_calendar, other_period)
    with pytest.raises(WorkspaceError, match="another calendar"):
        setup.propose(
            *args,
            selection(
                currency_id=str(currency.resource_id),
                calendar={"resource_id": result["planned"]["calendar_id"]},
                period={"resource_id": str(other_period.resource_id)},
            ),
        )

    # New currency is an explicit proposed reference, never inferred from source amounts.
    code = "".join(chr(65 + value % 26) for value in uuid4().bytes[:3])
    currency_request = selection(
        currency_id=None,
        currency_code=code,
        ledger_code="EXPLICIT",
        calendar={"resource_id": result["planned"]["calendar_id"]},
        period={"resource_id": result["planned"]["period_id"]},
    )
    currency_result = setup.propose(*args, currency_request)
    assert "Currency" in {row["object_type"] for row in currency_result["created"]}
    # A correction after submission invalidates exact context pins during promotion.
    current = resources.get_resource(reader, company.resource_id)["resource"]
    publish(
        company.model_copy(
            update={
                "expected_version_id": UUID(current["version_id"]),
                "display_name": "SYNTHETIC corrected company",
            }
        )
    )
    with pytest.raises(WorkspaceError):
        resources.review(checker, currency_request.request_id, review)
    # Scheduled editing heads cannot be silently overwritten/reused as current setup inputs.
    current = resources.get_resource(reader, currency.resource_id)["resource"]
    publish(
        currency.model_copy(
            update={
                "expected_version_id": UUID(current["version_id"]),
                "valid_from": datetime.now(UTC) + timedelta(days=2),
            }
        )
    )
    with pytest.raises(WorkspaceError, match="scheduled"):
        setup.propose(*args, selection(currency_id=str(currency.resource_id), ledger_code="FUTURE"))
