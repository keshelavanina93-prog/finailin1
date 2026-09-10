"""Durable petroleum variance investigation and action boundary.

The control workflow retains the exact variance snapshot and actor decisions in
the shared scoped workflow tables. It is intentionally not an external adapter:
execution is refused until a configured adapter can provide readback.
"""

import json
from collections.abc import Callable
from hashlib import sha256
from typing import Any, Literal

from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from finai_api.config import get_settings
from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services import petroleum_reconciliation, report_workflows
from finai_api.services.workspace import WorkspaceError


class InvestigationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    variance_id: str = Field(min_length=1, max_length=200)
    rationale: str = Field(min_length=10, max_length=2000)


class ControlDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    decision: str = Field(
        pattern=r"^(ACCEPT_EXPLANATION|REJECT_EXPLANATION|PROPOSE_ACTION|APPROVE_ACTION)$"
    )
    rationale: str = Field(min_length=10, max_length=2000)


class ActionReadback(BaseModel):
    """Typed adapter receipt; it never grants accounting authority."""

    contract: Literal["petroleum-action-readback/1"] = "petroleum-action-readback/1"
    adapter_id: str = Field(min_length=1, max_length=128)
    external_action_id: str = Field(min_length=1, max_length=256)
    readback_id: str = Field(min_length=1, max_length=256)
    readback_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: Literal["VERIFIED"] = "VERIFIED"


ActionAdapter = Callable[[Principal, str, dict[str, Any]], ActionReadback]


def _identity(principal: Principal, variance: dict[str, Any], rationale: str) -> str:
    value = {
        "tenant_id": str(principal.scope.tenant_id),
        "company_id": str(principal.scope.legal_entity_id),
        "variance_id": variance["variance_id"],
        "variance": variance,
        "rationale": rationale,
    }
    content = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return "pvc_" + sha256(content.encode()).hexdigest()


def _find(principal: Principal, variance_id: str) -> dict[str, Any]:
    # The authenticated scope already constrains the accepted resource query.
    # legal_entity_id is a governed business identifier and is not required to
    # be UUID-shaped (for example, SOCAR_PETROLEUM_GEORGIA).
    result = petroleum_reconciliation.variances(principal)
    for row in result["rows"]:
        if row["variance_id"] == variance_id:
            return row
    raise WorkspaceError(404, "Petroleum variance is unavailable in the authorized company scope")


def _local_action_adapter(
    _principal: Principal, control_id: str, current: dict[str, Any]
) -> ActionReadback:
    """A deterministic local-dev adapter with explicit non-production identity."""
    digest = sha256(
        json.dumps(
            {"control_id": control_id, "variance": current["variance"]},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return ActionReadback(
        adapter_id="LOCAL_SIMULATION_ONLY",
        external_action_id=f"local-action-{digest[:32]}",
        readback_id=f"local-readback-{digest[32:]}",
        readback_hash=digest,
    )


def _adapter_for(_principal: Principal, _current: dict[str, Any]) -> ActionAdapter | None:
    settings = get_settings()
    if settings.environment == "local" and settings.petroleum_action_adapter == "local":
        return _local_action_adapter
    return None


def start(principal: Principal, request: InvestigationRequest) -> dict[str, Any]:
    require_permission(principal, "ontology_propose")
    variance = _find(principal, request.variance_id)
    identity = _identity(principal, variance, request.rationale)
    scope = principal.scope.model_dump(mode="json")
    payload = {
        "definition": {
            "version": "petroleum-control/1",
            "effect": "INVESTIGATION_AND_GOVERNED_ACTION",
        },
        "variance": variance,
        "rationale": request.rationale,
        "state": "INVESTIGATION_OPEN",
        "initiator_actor_id": principal.actor_id,
        "request_hash": sha256(request.model_dump_json().encode()).hexdigest(),
    }
    with report_workflows.scope_connection(principal) as conn:
        report_workflows.set_scope(conn, principal)
        conn.execute(
            "INSERT INTO workflow_requests(tenant_id,workflow_id,exact_scope,actor_id,"
            "definition_version,payload) "
            "VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (
                principal.scope.tenant_id,
                identity,
                Jsonb(scope),
                principal.actor_id,
                "petroleum-control/1",
                Jsonb(payload),
            ),
        )
    report_workflows.event(principal, identity, "investigation-opened", {
        "state": "INVESTIGATION_OPEN", "actor_id": principal.actor_id,
        "variance_id": variance["variance_id"],
    })
    return read(principal, identity)


def read(principal: Principal, control_id: str) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    record = report_workflows.read(principal, control_id)
    if record["definition"].get("version") != "petroleum-control/1":
        raise WorkspaceError(404, "Petroleum control workflow unavailable")
    request = record["request"]
    events = record["events"]
    state = request.get("state", "INVESTIGATION_OPEN")
    execution = "REFUSED_NO_EXTERNAL_ADAPTER"
    readback: dict[str, Any] | None = None
    for event in events:
        if event.get("state") in {
            "EXPLANATION_ACCEPTED", "EXPLANATION_REJECTED", "ACTION_PROPOSED",
            "APPROVED", "REFUSED", "READBACK_VERIFIED",
        }:
            state = event["state"]
        if event.get("execution"):
            execution = str(event["execution"])
        if event.get("readback"):
            readback = event["readback"]
    return {"contract": "petroleum-control/1", "control_id": control_id,
            "variance": request["variance"], "state": state, "events": events,
            "initiator_actor_id": request["initiator_actor_id"],
            "execution": execution, "readback": readback,
            "accounting_authorized": False, "business_effect_authorized": False}


def decide(
    principal: Principal, control_id: str, request: ControlDecisionRequest
) -> dict[str, Any]:
    require_permission(principal, "ontology_review")
    current = read(principal, control_id)
    if current["initiator_actor_id"] == principal.actor_id:
        raise WorkspaceError(403, "Maker/checker separation requires an independent reviewer")
    allowed = {"INVESTIGATION_OPEN", "EXPLANATION_REJECTED"}
    if request.decision == "APPROVE_ACTION":
        allowed = {"ACTION_PROPOSED"}
    if current["state"] not in allowed:
        raise WorkspaceError(409, "Petroleum control is not awaiting an independent decision")
    state = {"ACCEPT_EXPLANATION": "EXPLANATION_ACCEPTED",
             "REJECT_EXPLANATION": "EXPLANATION_REJECTED",
             "PROPOSE_ACTION": "ACTION_PROPOSED",
             "APPROVE_ACTION": "APPROVED"}[request.decision]
    report_workflows.event(principal, control_id, "decision:" + request.decision.lower(), {
        "state": state, "actor_id": principal.actor_id, "rationale": request.rationale,
    })
    return read(principal, control_id)


def execute(principal: Principal, control_id: str) -> dict[str, Any]:
    require_permission(principal, "ontology_propose")
    current = read(principal, control_id)
    if current["state"] != "APPROVED":
        raise WorkspaceError(409, "Only an independently approved action can execute")
    adapter = _adapter_for(principal, current)
    if adapter is None:
        report_workflows.event(principal, control_id, "execution-refused", {
            "state": "REFUSED",
            "reason": "No configured external petroleum adapter can provide readback",
        })
        raise WorkspaceError(
            409,
            "External petroleum action adapter is not configured; no action was executed",
        )
    try:
        receipt = adapter(principal, control_id, current)
    except (ValueError, TypeError) as exc:
        raise WorkspaceError(409, "Petroleum action adapter returned an invalid receipt") from exc
    report_workflows.event(principal, control_id, "execution-readback", {
        "state": "READBACK_VERIFIED",
        "execution": "LOCAL_READBACK_VERIFIED"
        if receipt.adapter_id == "LOCAL_SIMULATION_ONLY"
        else "EXTERNAL_READBACK_VERIFIED",
        "external_action_id": receipt.external_action_id,
        "readback": receipt.model_dump(mode="json"),
    })
    return read(principal, control_id)
