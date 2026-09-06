"""Read-only authentic briefing proof through the running G8 web/API proxy.

Run after scripts/load-local.ps1 with the packaged API and web running on 8062/3062.
This inspects retained resources and does not create facts, trigger workflows or grant use.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

import httpx

COMPANIES = {
    "SOCAR Georgia Gas": "a5f221e2-17a1-5903-9f3f-e2d896b3fc9d",
    "SOCAR Georgia Petroleum": "dc706c30-a8fb-57dc-b098-8a6bf2c2309d",
}


def main():
    token = next(
        key
        for key, grant in json.loads(os.environ["FINAI_ACCESS_TOKENS"]).items()
        if "ontology_read" in grant.get("permissions", [])
    )
    cutoff = datetime.now(UTC).isoformat()
    requests, companies = [], []
    with httpx.Client(
        base_url="http://127.0.0.1:3062",
        headers={"Authorization": "Bearer " + token},
        timeout=25,
    ) as client:

        def read(label, path, *, params=None, body=None):
            started = monotonic()
            response = (
                client.get(path, params=params)
                if body is None
                else client.post(path, json=body)
            )
            requests.append(
                {
                    "read": label,
                    "http_status": response.status_code,
                    "seconds": round(monotonic() - started, 3),
                }
            )
            response.raise_for_status()
            return response.json()

        for name, identity in COMPANIES.items():
            envelope = read(
                name + " company context",
                "/api/ontology/company-context",
                params={
                    "company_id": identity,
                    "valid_at": cutoff,
                    "known_at": cutoff,
                },
            )
            context = envelope["context"]
            assert context["company"]["resource_id"] == identity
            assert datetime.fromisoformat(
                envelope["known_at"]
            ) == datetime.fromisoformat(cutoff)
            params = {
                "company_id": identity,
                "effective_at": cutoff,
                "known_at": cutoff,
                "sort": "recorded_desc",
                "limit": 2,
            }
            first = read(
                name + " newest page one", "/api/ontology/history-search", params=params
            )
            second = read(
                name + " newest page two",
                "/api/ontology/history-search",
                params={**params, "offset": 2},
            )
            prefix = read(
                name + " same-cutoff prefix",
                "/api/ontology/history-search",
                params={**params, "limit": 4},
            )
            joined = first["resources"] + second["resources"]
            assert joined and first["sort"] == second["sort"] == "recorded_desc"
            assert [r["version_id"] for r in joined] == [
                r["version_id"] for r in prefix["resources"]
            ]
            assert len({r["resource_id"] for r in joined}) == len(joined)
            assert joined == sorted(
                joined,
                key=lambda r: (
                    -datetime.fromisoformat(r["system_from"]).timestamp(),
                    r["resource_id"],
                ),
            )
            assert all(
                datetime.fromisoformat(r["system_from"])
                <= datetime.fromisoformat(cutoff)
                for r in joined
            )
            assert (
                first["matched_count"]
                == second["matched_count"]
                == prefix["matched_count"]
            )
            assert (
                first["type_facets"] == second["type_facets"] == prefix["type_facets"]
            )
            assert (
                sum(f["count"] for f in first["type_facets"]) == first["matched_count"]
            )
            assert first["current_use_authorized"] is False

            selected = first["resources"][0]
            inspection = read(
                name + " exact inspection",
                "/api/ontology/operator/resources/" + selected["resource_id"],
                params={
                    "version_id": selected["version_id"],
                    "known_at": cutoff,
                },
            )
            assert inspection["resource"]["version_id"] == selected["version_id"]
            assert datetime.fromisoformat(
                inspection["known_at"]
            ) == datetime.fromisoformat(cutoff)
            assert inspection["selection_mode"] == "EXACT_VERSION"
            assert inspection["current_use_authorized"] is False
            assert all(
                datetime.fromisoformat(r["system_from"])
                <= datetime.fromisoformat(cutoff)
                for r in inspection["versions"]
            )

            states = {}
            for source in context["accounting_sources"]:
                for status in source.get("binding_eligibility", {}).values():
                    state = status["state"]
                    states[state] = states.get(state, 0) + 1
                    assert status["current_use_authorized"] is False
            companies.append(
                {
                    "company_id": identity,
                    "company_version_id": context["company"]["version_id"],
                    "name": name,
                    "retained_name": context["company"]["display_name"],
                    "accounting_state": context["accounting_state"],
                    "readiness_counts": {
                        "configured_ledgers": sum(
                            bool(r["ready"]) for r in context["ledgers"]
                        ),
                        "accounting_sources": len(context["accounting_sources"]),
                        "reviewed_bindings": sum(
                            len(r["bindings"]) for r in context["accounting_sources"]
                        ),
                        "licence_evidence": len(context["licence_evidence"]),
                        "relationships": len(context["relationships"]),
                        "disclosures": len(context["disclosures"]),
                        "structural_resources": len(context["structural_resources"]),
                    },
                    "current_advisory_binding_states": states,
                    "matched_resources": first["matched_count"],
                    "type_facets": first["type_facets"],
                    "newest_versions_checked": [r["version_id"] for r in joined],
                    "newest_sort_across_pages_verified": True,
                    "same_cutoff_exact_inspection_verified": True,
                    "inspected_resource_id": selected["resource_id"],
                    "inspected_version_id": selected["version_id"],
                }
            )

        incoming = read(
            "Petroleum incoming legal entity dependencies",
            "/api/ontology/object-sets/query",
            body={
                "object_type": "LegalEntity",
                "resource_ids": [COMPANIES["SOCAR Georgia Petroleum"]],
                "valid_at": cutoff,
                "known_at": cutoff,
                "limit": 1,
                "traversal": [
                    {
                        "kind": "reference",
                        "name": "legal_entity_id",
                        "direction": "incoming",
                    }
                ],
            },
        )
        assert incoming["total"] == sum(incoming["counts_by_type"].values())
        assert incoming["total"] > 0 and len(incoming["objects"]) == 1
        assert datetime.fromisoformat(
            incoming["query"]["known_at"]
        ) == datetime.fromisoformat(cutoff)

    evidence = {
        "checked_at": datetime.now(UTC).isoformat(),
        "fixed_knowledge_and_effective_cutoff": cutoff,
        "capability": "NIN-25 company briefing / NIN-6 exact incoming traversal",
        "mode": "authenticated running web proxy over retained SOCAR canonical resources",
        "web_url": "http://127.0.0.1:3062",
        "companies": companies,
        "petroleum_incoming": {
            "total": incoming["total"],
            "counts_by_type": incoming["counts_by_type"],
            "page_size": len(incoming["objects"]),
            "seconds": requests[-1]["seconds"],
        },
        "requests": requests,
        "browser_acceptance": False,
        "financial_calculation_acceptance": False,
        "full_NIN_6_acceptance": False,
        "full_NIN_25_acceptance": False,
        "release_accepted": False,
    }
    Path("docs/development/evidence/nin25-company-briefing.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    # PowerShell may use a legacy console encoding; the retained artifact stays UTF-8.
    print(json.dumps(evidence))


if __name__ == "__main__":
    main()
