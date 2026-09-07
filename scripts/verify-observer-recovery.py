"""Read retained evidence after the managed collector's actual outage/restart proof."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx


def main():
    before = json.loads(
        Path(".finai/tmp/observer-outage.json").read_text(encoding="utf-8")
    )
    after = json.loads(
        Path(".finai/runtime-observer/checkpoint.json").read_text(encoding="utf-8")
    )
    request = before["pending"]
    assert before["last_ack"] is None and request
    assert after["pending"] is None
    assert before["config_hash"] == after["config_hash"]
    grants = json.loads(os.environ["FINAI_ACCESS_TOKENS"])
    token = next(t for t, g in grants.items() if g["actor_id"] == "local-steward")
    with httpx.Client(
        base_url="http://127.0.0.1:8062/v1/ontology/runtime-observations",
        headers={"Authorization": "Bearer " + token},
        timeout=30,
        trust_env=False,
    ) as client:
        response = client.get("/" + request["request_id"])
        response.raise_for_status()
        receipt = response.json()
        assert receipt["request_id"] == request["request_id"]
        assert (
            receipt["reported_state"]["desired_state"]["version_id"]
            == request["desired_state"]["version_id"]
        )
        assert receipt["reported_state"]["recorded_state"] == "DRIFT"
        assert receipt["deployment_authorized"] is False
        assert receipt["current_use_authorized"] is False
        latest = client.get("/" + after["last_ack"]["request_id"])
        latest.raise_for_status()
        latest_receipt = latest.json()
        for key in ("request_id", "run_id", "proof_hash", "recorded_at"):
            assert latest_receipt[key] == after["last_ack"][key]
    Path("docs/development/evidence/nin31-managed-observer-recovery.json").write_text(
        json.dumps(
            {
                "checked_at": datetime.now(UTC).isoformat(),
                "outage_checkpoint": before,
                "recovered_checkpoint": after,
                "recovered_request_receipt": receipt,
                "latest_ack_receipt": latest_receipt,
                "same_pending_request_recovered": True,
                "desired_state_unchanged": True,
                "scope": "LOCAL_API_OUTAGE_AND_COLLECTOR_PROCESS_RESTART",
                "power_loss_recovery_proven": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        "Original pending request recovered; receipt readback verified; reviewed expectation reports DRIFT."
    )


if __name__ == "__main__":
    main()
