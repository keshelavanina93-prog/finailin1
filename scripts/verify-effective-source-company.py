"""Read the retained SEG match without proposing identity or accounting changes."""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", default="docs/development/evidence/nin26-effective-source-company.json"
    )
    args = parser.parse_args()
    token = next(
        key
        for key, value in json.loads(os.environ["FINAI_ACCESS_TOKENS"]).items()
        if "ingest" in value["permissions"] and "ontology_read" in value["permissions"]
    )
    source = "ir_e630518b23cd9855216cf776fa87e51a5b3d964a912ebc480f47e910b6a073e6"
    company = "365aa5d9-c2ec-52e1-867a-50fe3415f486"
    response = httpx.post(
        f"http://127.0.0.1:3062/api/ontology/source-documents/{source}/accounting-context/inspect",
        headers={"Authorization": "Bearer " + token},
        json={"sheet": "Base", "profile": "seg_expense_base", "company_id": company},
        timeout=30,
    )
    response.raise_for_status()
    result = response.json()
    binding = result["company_binding"]
    assert binding["accepted"]
    assert binding["company"]["resource_id"] == company
    assert binding["alias"]["resource_id"] == "45a5248a-fee0-5bfe-b689-fb935d2345f1"
    assert binding["accounting_use_authorized"] is False
    assert result["canonical_ready"] is False
    evidence = {
        "checked_at": datetime.now(UTC).isoformat(),
        "web_api_status": response.status_code,
        "source": source,
        "company_id": company,
        "company_version_id": binding["company"]["version_id"],
        "alias_id": binding["alias"]["resource_id"],
        "alias_version_id": binding["alias"]["version_id"],
        "identity_binding_accepted": True,
        "canonical_accounting_ready": result["canonical_ready"],
        "remaining_blockers": result["unresolved"],
        "accounting_use_authorized": False,
        "financial_certification_or_release_acceptance": False,
        "scope": "Existing retained SEG source identity match; read-only inspection",
    }
    Path(args.output).write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("Retained SEG company match remains accepted; accounting remains unestablished.")


if __name__ == "__main__":
    main()
