"""Review an explicitly selected source/company match without creating company identities."""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from finai_api.main import app


def main():
    parser = argparse.ArgumentParser()
    for name in ("source", "sheet", "profile", "company", "rationale"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    profiles = json.loads(os.environ["FINAI_ACCESS_TOKENS"])
    author = next(
        key
        for key, value in profiles.items()
        if "ingest" in value["permissions"]
        and "ontology_propose" in value["permissions"]
    )
    reviewer = next(
        key
        for key, value in profiles.items()
        if "ontology_review" in value["permissions"]
        and value["actor_id"] != profiles[author]["actor_id"]
        and value["scope"] == profiles[author]["scope"]
    )
    payload = {"sheet": args.sheet, "profile": args.profile, "company_id": args.company}
    base = f"/v1/ontology/source-documents/{args.source}/accounting-context/"
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + author
        before_response = client.post(base + "inspect", json=payload)
        assert before_response.status_code == 200, before_response.text
        before = before_response.json()
        company_version = before["company_binding"]["company"]["version_id"]
        proposal_id = None
        if not before["company_binding"]["accepted"]:
            proposal = client.post(
                base + "company-binding-proposal",
                json={**payload, "rationale": args.rationale},
            )
            assert proposal.status_code == 200, proposal.text
            proposed = proposal.json()["proposal"]
            assert {item["object_type"] for item in proposed["mutations"]} <= {
                "Alias",
                "SourceRecord",
                "SourceEvidence",
            }
            proposal_id = proposed["proposal_id"]
            client.headers["Authorization"] = "Bearer " + reviewer
            decision = client.post(
                f"/v1/ontology/proposals/{proposal_id}/decision",
                json={"decision": "APPROVED", "rationale": args.rationale},
            )
            assert decision.status_code == 200, decision.text
            client.headers["Authorization"] = "Bearer " + author
        reopened = client.post(base + "inspect", json=payload)
        assert reopened.status_code == 200, reopened.text
        result = reopened.json()
        assert result["company_binding"]["accepted"]
        assert result["company_binding"]["company"]["version_id"] == company_version
        assert (
            result["observed"]["company_alias_id"]
            == result["company_binding"]["alias"]["resource_id"]
        )
        evidence = {
            "checked_at": datetime.now(UTC).isoformat(),
            "source": args.source,
            "company_id": args.company,
            "company_version_unchanged": company_version,
            "proposal_id": proposal_id,
            "source_label": result["source_company_label"],
            "alias_id": result["company_binding"]["alias"]["resource_id"],
            "alias_version_id": result["company_binding"]["alias"]["version_id"],
            "identity_binding_accepted": True,
            "canonical_accounting_ready": result["canonical_ready"],
            "remaining_blockers": result["unresolved"],
            "accounting_use_authorized": False,
            "financial_certification": None,
            "browser_acceptance": "UNVERIFIED",
        }
    destination = Path(".finai/artifacts/source-company-alias.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "evidence": str(destination.resolve()),
                "proposal_id": proposal_id,
                "identity_binding_accepted": True,
                "accounting_ready": result["canonical_ready"],
            }
        )
    )


if __name__ == "__main__":
    main()
