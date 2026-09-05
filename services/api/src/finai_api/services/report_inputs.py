"""Source-package coverage preflight; never certifies or calculates financial outputs."""

import json
from hashlib import sha256
from typing import Any

from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from finai_api.domain.ingest import IngestReceipt
from finai_api.domain.review import Principal
from finai_api.services.workspace import WorkspaceError
from finai_api.storage import connection

# Versioned input requirements, not financial metric implementations.
REQUIREMENTS = {
    "Mapped account P&L and balance sheet": {"TRIAL_BALANCE", "GL_OR_JOURNAL"},
    "Product net revenue": {"PRODUCT_REVENUE"},
    "Product COGS": {"ACCOUNT_ANALYTIC_TURNOVER", "INVENTORY_MOVEMENT"},
    "Expense department and counterparty drill": {"GL_OR_JOURNAL"},
    "Budget comparison": {"APPROVED_BUDGET"},
    "Currency translation": {"APPROVED_FX_RATE_SET"},
    "Cash flow and non-cash adjustments": {"CASH_FLOW_FACTS"},
    "Receivables/payables aging": {"SUBLEDGER_AGING"},
    "Physical volumes and losses": {"PHYSICAL_MOVEMENT"},
    "HR and HSE indicators": {"OPERATIONAL_KPI"},
}


class ReportInputRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    company_label: str = Field(min_length=1, max_length=256)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    receipt_ids: tuple[str, ...] = Field(min_length=1, max_length=100)


def assess(request: ReportInputRequest, receipts: list[IngestReceipt]) -> dict[str, Any]:
    inputs = []
    for receipt in receipts:
        profile = receipt.source_profile
        use = profile.get("source_use", "ACTUAL_INPUT")
        sheets = profile.get("sheets", [])
        if receipt.source_class == "TRIAL_BALANCE":
            sheets = [
                {
                    "sheet": "TB",
                    "source_type": "TRIAL_BALANCE",
                    "periods": [profile.get("observed_period")],
                    "company_labels": [profile.get("observed_company_label")],
                }
            ]
        for sheet in sheets:
            reasons = []
            if use != "ACTUAL_INPUT":
                reasons.append("REFERENCE_ONLY")
            if request.period not in sheet.get("periods", []):
                reasons.append("PERIOD_MISMATCH_OR_UNESTABLISHED")
            if request.company_label not in sheet.get("company_labels", []):
                reasons.append("COMPANY_MISMATCH_OR_UNBOUND")
            if sheet.get("functional_currency") != request.currency:
                reasons.append("CURRENCY_UNBOUND")
            if receipt.binding_state != "CANONICAL_BOUND":
                reasons.append("NO_CANONICAL_FINANCIAL_AUTHORITY")
            inputs.append(
                {
                    "receipt_id": receipt.receipt_id,
                    "source_sha256": receipt.source_sha256,
                    "sheet": sheet["sheet"],
                    "source_type": sheet["source_type"],
                    "source_use": use,
                    "excluded_reasons": reasons,
                    "observed_periods": sheet.get("periods", []),
                    "observed_companies": sheet.get("company_labels", []),
                }
            )
    lines = []
    for line, types in REQUIREMENTS.items():
        matches = [item for item in inputs if item["source_type"] in types]
        lines.append(
            {
                "line": line,
                "required_source_types": sorted(types),
                "state": "UNAVAILABLE",
                "source_candidates": matches,
                "reason": "MISSING_SOURCE_CLASS"
                if not matches
                else "REVIEW_AND_CANONICAL_FACTS_REQUIRED",
            }
        )
    return {
        "contract_version": "mr-source-coverage/1",
        "target": request.model_dump(mode="json"),
        "inputs": inputs,
        "lines": lines,
        "state": "UNAVAILABLE",
        "explanation": (
            "This is source coverage preflight. Retained source observations are not "
            "approved metric inputs. No report amounts were calculated."
        ),
        "source_version_set": [r.source_sha256 for r in receipts],
    }


def retain_assessment(principal: Principal, request: ReportInputRequest) -> dict[str, Any]:
    with connection(principal.scope) as conn:
        scope = principal.scope.model_dump(mode="json")
        conn.execute("SELECT set_config('finai.exact_scope',%s,true)", (json.dumps(scope),))
        receipts = []
        for receipt_id in sorted(set(request.receipt_ids)):
            row = conn.execute(
                "SELECT receipt FROM hydration_runs WHERE tenant_id=%s AND "
                "exact_scope=%s AND receipt_id=%s",
                (principal.scope.tenant_id, Jsonb(scope), receipt_id),
            ).fetchone()
            if not row:
                raise WorkspaceError(404, "Source receipt unavailable in authorized scope")
            receipts.append(IngestReceipt.model_validate(row[0]))
        result = assess(request, receipts)
        result["scope"] = scope
        identity = "rca_" + sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
        result["assessment_id"] = identity
        conn.execute(
            "INSERT INTO report_source_assessments "
            "(tenant_id,assessment_id,exact_scope,payload,actor_id) "
            "VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (principal.scope.tenant_id, identity, Jsonb(scope), Jsonb(result), principal.actor_id),
        )
        return result


def assessments(principal: Principal) -> list[dict[str, Any]]:
    with connection(principal.scope) as conn:
        scope = principal.scope.model_dump(mode="json")
        conn.execute("SELECT set_config('finai.exact_scope',%s,true)", (json.dumps(scope),))
        rows = conn.execute(
            "SELECT payload FROM report_source_assessments WHERE tenant_id=%s AND exact_scope=%s "
            "AND assessment_id LIKE 'rca_%%' "
            "ORDER BY created_at DESC,assessment_id LIMIT 20",
            (principal.scope.tenant_id, Jsonb(scope)),
        ).fetchall()
        return [row[0] for row in rows]
