# ruff: noqa: F811
"""Native bundle query and source-binding refusal, not successful journal acceptance."""

import pytest
from test_definition_history import DB, item, retained  # noqa: F401
from test_journal_balance import bundle

from finai_api.domain.resources import ResourceProposal
from finai_api.services import resources
from finai_api.services.journal_balance import validate_bundle
from finai_api.services.workspace import WorkspaceError


@DB
def test_native_bundle_query_and_no_partial_journal_without_binding(retained):
    reader, _publish = retained
    with resources.resource_connection(reader) as conn:
        assert validate_bundle(conn, reader, bundle())[0]["status"] == "BALANCED"
    company = item("LegalEntity", {})
    chart = item(
        "LocalChartOfAccounts", {"legal_entity_id": str(company.resource_id), "code": "TEST"}
    )
    calendar = item("FiscalCalendar", {"code": "TEST"})
    currency = item("Currency", {"code": "GEL"})
    ledger = item(
        "Ledger",
        {
            "legal_entity_id": str(company.resource_id),
            "chart_id": str(chart.resource_id),
            "calendar_id": str(calendar.resource_id),
            "currency_id": str(currency.resource_id),
        },
    )
    period = item(
        "FiscalPeriod",
        {
            "calendar_id": str(calendar.resource_id),
            "starts_on": "2026-01-01",
            "ends_on": "2026-01-31",
        },
    )
    proposal_bundle = bundle()
    entry = proposal_bundle.mutations[0]
    attrs = {
        "legal_entity_id": str(company.resource_id),
        "ledger_id": str(ledger.resource_id),
        "period_id": str(period.resource_id),
        "reference": "SYNTHETIC no binding",
        "definition": entry.attributes["definition"],
    }
    entry = entry.model_copy(update={"attributes": attrs})
    proposal = ResourceProposal(
        title="Reject synthetic journal without binding",
        rationale="No accounting source authority is fabricated for balance testing",
        access_entity=reader.scope.legal_entity_id,
        mutations=[company, chart, calendar, currency, ledger, period, entry],
    )
    proposer = reader.model_copy(update={"permissions": (*reader.permissions, "ontology_propose")})
    with pytest.raises(WorkspaceError, match="accepted source accounting binding"):
        resources.propose(proposer, proposal)
    with resources.resource_connection(reader) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM resource_versions WHERE tenant_id=%s "
                "AND resource_id=ANY(%s::uuid[])",
                (reader.scope.tenant_id, [m.resource_id for m in proposal.mutations]),
            ).fetchone()[0]
            == 0
        )
