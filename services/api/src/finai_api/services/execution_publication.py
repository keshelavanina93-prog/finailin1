"""Atomic, immutable execution output sets over the scoped workflow event store.

Staged outputs are diagnostics, not published data products. A single immutable
manifest publishes the complete declared set. Publication never promotes authority.
"""

import json
from hashlib import sha256
from typing import Any

from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services import report_workflows as records
from finai_api.services.workspace import WorkspaceError


def digest(value: Any) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _contract(record: dict[str, Any], generation: int) -> dict[str, str]:
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
        raise WorkspaceError(422, "Invalid execution generation")
    contract = record["definition"].get("outputs")
    if (
        not isinstance(contract, dict)
        or not contract
        or len(contract) > 100
        or any(
            not isinstance(k, str) or not k or not isinstance(v, str) or not v
            for k, v in contract.items()
        )
    ):
        raise WorkspaceError(409, "Workflow has no valid declared output contract")
    return contract


def stage(
    principal: Principal,
    identity: str,
    generation: int,
    slot: str,
    artifact_type: str,
    value: dict[str, Any],
) -> dict[str, Any]:
    require_permission(principal, "read")
    require_permission(principal, "ingest")
    record = records.read(principal, identity)
    contract = _contract(record, generation)
    if contract.get(slot) != artifact_type:
        raise WorkspaceError(409, "Output does not match the retained definition contract")
    # Length-prefix via JSON avoids ambiguous node/generation delimiter identities.
    key = "output:" + digest([generation, slot])
    payload = {
        "node": slot,
        "state": "STAGED",
        "generation": generation,
        "artifact_type": artifact_type,
        "value": value,
        "sha256": digest(value),
    }
    if len(json.dumps(payload).encode()) > 1_000_000:
        raise WorkspaceError(
            413, "Output metadata exceeds publication limit; use retained references"
        )
    records.event(principal, identity, key, payload)
    return {"event_id": key, "sha256": payload["sha256"]}


def publish(principal: Principal, identity: str, generation: int) -> dict[str, Any]:
    require_permission(principal, "read")
    require_permission(principal, "ingest")
    record = records.read(principal, identity)
    contract = _contract(record, generation)
    events = {event["event_id"]: event for event in record["events"]}
    outputs = []
    for slot, artifact_type in sorted(contract.items()):
        key = "output:" + digest([generation, slot])
        output = events.get(key)
        if not output or output.get("state") != "STAGED":
            raise WorkspaceError(409, "Execution outputs incomplete; nothing was published")
        if (
            output.get("artifact_type") != artifact_type
            or output.get("generation") != generation
            or output.get("sha256") != digest(output.get("value"))
        ):
            raise WorkspaceError(409, "Retained output integrity does not match its contract")
        outputs.append(
            {
                "slot": slot,
                "artifact_type": artifact_type,
                "event_id": key,
                "sha256": output["sha256"],
                "value": output["value"],
            }
        )
    manifest = {
        "protocol": "execution-publication/1",
        "workflow_id": identity,
        "generation": generation,
        "definition_sha256": digest(record["definition"]),
        "authority": "EXECUTION_ONLY",
        "outputs": outputs,
    }
    manifest["publication_id"] = "pub_" + digest(manifest)
    # The one-row insert is the commit point; all referenced staging rows are immutable.
    # A timeout after commit is safely retried under the same stable event identity.
    records.event(
        principal,
        identity,
        f"publication:{generation}",
        {"node": "publication", "state": "PUBLISHED", "manifest": manifest},
    )
    return manifest


def published(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Consumer boundary: incomplete/staged attempts never appear as published output."""
    return sorted(
        [
            event["manifest"]
            for event in record["events"]
            if event["event_id"].startswith("publication:") and event.get("state") == "PUBLISHED"
        ],
        key=lambda item: item["generation"],
    )
