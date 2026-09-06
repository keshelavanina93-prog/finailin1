"""Read authentic retained SEG evidence through authenticated API; refuse unresolved activation."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from finai_api.main import app


def main():
    token = next(
        key
        for key, value in json.loads(os.environ["FINAI_ACCESS_TOKENS"]).items()
        if "ingest" in value["permissions"]
        and "ontology_propose" in value["permissions"]
    )
    identity = "ir_e630518b23cd9855216cf776fa87e51a5b3d964a912ebc480f47e910b6a073e6"
    path = f"/v1/ontology/source-documents/{identity}/accounting-context/"
    selection = {
        "sheet": "Base",
        "profile": "seg_expense_base",
        "company_id": "365aa5d9-c2ec-52e1-867a-50fe3415f486",
    }
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + token
        response = client.post(path + "inspect", json=selection)
        assert response.status_code == 200, response.text
        context = response.json()
        observed = context["source_observations"]
        assert (
            observed["source_sha256"]
            == "d7c7e67c093b40b6f9209b301ca8fab7e4febc85c27d735babb95fa2028a8f0a"
        )
        assert observed["row_count"] == 596
        assert (observed["observed_from"], observed["observed_through"]) == (
            "2025-01-01",
            "2025-01-31",
        )
        assert (
            not context["canonical_ready"]
            and not observed["accounting_mapping_available"]
        )
        assert all("amount" not in row["attributes"] for row in observed["sample_rows"])
        denied = client.post(
            path + "binding-proposal",
            json={
                **selection,
                "selection": {
                    "source_use": "ACCOUNTING_INPUT",
                    "contract_version": "2",
                    "rationale": "Attempt must refuse unresolved source accounting meaning",
                },
            },
        )
        assert denied.status_code == 409, denied.text
        accounts = None
        if context["company_binding"]["accepted"]:
            account_response = client.post(
                path + "account-observations", json=selection
            )
            assert account_response.status_code == 200, account_response.text
            accounts = account_response.json()
            assert accounts["observed_code_count"] == 38
            assert accounts["row_count"] == 596
            assert accounts["mapping_state"] == "CANDIDATE_REVIEW"
            assert accounts["accounting_use_authorized"] is False
    evidence = {
        "checked_at": datetime.now(UTC).isoformat(),
        "api_inspection_status": response.status_code,
        "activation_status": denied.status_code,
        "activation_blocker": denied.json()["detail"],
        "source_receipt_id": identity,
        "source_sha256": observed["source_sha256"],
        "source_company_label": observed["source_company_label"],
        "row_count": observed["row_count"],
        "observed_from": observed["observed_from"],
        "observed_through": observed["observed_through"],
        "canonical_company_candidate": selection["company_id"],
        "canonical_ready": False,
        "unresolved": context["unresolved"] + observed["unresolved"],
        "authentic_source_read": True,
        "authentic_accounting_calculation": False,
        "financial_certification": None,
        "browser_acceptance": "UNVERIFIED",
        "account_observations": {
            "observed_code_count": accounts["observed_code_count"],
            "mapping_state": accounts["mapping_state"],
            "codes_with_definition_candidates": sum(
                bool(row["definitions"]) for row in accounts["rows"]
            ),
            "accounting_use_authorized": False,
        }
        if accounts
        else None,
    }
    destination = Path(".finai/artifacts/source-accounting-context-v2.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "evidence": str(destination.resolve()),
                "inspection": response.status_code,
                "activation": denied.status_code,
                "authentic_calculation": False,
            }
        )
    )


if __name__ == "__main__":
    main()
