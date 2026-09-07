"""Exercise a reviewed posted-movement build through the actual Temporal API.

--pause retains a completed node before publication. Restart the owned worker
externally, then --resume verifies that checkpoint and completes publication.
--replay resubmits the identical request; --readback performs no mutation.
This records a bounded source-posting proof, never ledger or release acceptance.
"""

import argparse
import hashlib
import json
import os
import time
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from pathlib import Path
from uuid import UUID, uuid4

import httpx


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def save(path, evidence):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def retained(result):
    return {k: v for k, v in result.items() if k not in ("runtime_status", "execution")}


def verify_result(client, result):
    assert result["runtime_status"] == "COMPLETED", result.get("runtime_status")
    assert result["execution"]["state"] == "COMPLETED", result.get("execution")
    assert result["business_effect_authorized"] is False
    assert result["current_use_authorized"] is False
    assert len(result["publications"]) == 1
    publication = result["publications"][0]
    assert publication["authority"] == "EXECUTION_ONLY"
    assert len(publication["outputs"]) == 1
    ref = publication["outputs"][0]["value"]
    response = client.get("/functions/invocations/" + ref["invocation_id"])
    response.raise_for_status()
    invocation = response.json()
    assert invocation["status"] == "SUCCEEDED"
    assert invocation["receipt_hash"] == ref["receipt_hash"]
    output = invocation["output"]
    assert output["run_id"] == ref["run_id"]
    assert output["implementation"]["implementation_id"] == "accounting.retained-posted-movements/v1"
    source = output["source_document"]
    assert source["sha256"] == "d7c7e67c093b40b6f9209b301ca8fab7e4febc85c27d735babb95fa2028a8f0a"
    assert source["sheet"] == "Base"
    assert source["company_id"] == "365aa5d9-c2ec-52e1-867a-50fe3415f486"
    assert output["returned_rows"] == len(output["source_rows"]) == 596
    movements = output["posted_movements"]
    assert movements["coverage"] == {
        "source_rows": 596,
        "included_rows": 595,
        "excluded_rows": 1,
        "ledger_completeness": "UNESTABLISHED",
    }
    assert movements["excluded_rows"] == [{
        "row": 288, "coordinate": "Base!S288", "reason": "MISSING_LITERAL_POSTED_AMOUNT"
    }]
    included = movements["included_coordinates"]
    assert len(included) == len(set(included)) == 595
    assert "Base!S288" not in included
    assert len(movements["groups"]) == 59
    totals = {}
    with localcontext() as context:
        context.prec = 50
        for side in ("debit", "credit"):
            groups = [g for g in movements["groups"] if g["side"] == side]
            coordinates = [c for g in groups for c in g["source_coordinates"]]
            assert sorted(coordinates) == sorted(included)
            assert all(g["currency_id"] == source["context"]["currency_id"] for g in groups)
            totals[side] = format(sum((Decimal(g["value"]) for g in groups), Decimal(0)), "f")
    assert totals["debit"] == totals["credit"] == "12502967.2300000000006576"
    return {
        "publication": publication,
        "invocation_id": invocation["invocation_id"],
        "receipt_hash": invocation["receipt_hash"],
        "run_id": output["run_id"],
        "retained_build_sha256": digest(retained(result)),
        "retained_invocation_sha256": digest(invocation),
        "coverage": movements["coverage"],
        "excluded_rows": movements["excluded_rows"],
        "account_side_groups": len(movements["groups"]),
        "posted_control_sums": totals,
        "source": source,
        "function": output["function"],
        "implementation": output["implementation"],
        "query": output["query"],
        "events": result["events"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    for mode in ("start", "pause", "resume", "replay", "readback"):
        modes.add_argument("--" + mode, action="store_true")
    parser.add_argument("--definition-id", type=UUID)
    parser.add_argument("--base-url", default="http://127.0.0.1:8062/v1/ontology")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--restart-evidence", type=Path,
                        help="Recorded owned worker identities before and after restart")
    parser.add_argument("--output", type=Path, default=Path(
        "docs/development/evidence/nin58-posted-movement-worker.json"
    ))
    args = parser.parse_args()
    if args.resume and not args.restart_evidence:
        parser.error("--resume requires --restart-evidence from the owned worker restart")
    grants = json.loads(os.environ["FINAI_ACCESS_TOKENS"])
    token = next(key for key, grant in grants.items()
                 if {"read", "ontology_read", "ingest"}.issubset(grant["permissions"]))
    with httpx.Client(base_url=args.base_url, headers={"Authorization": "Bearer " + token},
                      timeout=60, trust_env=False, follow_redirects=False) as client:
        if args.start or args.pause:
            assert args.definition_id, "Use the reviewed target Transformation identity"
            assert not args.output.exists(), "Preserve the previous evidence; choose a fresh path"
            response = client.get("/resources/" + str(args.definition_id))
            response.raise_for_status()
            definition = response.json()["resource"]
            assert definition["object_type"] == "TransformationDefinition"
            cutoff = datetime.now(UTC).isoformat()
            evidence = {"request": {
                "request_id": str(uuid4()),
                "transformation": {"resource_id": str(args.definition_id),
                                   "version_id": definition["version_id"]},
                "valid_at": cutoff, "known_at": cutoff,
            }, "started_at": cutoff, "release_accepted": False}
            save(args.output, evidence)
        else:
            evidence = json.loads(args.output.read_text(encoding="utf-8"))
        request = evidence["request"]
        path = "/transformations/runs/" + request["request_id"]

        def read():
            response = client.get(path)
            response.raise_for_status()
            return response.json()

        def control(command):
            response = client.post(path + "/control", json={
                "command": command,
                "reason": "Verify retained authentic posted movements across owned worker restart",
                "idempotency_key": str(uuid4()),
            })
            response.raise_for_status()

        if args.start or args.pause or args.replay:
            response = client.post("/transformations/runs", json=request)
            response.raise_for_status()
            assert response.json()["workflow_id"] == "transformation:" + request["request_id"]
        if args.resume:
            before = read()
            assert before["execution"]["state"] == "PAUSED"
            assert retained(before) == evidence["paused_retained"]
            evidence["checkpoint_read_after_restart"] = datetime.now(UTC).isoformat()
            save(args.output, evidence)
            control("resume")
        deadline = time.monotonic() + args.timeout
        pause_sent = False
        while True:
            result = read()
            state = result.get("execution", {}).get("state")
            events = result.get("events", [])
            if args.pause and not pause_sent and any(e.get("state") == "RUNNING" and e.get("node") for e in events):
                assert not result.get("publications"), "Build already published; no checkpoint proof"
                control("pause")
                pause_sent = True
            if args.pause and state == "PAUSED":
                terminals = [e for e in events if e.get("node") and e.get("state") == "COMPLETED"]
                assert len(terminals) == 1 and not result["publications"]
                evidence.update(paused_retained=retained(result), completed_node=terminals[0],
                                phase="PAUSED_AFTER_COMPLETED_NODE", worker_recovery_verified=False)
                save(args.output, evidence)
                print(json.dumps({"request_id": request["request_id"], "phase": evidence["phase"]}))
                return
            if state == "COMPLETED" and result["runtime_status"] == "COMPLETED":
                assert not args.pause, "Build completed before pause; no recovery proof"
                break
            assert state not in ("FAILED", "CANCELLED"), result.get("execution")
            assert time.monotonic() < deadline, "Worker did not reach the expected state"
            time.sleep(0.1 if args.pause else 0.5)
        verified = verify_result(client, result)
        if evidence.get("verified"):
            assert evidence["verified"] == verified, "Retained build or invocation changed"
        if args.resume or args.restart_evidence:
            assert args.restart_evidence, "Supply the recorded worker restart identities"
            restart = json.loads(args.restart_evidence.read_text(encoding="utf-8-sig"))
            assert restart["before"]["name"] == restart["after"]["name"] == "worker"
            assert restart["before"]["exe"] == restart["after"]["exe"]
            assert restart["after"]["exe"].lower().startswith("d:\\")
            assert restart["before"]["pid"] != restart["after"]["pid"]
            restarted_at = datetime.fromisoformat(restart["after"]["created"].replace("Z", "+00:00"))
            assert evidence["completed_node"] in result["events"]
            assert sum(e["event_id"] == evidence["completed_node"]["event_id"] for e in result["events"]) == 1
            assert datetime.fromisoformat(evidence["completed_node"]["created_at"]) < restarted_at
            resumes = [e for e in result["events"] if e.get("command") == "resume"]
            assert len(resumes) == 1 and restarted_at < datetime.fromisoformat(resumes[0]["created_at"])
            for event in evidence["paused_retained"]["events"]:
                assert event in result["events"]
            evidence["worker_restart"] = restart
            evidence["worker_recovery_verified"] = True
        evidence.update(verified=verified, phase="COMPLETED", actual_temporal_worker_verified=True)
        if args.replay:
            evidence["idempotent_replay_verified_at"] = datetime.now(UTC).isoformat()
        if args.readback:
            evidence["unchanged_readback_verified_at"] = datetime.now(UTC).isoformat()
        save(args.output, evidence)
        print(json.dumps({"request_id": request["request_id"], "phase": evidence["phase"],
                          "invocation_id": verified["invocation_id"],
                          "worker_recovery_verified": evidence.get("worker_recovery_verified", False)}))


if __name__ == "__main__":
    main()
