"""Synthetic proposal checks; these do not approve authentic source accounting meaning."""

from types import SimpleNamespace
from uuid import uuid4, uuid5

import pytest
from pydantic import ValidationError

from finai_api.services import seg_chart_binding as chart
from finai_api.services.workspace import WorkspaceError


def fixture(monkeypatch):
    company, definition, version = uuid4(), uuid4(), uuid4()
    principal = SimpleNamespace(scope=SimpleNamespace(tenant_id=uuid4(), legal_entity_id="test"))
    choice = chart.ChartSelection(
        source_sha256="a" * 64,
        rationale="Explicit synthetic selection",
        accounts=[
            {
                "code": "0012.01",
                "definition_id": definition,
                "definition_version_id": version,
            }
        ],
    )
    monkeypatch.setattr(chart, "require_permission", lambda *_: None)
    monkeypatch.setattr(
        chart.seg_account_observations,
        "inspect",
        lambda *_: {
            "source_sha256": "a" * 64,
            "rows": [
                {
                    "code": "0012.01",
                    "coordinates": [{"coordinate": "Base!E2"}],
                    "definitions": [
                        {
                            "resource_id": str(definition),
                            "version_id": str(version),
                            "display_name": "Definition",
                        }
                    ],
                }
            ],
        },
    )
    monkeypatch.setattr(
        chart.source_company_alias,
        "inspect",
        lambda *_: {
            "accepted": True,
            "source_sha256": "a" * 64,
            "company": {"version_id": str(uuid4()), "display_name": "Synthetic company"},
        },
    )

    def missing(*_):
        raise WorkspaceError(404, "not found")

    monkeypatch.setattr(chart.resources, "get_resource", missing)
    monkeypatch.setattr(chart.resources, "propose", lambda _principal, proposal: proposal)
    return principal, company, choice


def test_exact_code_canonical_identity_and_definition_pin(monkeypatch):
    principal, company, choice = fixture(monkeypatch)
    result = chart.propose(principal, "synthetic", "Base", "seg_expense_base", company, choice)
    account = next(item for item in result.mutations if item.object_type == "LocalAccount")
    assert account.resource_id == uuid5(uuid5(company, "1c-observed-chart"), "0012.01")
    assert account.attributes["account_code"] == "0012.01"
    assert result.source_versions[account.resource_id] == {
        choice.accounts[0].definition_id: choice.accounts[0].definition_version_id,
    }
    assert {item.object_type for item in result.mutations} == {
        "LocalAccount",
        "LocalChartOfAccounts",
        "SourceRecord",
        "Relationship",
    }
    assert "does not establish" in result.rationale


@pytest.mark.parametrize("change", ["hash", "code", "version", "company"])
def test_changed_or_unreviewed_input_refused(monkeypatch, change):
    principal, company, choice = fixture(monkeypatch)
    if change == "hash":
        choice.source_sha256 = "b" * 64
    elif change == "code":
        choice.accounts[0].code = "12.01"
    elif change == "version":
        choice.accounts[0].definition_version_id = uuid4()
    else:
        monkeypatch.setattr(chart.source_company_alias, "inspect", lambda *_: {"accepted": False})
    with pytest.raises(WorkspaceError) as error:
        chart.propose(principal, "synthetic", "Base", "seg_expense_base", company, choice)
    assert error.value.status == 409


def test_duplicate_selection_refused(monkeypatch):
    _, _, choice = fixture(monkeypatch)
    with pytest.raises(ValidationError):
        chart.ChartSelection(**{**choice.model_dump(), "accounts": choice.accounts * 2})
