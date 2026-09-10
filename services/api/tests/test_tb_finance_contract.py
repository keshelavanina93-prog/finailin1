import json

import pytest
from fastapi.testclient import TestClient

from finai_api.config import get_settings
from finai_api.services import tb_finance_contract
from finai_api.services.workspace import WorkspaceError


def valid_request(**changes):
    value = {
        "contract_id": tb_finance_contract.CONTRACT_ID,
        "profile": tb_finance_contract.PROFILE,
        "input_grain": tb_finance_contract.INPUT_GRAIN,
        "source_class": tb_finance_contract.SOURCE_CLASS,
        "source_family": tb_finance_contract.SOURCE_FAMILY,
        "requested_objects": ["AccountPeriodFact"],
        "requested_outputs": ["StatementDraft"],
        "currency_status": "UNREVIEWED",
    }
    value.update(changes)
    return value


def test_contract_description_is_generic_and_non_authoritative():
    result = tb_finance_contract.contract_definition()

    assert result["contract_id"] == "1c_turnover_trial_balance@v1"
    assert result["profile"] == "account_period_tb_finance"
    assert result["input_grain"] == "ACCOUNT_PERIOD"
    assert result["canonical_journal_created"] is False
    assert result["business_effect_authorized"] is False
    assert "journal entry" in result["forbidden_capabilities"]
    assert "liters" in result["forbidden_capabilities"]


def test_account_period_draft_input_is_accepted_without_mutation():
    result = tb_finance_contract.validate_input(valid_request())

    assert result["accepted"] is True
    assert result["authority_state"] == "DRAFT_INPUT"
    assert result["amount_unit"] == "source_amount"
    assert result["canonical_journal_created"] is False
    assert result["accounting_use_authorized"] is False
    assert result["business_effect_authorized"] is False


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("requested_objects", ["JournalEntry"], "journal entry"),
        ("requested_objects", ["JournalLine"], "journal line"),
        ("requested_objects", ["Invoice"], "invoice"),
        ("requested_outputs", ["ReceivablesAging"], "receivables aging"),
        ("requested_outputs", ["Liters"], "liters"),
        ("requested_outputs", ["TankDipFact"], "tank-dip fact"),
        ("requested_outputs", ["TruckDispatchFact"], "truck dispatch fact"),
        ("requested_outputs", ["ProductMargin"], "product margin"),
        ("requested_outputs", ["CashFlowStatement"], "cash-flow statement"),
    ],
)
def test_trial_balance_cannot_be_reinterpreted_as_other_source_families(
    field, value, expected
):
    with pytest.raises(WorkspaceError, match=expected):
        tb_finance_contract.validate(valid_request(**{field: value}))


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({"profile": "seg_expense_base"}, "account_period_tb_finance"),
        ({"input_grain": "JOURNAL_LINE"}, "ACCOUNT_PERIOD"),
        ({"source_class": "1C_JOURNAL"}, "1C_TURNOVER_TRIAL_BALANCE"),
        ({"source_family": "REVIEWED_GL"}, "1C_ACCOUNT_PERIOD"),
        ({"currency_status": "GEL"}, "source_amount"),
        ({"requested_objects": ["UnknownFact"]}, "account-period inputs"),
        ({"requested_outputs": ["CertifiedStatement"]}, "account-period draft outputs"),
    ],
)
def test_only_account_period_tb_finance_inputs_are_accepted(changes, expected):
    with pytest.raises(WorkspaceError, match=expected):
        tb_finance_contract.validate(valid_request(**changes))


def test_contract_http_endpoint_returns_guarded_decision(monkeypatch):
    from finai_api.main import app

    monkeypatch.setenv(
        "FINAI_ACCESS_TOKENS",
        json.dumps(
            {
                "test-token": {
                    "actor_id": "tb-contract-reader",
                    "display_name": "TB contract reader",
                    "scope": {
                        "tenant_id": "805d8a32-d12b-4268-a236-b0b16e59da9f",
                        "legal_entity_id": "entity-ge-001",
                        "period": "2026-08",
                        "currency": "GEL",
                    },
                    "permissions": ["read", "ontology_read"],
                }
            }
        ),
    )
    get_settings.cache_clear()
    client = TestClient(app, headers={"Authorization": "Bearer test-token"})

    descriptor = client.get("/v1/ontology/finance/contracts/1c_turnover_trial_balance")
    assert descriptor.status_code == 200
    assert descriptor.json()["profile"] == "account_period_tb_finance"

    accepted = client.post(
        "/v1/ontology/finance/contracts/1c_turnover_trial_balance/validate",
        json=valid_request(),
    )
    assert accepted.status_code == 200
    assert accepted.json()["accepted"] is True

    denied = client.post(
        "/v1/ontology/finance/contracts/1c_turnover_trial_balance/validate",
        json=valid_request(requested_objects=["JournalEntry"]),
    )
    assert denied.status_code == 422
    assert "journal entry" in denied.json()["detail"]


def test_contract_http_endpoint_requires_ontology_read():
    from finai_api.main import app

    client = TestClient(app, headers={"Authorization": "Bearer test-token"})
    # The test fixture's bootstrap token has no ontology_read permission.
    assert client.get("/v1/ontology/finance/contracts/1c_turnover_trial_balance").status_code == 403
    no_auth = TestClient(app).get("/v1/ontology/finance/contracts/1c_turnover_trial_balance")
    assert no_auth.status_code == 401
