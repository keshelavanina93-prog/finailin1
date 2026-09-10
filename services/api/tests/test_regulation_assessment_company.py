"""Pasted retained scenarios cannot cross the product's selected company boundary."""

from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from finai_api.api import regulation_routes as routes
from finai_api.domain.review import Principal
from finai_api.main import app
from finai_api.security import authenticated_principal
from finai_api.services.workspace import WorkspaceError


@pytest.fixture
def case(monkeypatch):
    company_id = uuid4()
    principal = Principal(
        actor_id="retained-scenario-reader",
        display_name="Synthetic reader",
        scope={
            "tenant_id": uuid4(),
            "legal_entity_id": "scope",
            "period": "2026-09",
            "currency": "GEL",
        },
        permissions=("ontology_read",),
    )
    result = {
        "contract": "regulatory-assessment/1",
        "run_id": "fcr_" + "a" * 64,
        "company": {
            "resource_id": str(company_id),
            "version_id": str(uuid4()),
            "display_name": "Retained company",
        },
        "at": "2025-01-31T23:01:02.123456+04:00",
        "known_at": "2025-02-10T23:01:02.654321+04:00",
        "assessment_context": {
            "legal_entity_id": str(company_id),
            "activity": "SUPPLY",
            "customer_count": None,
            "at": "2025-01-31T23:01:02.123456+04:00",
            "known_at": "2025-02-10T23:01:02.654321+04:00",
        },
        "rules": [],
        "coverage": "COMPLETE_AUTHORIZED_RULE_SCAN",
        "next_offset": None,
        "no_rules_found": True,
        "context_basis": "USER_SUPPLIED_SCENARIO",
        "accounting_effects_created": False,
    }
    reader = Mock(return_value=result)
    monkeypatch.setattr(routes, "read_run", reader)
    monkeypatch.setattr(
        routes, "retain_run", Mock(side_effect=AssertionError("A read must not retain another run"))
    )
    monkeypatch.setattr(
        routes,
        "_company_at",
        Mock(side_effect=AssertionError("No current or replacement company resolution")),
    )
    return principal, company_id, result, reader


def test_selected_company_preserves_original_scenario_exactly(case):
    principal, company_id, result, reader = case
    before = deepcopy(result)
    value = routes.read_assessment(principal, result["run_id"], company_id)
    assert value is result and value == before
    assert value["accounting_effects_created"] is False
    assert datetime.fromisoformat(value["at"]).microsecond == 123456
    assert datetime.fromisoformat(value["known_at"]).microsecond == 654321
    reader.assert_called_once_with(principal, result["run_id"])


@pytest.mark.parametrize(
    "changed",
    [
        "company",
        "context",
        "both",
        "missing_company",
        "missing_context",
        "malformed_company",
        "malformed_context",
    ],
)
def test_foreign_or_malformed_selected_company_refuses_without_metadata(case, changed):
    principal, company_id, result, _ = case
    foreign = str(uuid4())
    if changed in {"company", "both"}:
        result["company"]["resource_id"] = foreign
    if changed in {"context", "both"}:
        result["assessment_context"]["legal_entity_id"] = foreign
    if changed.startswith("missing"):
        result.pop("company" if changed == "missing_company" else "assessment_context")
    if changed.startswith("malformed"):
        result["company" if changed == "malformed_company" else "assessment_context"] = [foreign]
    with pytest.raises(WorkspaceError) as refusal:
        routes.read_assessment(principal, result["run_id"], company_id)
    assert refusal.value.status == 404
    assert refusal.value.detail == "Regulatory assessment unavailable"
    assert foreign not in refusal.value.detail and result["run_id"] not in refusal.value.detail


def test_legacy_unscoped_history_read_remains_compatible(case):
    principal, _, result, reader = case
    assert routes.read_assessment(principal, result["run_id"]) is result
    reader.assert_called_once()


@pytest.mark.parametrize("status", [404, 409])
def test_existing_exact_scope_permission_or_integrity_refusal_is_not_bypassed(case, status):
    principal, company_id, result, reader = case
    reader.side_effect = WorkspaceError(status, "Existing retained proof refused")
    with pytest.raises(WorkspaceError) as refusal:
        routes.read_assessment(principal, result["run_id"], company_id)
    assert refusal.value.status == status


def test_scoped_http_query_refuses_foreign_and_invalid_ids(case, monkeypatch):
    from finai_api import security

    principal, company_id, result, reader = case
    monkeypatch.setattr(
        security, "get_settings", lambda: SimpleNamespace(access_tokens=SecretStr('{"test": {}}'))
    )
    client = TestClient(app)
    path = "/v1/ontology/regulation/assessments/" + result["run_id"]
    assert client.get(path, params={"legal_entity_id": str(company_id)}).status_code == 401
    reader.assert_not_called()
    app.dependency_overrides[authenticated_principal] = lambda: principal
    try:
        response = client.get(path, params={"legal_entity_id": str(uuid4())})
        assert response.status_code == 404 and response.json() == {
            "detail": "Regulatory assessment unavailable"
        }
        reader.reset_mock()
        assert client.get(path, params={"legal_entity_id": "invalid"}).status_code == 422
        reader.assert_not_called()
        response = client.get(path, params={"legal_entity_id": str(company_id)})
        assert response.status_code == 200 and response.json() == result
    finally:
        app.dependency_overrides.clear()
