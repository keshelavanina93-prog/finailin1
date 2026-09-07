"""Actual paused build recovery proof. Worker restart is coordinated externally."""

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

OUT = Path("docs/development/evidence/nin12-transformation-recovery.json")
BASE = Path("docs/development/evidence/nin12-transformation-runtime.json")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    grants = json.loads(os.environ["FINAI_ACCESS_TOKENS"])
    token = next(
        key
        for key, grant in grants.items()
        if {"read", "ontology_read", "ingest"}.issubset(grant["permissions"])
    )
    with httpx.Client(
        base_url="http://127.0.0.1:8062/v1/ontology",
        timeout=30,
        headers={"Authorization": "Bearer " + token},
    ) as client:
        if args.resume:
            evidence = json.loads(OUT.read_text(encoding="utf-8"))
            request = evidence["request"]
        else:
            request = dict(json.loads(BASE.read_text(encoding="utf-8"))["request"])
            request.update(
                request_id=str(uuid4()),
                valid_at=datetime.now(UTC).isoformat(),
                known_at=datetime.now(UTC).isoformat(),
            )
            response = client.post("/transformations/runs", json=request)
            response.raise_for_status()
            evidence = {"request": request, "started_at": datetime.now(UTC).isoformat()}
        path = "/transformations/runs/" + request["request_id"]

        def read():
            response = client.get(path)
            response.raise_for_status()
            return response.json()

        def control(command):
            response = client.post(
                path + "/control",
                json={
                    "command": command,
                    "reason": "Verify retained build recovery across worker restart",
                    "idempotency_key": str(uuid4()),
                },
            )
            response.raise_for_status()

        def first_terminal(result):
            return next(
                (
                    event
                    for event in result["events"]
                    if event["event_id"] == "node:first_page:terminal"
                ),
                None,
            )

        if args.resume:
            before = read()
            assert before["execution"]["state"] == "PAUSED", before.get("execution")
            assert first_terminal(before) == evidence["first_terminal"]
            evidence["after_worker_restart"] = before["execution"]
            control("resume")
        else:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                result = read()
                if any(
                    event["event_id"] == "node:first_page:started"
                    for event in result["events"]
                ):
                    control("pause")
                    break
                if result.get("execution", {}).get("state") == "COMPLETED":
                    raise AssertionError(
                        "Build completed before pause; no pause evidence claimed"
                    )
                time.sleep(0.05)
            else:
                raise AssertionError("First node was not observed starting")
        deadline = time.monotonic() + 60
        wanted = "COMPLETED" if args.resume else "PAUSED"
        while time.monotonic() < deadline:
            result = read()
            state = result.get("execution", {}).get("state")
            if state == wanted:
                break
            if state in ("FAILED", "CANCELLED", "COMPLETED"):
                raise AssertionError("Unexpected build state " + str(state))
            time.sleep(0.15)
        else:
            raise AssertionError("Build did not reach " + wanted)
        if not args.resume:
            terminal = first_terminal(result)
            assert terminal and terminal["state"] == "COMPLETED"
            assert not any(
                event["event_id"] == "node:next_page:started"
                for event in result["events"]
            )
            evidence.update(
                paused_at=datetime.now(UTC).isoformat(),
                first_terminal=terminal,
                paused_execution=result["execution"],
                paused_result=result,
                worker_recovery_verified=False,
            )
        else:
            assert first_terminal(result) == evidence["first_terminal"]
            assert len(result["publications"]) == 1
            assert (
                sum(
                    event["event_id"] == "node:first_page:terminal"
                    for event in result["events"]
                )
                == 1
            )
            evidence.update(
                completed_at=datetime.now(UTC).isoformat(),
                result=result,
                worker_recovery_verified=True,
                completed_step_unchanged=True,
                release_accepted=False,
            )
        OUT.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "request_id": request["request_id"],
                    "state": wanted,
                    "worker_recovery_verified": evidence["worker_recovery_verified"],
                }
            )
        )


if __name__ == "__main__":
    main()
