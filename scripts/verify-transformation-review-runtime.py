"""Actual-source publication review proof; runtime restarts are separately supervised."""

import argparse
import importlib.util
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.review import Principal
from finai_api.services import resources

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location(
    "retained_input_proof", ROOT / "scripts/verify-transformation-input-runtime.py"
)
chain = importlib.util.module_from_spec(loader)
loader.loader.exec_module(chain)
KEY = "source-accounts:reviewed-publication-chain:v1"
QUESTION = "Do the retained source account objects and derived labels support publishing this observation-only evidence build?"


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def verify_task_outputs(client, task):
    assert len(task["outputs"]) == 2
    for reference in task["outputs"]:
        response = client.get(f"/functions/invocations/{reference['invocation_id']}")
        response.raise_for_status()
        invocation = response.json()
        assert invocation["status"] == "SUCCEEDED"
        assert invocation["receipt_hash"] == reference["receipt_hash"]
        assert invocation["output"]["run_id"] == reference["run_id"]
        assert invocation["output"]["mode"] == "EVIDENCE_ANALYSIS_ONLY"
        assert len(invocation["output"]["objects"]) == 3


def wait_state(client, request_id, expected, timeout):
    deadline = time.monotonic() + timeout
    while True:
        response = client.get(f"/transformations/runs/{request_id}")
        response.raise_for_status()
        result = response.json()
        assert result["workflow_id"] == "transformation:" + request_id
        assert result["business_effect_authorized"] is False
        assert result["current_use_authorized"] is False
        state = result.get("execution", {}).get("state")
        if state == expected:
            return result
        if state in ("FAILED", "CANCELLED"):
            raise AssertionError(f"Unexpected build state: {state}")
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Build did not reach {expected}")
        time.sleep(1)


def finish_decision(args, client, checker_token, previous, request):
    decision = "APPROVED" if args.approve else "REJECTED"
    intended = previous.get("decision_request") or {
        "decision_id": str(uuid4()),
        "decision": decision,
        "reason": "Review of exact retained source account objects and derived labels; observation evidence only.",
    }
    assert intended["decision"] == decision
    path = f"/transformations/runs/{request['request_id']}/publication-review"
    pending_response = client.get(f"/transformations/runs/{request['request_id']}")
    pending_response.raise_for_status()
    pending = pending_response.json()
    task = pending["publication_review"]
    assert task["question"] == QUESTION
    if previous.get("result", {}).get("publication_review"):
        assert task["task_id"] == previous["result"]["publication_review"]["task_id"]
        assert task["outputs"] == previous["result"]["publication_review"]["outputs"]
    verify_task_outputs(client, task)
    if task["state"] == "PENDING":
        assert not pending["publications"]
        maker_response = client.post(path, json=intended)
        assert maker_response.status_code == 403, (
            "Maker must not decide their own publication task"
        )
    else:
        assert task["state"] == decision
        assert task["decision"]["decision_id"] == intended["decision_id"]
    save(args.output, {**previous, "decision_request": intended})
    with httpx.Client(
        base_url=args.base_url,
        headers={"Authorization": "Bearer " + checker_token},
        timeout=60,
        trust_env=False,
    ) as checker_client:
        verify_task_outputs(checker_client, task)
        response = checker_client.post(path, json=intended)
        response.raise_for_status()
        repeated = checker_client.post(path, json=intended)
        repeated.raise_for_status()
    expected = "COMPLETED" if args.approve else "REJECTED"
    result = wait_state(client, request["request_id"], expected, args.timeout)
    assert result["publication_review"]["state"] == decision
    assert (
        result["publication_review"]["decision"]["decision_id"]
        == intended["decision_id"]
    )
    if args.approve:
        proof = chain.verify_chain(client, result)
    else:
        assert not result["publications"]
        proof = {"rejected_without_publication": True}
    response = client.get(f"/transformations/runs/{request['request_id']}")
    response.raise_for_status()
    assert chain.shared.retained_part(result) == chain.shared.retained_part(
        response.json()
    )
    save(
        args.output,
        {
            **previous,
            "checked_at": datetime.now(UTC).isoformat(),
            "request": request,
            "result": result,
            "expected_state": expected,
            "decision_request": intended,
            "chain": proof,
            "same_decision_replay_verified": True,
            "financial_authority_established": False,
            "restart_performed_by_this_script": False,
        },
    )
    print(
        "Independent publication decision retained; repeated decision and readback agree."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--prepare", action="store_true")
    modes.add_argument("--approve", action="store_true")
    modes.add_argument("--reject", action="store_true")
    modes.add_argument("--read-only", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:3062/api/ontology")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/development/evidence/nin29-publication-review-runtime.json"),
    )
    args = parser.parse_args()
    grants = json.loads(os.environ["FINAI_ACCESS_TOKENS"])
    required = (
        {"ontology_admin", "ontology_propose", "ontology_read"}
        if args.prepare
        else {"read", "ingest", "ontology_read"}
    )
    token, maker = next(
        (token, Principal.model_validate(grant))
        for token, grant in grants.items()
        if required.issubset(grant["permissions"])
    )
    checker_token, checker = next(
        (token, Principal.model_validate(grant))
        for token, grant in grants.items()
        if grant["actor_id"] != maker.actor_id
        and grant["scope"] == maker.scope.model_dump(mode="json")
        and (
            {"ontology_admin", "ontology_review"}
            if args.prepare
            else {"read", "ontology_read", "review"}
        ).issubset(grant["permissions"])
    )
    identity = canonical_id(maker.scope.tenant_id, "TransformationDefinition", KEY)
    if args.prepare:
        source_id = canonical_id(
            maker.scope.tenant_id, "TransformationDefinition", chain.KEY
        )
        source = resources.get_resource(maker, source_id)["resource"]
        attributes = {
            **source["attributes"],
            "publication_review": {"question": QUESTION},
        }
        result = chain.publish(
            maker,
            checker,
            "TransformationDefinition",
            KEY,
            "Review source account evidence before publication",
            attributes,
        )
        print(
            json.dumps(
                {
                    "resource_id": result["resource_id"],
                    "version_id": result["version_id"],
                    "prepared_only": True,
                }
            )
        )
        return
    previous = (
        json.loads(args.output.read_text(encoding="utf-8"))
        if args.approve or args.reject or args.read_only
        else None
    )
    with httpx.Client(
        base_url=args.base_url, headers={"Authorization": "Bearer " + token}, timeout=60
    ) as client:
        if previous:
            request = previous["request"]
        else:
            response = client.get(f"/resources/{identity}")
            response.raise_for_status()
            now = datetime.now(UTC).isoformat()
            request = {
                "request_id": str(uuid4()),
                "transformation": {
                    "resource_id": str(identity),
                    "version_id": response.json()["resource"]["version_id"],
                },
                "valid_at": now,
                "known_at": now,
            }
            save(args.output, {"phase": "REQUEST_PREPARED", "request": request})
            response = client.post("/transformations/runs", json=request)
            response.raise_for_status()
        if args.approve or args.reject:
            finish_decision(args, client, checker_token, previous, request)
            return
        expected = (
            previous.get("expected_state", "AWAITING_REVIEW")
            if previous
            else "AWAITING_REVIEW"
        )
        result = wait_state(client, request["request_id"], expected, args.timeout)
        if expected == "AWAITING_REVIEW":
            assert not result["publications"]
            assert (
                len(
                    [
                        event
                        for event in result["events"]
                        if event.get("state") == "COMPLETED"
                    ]
                )
                == 2
            )
            assert result["publication_review"]["state"] == "PENDING"
            assert result["publication_review"]["question"] == QUESTION
            verify_task_outputs(client, result["publication_review"])
        if previous and previous.get("result"):
            assert chain.shared.retained_part(result) == chain.shared.retained_part(
                previous["result"]
            )
        save(
            args.output,
            {
                **(previous or {}),
                "checked_at": datetime.now(UTC).isoformat(),
                "request": request,
                "result": result,
                "expected_state": expected,
                "read_only_verification": args.read_only,
                "financial_authority_established": False,
                "restart_performed_by_this_script": False,
            },
        )
        print("Retained review state verified; no publication before decision.")


if __name__ == "__main__":
    main()
