import base64
import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from finai_api.api.diagnostic_routes import router as diagnostic_router
from finai_api.api.trial_balance_package_routes import router as trial_balance_package_router
from finai_api.domain.authority import ExactScope
from finai_api.domain.review import Principal
from finai_api.domain.trial_balance_package import TrialBalancePackageRequest
from finai_api.security import authenticated_principal
from finai_api.services import trial_balance_package as package_service
from finai_api.services.trial_balance_package import TrialBalancePackageError, build_package_report
from finai_api.services.xls_source import inspect_xls


MEASURES = (
    "opening_debit",
    "opening_credit",
    "turnover_debit",
    "turnover_credit",
    "closing_debit",
    "closing_credit",
)


def _source(month: int, opening: str, closing: str) -> tuple[str, bytes, dict, None]:
    values = {
        "source_account_code": "1000",
        "source_account_name": "Cash",
        "source_analytic_label": "",
        "source_row_role": "ACCOUNT_SUMMARY",
        "source_outline_level": "0",
        "hierarchy_parent_row": "",
        **dict.fromkeys(MEASURES, "0"),
    }
    values.update(
        {
            "opening_debit": opening,
            "opening_credit": opening,
            "closing_debit": closing,
            "closing_credit": closing,
            "turnover_debit": "10",
            "turnover_credit": "10",
        }
    )
    footer = {
        **dict.fromkeys(MEASURES, "0"),
        "opening_debit": opening,
        "opening_credit": opening,
        "closing_debit": closing,
        "closing_credit": closing,
        "turnover_debit": "10",
        "turnover_credit": "10",
        "source_account_code": "",
        "source_account_name": "",
        "source_analytic_label": "",
        "source_outline_level": "0",
        "hierarchy_parent_row": "",
    }
    source = {
        "period": f"2025-{month:02d}",
        "company_label": "SOCAR Georgia Petroleum",
        "sheet": "TDSheet",
        "rows": [
            {"source_row": 8, "values": values},
            {"source_row": 9, "values": footer},
        ],
    }
    return f"SGP {month}.xls", f"source-{month}".encode(), source, None


def test_package_report_is_month_bound_and_exposes_carryforward_breaks():
    sources = [_source(month, str(100 + month - 1), str(100 + month)) for month in range(1, 13)]
    report = build_package_report(
        sources,
        currency="GEL",
        active_runtime_period="2026-08",
        expected_row_count=24,
    )
    assert report.row_count == 24
    assert report.row_count_state == "PASS"
    assert report.package_evidence_state == "SOURCE_PROOF_PASSED"
    assert report.periods == tuple(f"2025-{month:02d}" for month in range(1, 13))
    assert report.carryforward[0].state == "NOT_APPLICABLE"
    assert report.carryforward[1].state == "PASS"
    assert report.carryforward_breaks == 0
    assert report.finance_locked is True
    assert report.mapping_state == "REQUIRED"
    assert report.historical_scope_guard["active_runtime_period"] == "2026-08"
    assert report.historical_scope_guard["evaluated_under_active_runtime_period"] is False


def test_package_report_detects_a_real_carryforward_break():
    sources = [_source(month, str(100 + month - 1), str(100 + month)) for month in range(1, 13)]
    filename, content, source, receipt = sources[4]
    source["rows"][0]["values"]["opening_debit"] = "999"
    source["rows"][0]["values"]["opening_credit"] = "999"
    report = build_package_report(
        sources,
        currency="GEL",
        active_runtime_period="2026-08",
        expected_row_count=24,
    )
    assert report.carryforward[4].state == "BREAK"
    assert report.carryforward_breaks == 1


def test_package_report_rejects_a_non_sgp_company_label():
    sources = [_source(month, str(100 + month - 1), str(100 + month)) for month in range(1, 13)]
    for _, _, source, _ in sources:
        source["company_label"] = "Unrelated Company"
    with pytest.raises(TrialBalancePackageError, match="SOCAR Petroleum"):
        build_package_report(sources, currency="GEL", active_runtime_period="2026-08", expected_row_count=24)


def test_package_report_rejects_a_month_without_a_source_total_footer():
    sources = [_source(month, str(100 + month - 1), str(100 + month)) for month in range(1, 13)]
    sources[0][2]["rows"][1]["values"]["source_account_name"] = "Total"

    report = build_package_report(
        sources,
        currency="GEL",
        active_runtime_period="2026-08",
        expected_row_count=24,
    )

    assert report.months[0].equality_state == "BREAK"
    assert report.package_evidence_state == "SOURCE_REVIEW_REQUIRED"


def test_package_request_requires_the_exact_twelve_source_names():
    payload = [
        {"filename": f"SGP {month}.xls", "xls_base64": base64.b64encode(b"x").decode()}
        for month in range(1, 13)
    ]
    request = TrialBalancePackageRequest(files=tuple(payload))
    assert len(request.files) == 12
    with pytest.raises(ValueError):
        TrialBalancePackageRequest(
            files=tuple(payload[:-1] + [{"filename": "SGP 13.xls", "xls_base64": "eA=="}])
        )


def test_package_route_uses_authenticated_principal_dependency():
    app = FastAPI()
    app.include_router(trial_balance_package_router)

    operation = app.openapi()["paths"]["/v1/hydration/trial-balance-package"]["post"]
    body_schema = operation["requestBody"]["content"]["application/json"]["schema"]

    assert body_schema["$ref"] == "#/components/schemas/TrialBalancePackageRequest"
    assert operation["security"] == [{"HTTPBearer": []}]


def test_package_diagnostics_route_is_bearer_protected_and_registered():
    app = FastAPI()
    app.include_router(trial_balance_package_router)

    operation = app.openapi()["paths"]["/v1/hydration/trial-balance-package/diagnostics"]["post"]
    body_schema = operation["requestBody"]["content"]["application/json"]["schema"]

    assert body_schema["$ref"] == "#/components/schemas/TrialBalancePackageDiagnosticsRequest"
    assert operation["security"] == [{"HTTPBearer": []}]


def test_package_diagnostics_keeps_2025_periods_separate_from_active_runtime_scope():
    scope = ExactScope(
        tenant_id=uuid4(),
        legal_entity_id="socar-georgia-petroleum",
        period="2026-08",
        currency="GEL",
    )
    sources = [_source(month, str(100 + month - 1), str(100 + month)) for month in range(1, 13)]
    report = build_package_report(
        sources,
        currency=scope.currency,
        active_runtime_period=scope.period,
        expected_row_count=24,
        tenant_id=str(scope.tenant_id),
        legal_entity_id=scope.legal_entity_id,
    )

    diagnostics = package_service.diagnose_package(report, scope)

    assert diagnostics.source_periods == tuple(f"2025-{month:02d}" for month in range(1, 13))
    assert diagnostics.active_runtime_period == "2026-08"
    assert diagnostics.evaluated_under_active_runtime_period is False
    assert diagnostics.historical_scope_state == "ISOLATED"
    assert diagnostics.mapping_state == "REQUIRED"
    assert diagnostics.finance_locked is True
    assert diagnostics.overall_state == "REVIEW_REQUIRED"
    assert report.tenant_id == scope.tenant_id
    assert report.legal_entity_id == scope.legal_entity_id

    other_report = build_package_report(
        sources,
        currency=scope.currency,
        active_runtime_period=scope.period,
        expected_row_count=24,
        tenant_id=str(uuid4()),
        legal_entity_id=scope.legal_entity_id,
    )
    assert other_report.package_id != report.package_id


def test_package_diagnostics_refuses_a_different_tenant_or_entity():
    scope = ExactScope(
        tenant_id=uuid4(),
        legal_entity_id="socar-georgia-petroleum",
        period="2026-08",
        currency="GEL",
    )
    sources = [_source(month, str(100 + month - 1), str(100 + month)) for month in range(1, 13)]
    report = build_package_report(
        sources,
        currency=scope.currency,
        active_runtime_period=scope.period,
        expected_row_count=24,
        tenant_id=str(uuid4()),
        legal_entity_id=scope.legal_entity_id,
    )

    with pytest.raises(package_service.TrialBalancePackageError, match="authenticated tenant"):
        package_service.diagnose_package(report, scope)


def test_package_diagnostics_blocks_a_runtime_evaluation_claim():
    scope = ExactScope(
        tenant_id=uuid4(),
        legal_entity_id="socar-georgia-petroleum",
        period="2026-08",
        currency="GEL",
    )
    sources = [_source(month, str(100 + month - 1), str(100 + month)) for month in range(1, 13)]
    report = build_package_report(
        sources,
        currency=scope.currency,
        active_runtime_period=scope.period,
        expected_row_count=24,
        tenant_id=str(scope.tenant_id),
        legal_entity_id=scope.legal_entity_id,
    ).model_copy(
        update={
            "historical_scope_guard": {
                "source_year": "2025",
                "active_runtime_period": "2026-08",
                "evaluated_under_active_runtime_period": True,
                "period_binding": "ACTIVE_RUNTIME_PERIOD",
            }
        }
    )

    diagnostics = package_service.diagnose_package(report, scope)

    assert diagnostics.evaluated_under_active_runtime_period is True
    assert diagnostics.historical_scope_state == "REVIEW_REQUIRED"
    assert diagnostics.overall_state == "BLOCKED"


def test_package_diagnostics_http_route_returns_read_only_scope_context():
    scope = ExactScope(
        tenant_id=uuid4(),
        legal_entity_id="socar-georgia-petroleum",
        period="2026-08",
        currency="GEL",
    )
    principal = Principal(
        actor_id="diagnostic-reader",
        display_name="Diagnostic reader",
        scope=scope,
        permissions=("read",),
    )
    sources = [_source(month, str(100 + month - 1), str(100 + month)) for month in range(1, 13)]
    report = build_package_report(
        sources,
        currency=scope.currency,
        active_runtime_period=scope.period,
        expected_row_count=24,
        tenant_id=str(scope.tenant_id),
        legal_entity_id=scope.legal_entity_id,
    )
    app = FastAPI()
    app.include_router(trial_balance_package_router)
    app.dependency_overrides[authenticated_principal] = lambda: principal

    response = TestClient(app).post(
        "/v1/hydration/trial-balance-package/diagnostics",
        json={"report": report.model_dump(mode="json")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_periods"] == [f"2025-{month:02d}" for month in range(1, 13)]
    assert body["active_runtime_period"] == "2026-08"
    assert body["evaluated_under_active_runtime_period"] is False
    assert body["finance_locked"] is True
    app.dependency_overrides.clear()


def test_diagnostic_routes_are_registered_with_authenticated_context():
    app = FastAPI()
    app.include_router(diagnostic_router)
    schema = app.openapi()["paths"]
    assert "/v1/diagnostics/readiness" in schema
    assert "/v1/diagnostics/evidence-context" in schema
    assert schema["/v1/diagnostics/evidence-context"]["get"]["security"] == [{"HTTPBearer": []}]


def test_compile_package_binds_each_receipt_to_observed_2025_period(monkeypatch):
    sources_by_content = {}
    payload = []
    for month in range(1, 13):
        filename, _, source, _ = _source(month, str(100 + month - 1), str(100 + month))
        content = bytes.fromhex("d0cf11e0a1b11ae1") + f"source-{month}".encode()
        sources_by_content[content] = source
        payload.append(
            {
                "filename": filename,
                "xls_base64": base64.b64encode(content).decode(),
            }
        )

    class Receipt:
        def __init__(self, receipt_id: str):
            self.receipt_id = receipt_id

    compiled_scopes: list[str] = []
    retained_scopes: list[str] = []
    monkeypatch.setattr(
        package_service,
        "inspect_xls",
        lambda content: sources_by_content[content],
    )

    def fake_compile(request):
        compiled_scopes.append(request.scope.period)
        return Receipt(f"receipt-{request.scope.period}")

    monkeypatch.setattr(package_service, "compile_source", fake_compile)
    from finai_api import storage

    def fake_retain(request, receipt, actor_id):
        retained_scopes.append(request.scope.period)
        return receipt

    monkeypatch.setattr(storage, "retain", fake_retain)
    principal = Principal(
        actor_id="historical-intake",
        display_name="Historical intake",
        scope=ExactScope(
            tenant_id=uuid4(),
            legal_entity_id="socar-georgia-petroleum",
            period="2026-08",
            currency="GEL",
        ),
        permissions=("ingest",),
    )

    report = package_service.compile_package(
        principal,
        TrialBalancePackageRequest(files=tuple(payload)),
    )

    expected_periods = [f"2025-{month:02d}" for month in range(1, 13)]
    assert compiled_scopes == expected_periods
    assert retained_scopes == expected_periods
    assert [month.period for month in report.months] == expected_periods
    assert all(period != principal.scope.period for period in compiled_scopes)


@pytest.mark.skipif(
    not os.environ.get("FINAI_PETROLEUM_FIXTURES"),
    reason="private SGP fixture directory is not configured",
)
def test_authentic_sgp_package_has_38137_rows_and_zero_monthly_equality_residuals():
    folder = Path(os.environ["FINAI_PETROLEUM_FIXTURES"])
    sources = []
    for month in range(1, 13):
        content = (folder / f"SGP {month}.xls").read_bytes()
        sources.append((f"SGP {month}.xls", content, inspect_xls(content), None))
    report = build_package_report(
        sources,
        currency="GEL",
        active_runtime_period="2026-08",
    )
    assert report.row_count == 38137
    assert all(month.equality_state == "PASS" for month in report.months)
