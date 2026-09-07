"""Read-only mounted HTTP proof of the authentic SEG source-movement result.

Requires an already reviewed and executed invocation from the integrated runtime.
Never invokes a Function, publishes journals, changes grants or claims browser QA.
Only bounded references, controls and one original cell are saved as evidence.
"""

import argparse
import json
import os
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal, Inexact, localcontext
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from uuid import UUID

COMPANY = "365aa5d9-c2ec-52e1-867a-50fe3415f486"
SOURCE_SHA = "d7c7e67c093b40b6f9209b301ca8fab7e4febc85c27d735babb95fa2028a8f0a"
SOURCE_ID = "ir_e630518b23cd9855216cf776fa87e51a5b3d964a912ebc480f47e910b6a073e6"
ORIGINAL_ID = "c631bb9c-f92e-5dd9-a693-233c1b3b7925"
ORIGINAL_RECEIPT = "1cb82d90e0945947feb5aee646d8dc3ce076a4c2311b4b2eea17a41dfe2350d7"
CONTROL = "12502967.2300000000006576"
COMPANY_PIN = {
    "resource_id": COMPANY,
    "version_id": "928f83fe-09a5-5f73-82ad-83fcfa77af7b",
    "content_hash": "f1c3000ff2997d128f0d60f6f11197a9f2f720adf1949427e77993ed08516fcf",
}


def digest(value):
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8062")
    parser.add_argument("--invocation", required=True, type=UUID)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    destination = Path(args.output).resolve()
    if destination.drive.upper() != "D:":
        parser.error("Evidence must stay on D:")
    endpoint = urlsplit(args.api)
    if endpoint.scheme != "http" or endpoint.hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        parser.error("This local-runtime verifier requires a loopback HTTP endpoint")
    if endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
        parser.error("API endpoint must not contain credentials, query or fragment")
    token, _ = next(
        (key, grant)
        for key, grant in json.loads(os.environ["FINAI_ACCESS_TOKENS"]).items()
        if {"ingest", "ontology_read"} <= set(grant["permissions"])
        and "ontology_admin" not in grant["permissions"]
    )
    timings = []

    def call(path, body=None, authenticated=True):
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["Authorization"] = "Bearer " + token
        request = Request(
            args.api.rstrip("/") + "/v1/ontology/" + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
        )
        started = perf_counter()
        try:
            with urlopen(request, timeout=60) as response:
                status, data = response.status, json.load(response)
        except HTTPError as exc:
            status, data = exc.code, json.load(exc)
        timings.append(
            {
                "path": path,
                "status": status,
                "seconds": round(perf_counter() - started, 3),
            }
        )
        return status, data

    def ok(path, body=None):
        status, data = call(path, body)
        assert status == 200, ("Unexpected HTTP status", path, status)
        return data

    def historical_original():
        history = ok("functions/invocations/" + ORIGINAL_ID)
        assert history["status"] == "SUCCEEDED"
        assert history["receipt_hash"] == ORIGINAL_RECEIPT
        assert (
            history["output"]["run_id"]
            == "fcr_86a6a3f4e4b8511c86b8068771f6a19474e1279c694561e2e2861ef1fd8ce7a9"
        )
        assert "entity_movement_review" not in history["output"]
        return history

    original = historical_original()
    history = ok("functions/invocations/" + str(args.invocation))
    assert history["status"] == "SUCCEEDED"
    output = history["output"]
    assert output["source_document"]["sha256"] == SOURCE_SHA
    assert output["source_document"]["document_id"] == SOURCE_ID
    assert output["source_document"]["company_id"] == COMPANY
    assert output["business_effect_authorized"] is False
    assert output["current_use_authorized"] is False
    review = output["entity_movement_review"]
    assert review["contract"] == "entity-movement-review/1"
    assert review["business_effect_authorized"] is False
    assert all(
        review[key] is False
        for key in (
            "opening_balances_available",
            "closing_balances_available",
            "certification_available",
        )
    )
    assert review["coverage"] == {
        "source_rows": 596,
        "included_rows": 595,
        "excluded_rows": 1,
        "ledger_completeness": "UNESTABLISHED",
    }
    pairs, movements, receipt = (
        review["pairs"],
        review["movements"],
        review["reconciliation"],
    )
    assert len(pairs) == len({pair["proposed_entry_id"] for pair in pairs}) == 595
    assert len(movements) == 37
    assert receipt["receipt_hash"] == digest(
        {k: v for k, v in receipt.items() if k != "receipt_hash"}
    )
    assert receipt["basis"] == "RETAINED_SOURCE_POSTING_PAIRS"
    assert (
        receipt["status"] == "SOURCE_MOVEMENTS_RECONCILED_JOURNAL_PROMOTION_UNAVAILABLE"
    )
    assert receipt["company_id"] == COMPANY and receipt["source_sha256"] == SOURCE_SHA
    for key in (
        "source_amount_total",
        "source_pair_debit_total",
        "source_pair_credit_total",
    ):
        assert receipt[key] == CONTROL
    assert (
        receipt["difference"] == "0"
        and receipt["accepted_canonical_journal_count"] == 0
    )
    assert all(
        receipt[key] is None
        for key in (
            "canonical_journal_trial_balance",
            "journal_debit_total",
            "journal_credit_total",
        )
    )
    assert receipt["excluded_rows"] == [
        {
            "row": 288,
            "coordinate": "Base!S288",
            "reason": "MISSING_LITERAL_POSTED_AMOUNT",
        }
    ]
    blockers = Counter(
        issue["code"] for pair in pairs for issue in pair["promotion_blockers"]
    )
    assert blockers == {
        "JOURNAL_PUBLICATION_CONTEXT_UNAVAILABLE": 595,
        "ACCOUNT_DIMENSION_POLICY_UNESTABLISHED": 1190,
        "CANONICAL_JOURNAL_AMOUNT_CONTRACT_UNSUPPORTED": 52,
    }
    old_totals = {
        (g["account_code"], g["side"]): g["value"]
        for g in original["output"]["posted_movements"]["groups"]
    }
    with localcontext() as arithmetic:
        arithmetic.prec = 50
        arithmetic.traps[Inexact] = True
        for pair in pairs:
            assert pair["state"] == "SOURCE_POSTING_PAIR_ONLY"
            assert [line["side"] for line in pair["lines"]] == ["DEBIT", "CREDIT"]
            assert pair["lines"][0]["amount"] == pair["lines"][1]["amount"]
        for movement in movements:
            assert (
                movement["opening_balance"] is None
                and movement["closing_balance"] is None
            )
            for side in ("debit", "credit"):
                assert Decimal(movement[side]) == Decimal(
                    old_totals.get((movement["account_code"], side), "0")
                )
            assert Decimal(movement["net_movement"]) == Decimal(
                movement["debit"]
            ) - Decimal(movement["credit"])
        assert sum((Decimal(m["debit"]) for m in movements), Decimal(0)) == Decimal(
            CONTROL
        )
        assert sum((Decimal(m["credit"]) for m in movements), Decimal(0)) == Decimal(
            CONTROL
        )
        assert sum((Decimal(m["net_movement"]) for m in movements), Decimal(0)) == 0

    base = {"invocation_id": str(args.invocation), "company_id": COMPANY}
    projected = ok("analysis/project", base)
    descriptor = projected["descriptor"]
    assert (
        descriptor["contract"] == "semantic-analysis/2"
        and descriptor["row_noun"] == "objects"
    )
    assert descriptor["measure"] is None and descriptor["visual"] == "NONE"
    assert (
        descriptor["current_use_authorized"] is False
        and descriptor["business_effect_authorized"] is False
    )
    assert descriptor["company"] == COMPANY_PIN
    assert descriptor["function"] == output["function"]
    assert (
        descriptor["receipt_hash"] == history["receipt_hash"]
        and descriptor["run_id"] == output["run_id"]
    )
    assert descriptor["valid_at"] == output["query"]["valid_at"]
    assert descriptor["known_at"] == output["query"]["known_at"]
    assert {f["key"]: f["role"] for f in descriptor["fields"]} == {
        "account": "DIMENSION",
        "debit_movement": "ATTRIBUTE",
        "credit_movement": "ATTRIBUTE",
        "net_movement": "ATTRIBUTE",
    }
    assert all(f["aggregation"] == "NONE" for f in descriptor["fields"])
    revision = projected["descriptor_sha256"]
    assert revision == digest({"descriptor": descriptor, "rows": projected["rows"]})
    assert len(projected["rows"]) == projected["total_rows"] == 37
    by_account = {m["account"]["resource_id"]: m for m in movements}
    for row in projected["rows"]:
        movement = by_account[row["values"]["account"]["value"]]
        assert row["trace"] == row["values"]["account"]["reference"]
        assert {
            key: row["trace"][key] for key in ("resource_id", "version_id")
        } == movement["account"]
        for field in ("debit", "credit", "net"):
            assert (
                row["values"][field + "_movement"]["value"]
                == movement["net_movement" if field == "net" else field]
            )
        assert row["contributor_count"] == len(movement["source_coordinates"])
    selected_movement = next(m for m in movements if m["account_code"] == "7310.02.1")
    assert Decimal(selected_movement["debit"]) == Decimal("58988.95")
    selected = next(
        row
        for row in projected["rows"]
        if row["trace"]["resource_id"] == selected_movement["account"]["resource_id"]
    )
    retained_account = ok(
        "operator/resources/"
        + selected["trace"]["resource_id"]
        + "?"
        + urlencode(
            {
                "version_id": selected["trace"]["version_id"],
                "known_at": descriptor["known_at"],
            }
        )
    )["resource"]
    assert selected["trace"] == {
        key: retained_account[key]
        for key in ("resource_id", "version_id", "content_hash")
    }
    contributor_index = selected_movement["source_coordinates"].index("Base!S2")
    selection = {
        **base,
        "descriptor_sha256": revision,
        "selected_row": selected["key"],
        "contributor_index": contributor_index,
        "filters": [{"field": "account", "value": selected["trace"]["resource_id"]}],
        "group_by": "account",
    }
    detail = ok("analysis/project", selection)
    assert (
        detail["descriptor"] == descriptor and detail["descriptor_sha256"] == revision
    )
    assert detail["rows"] == [selected] and detail["sections"][0]["row_keys"] == [
        selected["key"]
    ]
    contributor = detail["selection"]["contributor"]
    assert (
        contributor["coordinate"] == "Base!S2"
        and contributor["source_sha256"] == SOURCE_SHA
    )
    assert (
        contributor["document_id"] == SOURCE_ID
        and contributor.get("basis", "ORIGINAL_SOURCE") == "ORIGINAL_SOURCE"
    )
    cell = next(c for c in contributor["cells"] if c["coordinate"] == "Base!S2")
    assert cell["value"] == "731.97" and cell["formula"] is None
    assert any(c["coordinate"] == "Base!S288" for c in descriptor["excluded_evidence"])
    resumed = ok("analysis/project", detail["request"])
    assert resumed == detail
    refusals = {
        "wrong_company": call(
            "analysis/project",
            {**base, "company_id": "c6f87828-9609-5b35-afa6-e894a0acfe41"},
        )[0],
        "stale_descriptor": call(
            "analysis/project", {**selection, "descriptor_sha256": "0" * 64}
        )[0],
        "forbidden_aggregate": call("analysis/project", {**base, "aggregation": "sum"})[
            0
        ],
        "anonymous": call("analysis/project", base, authenticated=False)[0],
    }
    assert refusals == {
        "wrong_company": 404,
        "stale_descriptor": 409,
        "forbidden_aggregate": 422,
        "anonymous": 401,
    }
    original_after = historical_original()
    assert original_after["output"] == original["output"]
    evidence = {
        "state": "LOCAL_INTEGRATED_ENTITY_MOVEMENT_HTTP_PASS",
        "recorded_at": datetime.now(UTC).isoformat(),
        "api": args.api,
        "native_writes_performed": False,
        "invocation_id": str(args.invocation),
        "receipt_hash": history["receipt_hash"],
        "run_id": output["run_id"],
        "function": descriptor["function"],
        "company": COMPANY_PIN,
        "descriptor_sha256": revision,
        "source_sha256": SOURCE_SHA,
        "movement_accounts": 37,
        "source_pairs": 595,
        "source_rows": 596,
        "source_control": CONTROL,
        "reconciliation_receipt_hash": receipt["receipt_hash"],
        "accepted_canonical_journals": 0,
        "canonical_journal_trial_balance": None,
        "exclusions": receipt["excluded_rows"],
        "promotion_blocker_occurrences": dict(blockers),
        "selected_account": selected["trace"],
        "selected_account_code": "7310.02.1",
        "selected_debit": selected_movement["debit"],
        "selected_row": selected["key"],
        "selected_original_cell": cell,
        "filter_group_resume_verified": True,
        "all_movement_pins_match_retained_result": True,
        "original_invocation": ORIGINAL_ID,
        "original_receipt_unchanged": ORIGINAL_RECEIPT,
        "refusals": refusals,
        "requests": timings,
        "frontend_sdk_execution": "NOT_RUN_BY_THIS_HTTP_HELPER",
        "browser_acceptance": "PENDING",
        "independent_acceptance": "PENDING",
        "release_accepted": False,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "state": evidence["state"],
                "movement_accounts": 37,
                "source_pairs": 595,
                "accepted_canonical_journals": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
