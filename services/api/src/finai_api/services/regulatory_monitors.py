"""Regulatory schedules share scoped platform requests, events and source storage."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb
from pydantic import ConfigDict, Field
from temporalio import activity

from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services import regulatory_sources as sources
from finai_api.services import report_workflows as records
from finai_api.services.workspace import WorkspaceError

VERSION = "regulatory-source-monitor/1"


class MonitorRequest(sources.Capture):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    name: str = Field(min_length=3, max_length=200)
    cadence_hours: int = Field(ge=1, le=720)
    rationale: str = Field(min_length=10, max_length=2000)


def retain(principal: Principal, request: MonitorRequest) -> str:
    require_permission(principal, "read")
    require_permission(principal, "ingest")
    scope = principal.scope.model_dump(mode="json")
    identity = (
        "rgm_"
        + sha256(
            json.dumps(
                [scope, principal.actor_id, str(request.request_id)], sort_keys=True
            ).encode()
        ).hexdigest()
    )
    payload = request.model_dump(mode="json")
    payload["definition"] = {
        "version": VERSION,
        "parser": "matsne-act/1",
        "automatic_legal_activation": False,
        "source_authority": "OFFICIAL_PUBLISHER",
        "source_identity": "GE:MATSNE:" + request.document_number,
        "discovery_strategy": "EXACT_PUBLICATION_AND_ADVERTISED_PUBLICATION_NUMBERS",
        "expected_publication_latency": "UNKNOWN",
        "freshness_grace_hours": 1,
    }
    with records.scope_connection(principal) as conn:
        records.set_scope(conn, principal)
        conn.execute(
            "INSERT INTO workflow_requests "
            "(tenant_id,workflow_id,exact_scope,actor_id,definition_version,payload) "
            "VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (
                principal.scope.tenant_id,
                identity,
                Jsonb(scope),
                principal.actor_id,
                VERSION,
                Jsonb(payload),
            ),
        )
        previous = conn.execute(
            "SELECT payload FROM workflow_requests WHERE tenant_id=%s "
            "AND exact_scope=%s AND workflow_id=%s",
            (principal.scope.tenant_id, Jsonb(scope), identity),
        ).fetchone()
        if not previous or {
            k: v for k, v in previous[0].items() if k != "definition"
        } != request.model_dump(mode="json"):
            raise WorkspaceError(
                409, "Monitor request identity has different retained configuration"
            )
    return identity


def read(principal: Principal, identity: str) -> dict[str, Any]:
    require_permission(principal, "read")
    result = records.read(principal, identity)
    if result["definition"].get("version") != VERSION:
        raise WorkspaceError(404, "Regulatory monitor unavailable")
    return result


def listing(principal: Principal) -> list[dict[str, Any]]:
    require_permission(principal, "read")
    with records.scope_connection(principal) as conn:
        scope = records.set_scope(conn, principal)
        rows = conn.execute(
            "SELECT workflow_id,payload,created_at FROM workflow_requests "
            "WHERE tenant_id=%s AND exact_scope=%s AND definition_version=%s "
            "ORDER BY created_at DESC LIMIT 100",
            (principal.scope.tenant_id, Jsonb(scope), VERSION),
        ).fetchall()
    return [
        {"workflow_id": row[0], "request": row[1], "created_at": row[2].isoformat()} for row in rows
    ]


@activity.defn(name="regulatory_source_check")
def check(context: dict[str, Any]) -> dict[str, Any]:
    principal = records.current_principal(context["actor_id"], context["scope"])
    require_permission(principal, "read")
    require_permission(principal, "ingest")
    identity, check_id = context["workflow_id"], context["check_id"]
    record = read(principal, identity)
    completed_key = "source-check:" + check_id
    previous = next((e for e in record["events"] if e["event_id"] == completed_key), None)
    if previous:
        return {"event_id": completed_key, "state": previous["state"]}
    attempt_key = completed_key + f":attempt:{activity.info().attempt}"
    records.event(
        principal, identity, attempt_key + ":started", {"state": "CHECKING", "check_id": check_id}
    )
    try:
        result = sources.capture(
            principal,
            sources.Capture(
                document_number=record["request"]["document_number"],
                publication=record["request"]["publication"],
            ),
        )
        observation = result["observation"]
        signature = {
            "text_sha256": observation["text_sha256"],
            "advertised_publications": observation["advertised_publications"],
            "completeness": observation["completeness"],
        }
        successes = [e for e in record["events"] if "signature" in e]
        state = (
            "INITIAL_CAPTURE"
            if not successes
            else "UNCHANGED"
            if successes[-1]["signature"] == signature
            else "SOURCE_CHANGED"
        )
        records.event(
            principal,
            identity,
            completed_key,
            {
                "state": state,
                "check_id": check_id,
                "checked_at": datetime.now(UTC).isoformat(),
                "document": result["document"],
                "source_url": result["source_url"],
                "signature": signature,
                "parser_version": observation["parser_version"],
                "previous_check": successes[-1]["event_id"] if successes else None,
                "legal_change_verified": False,
                "accounting_effects": False,
            },
        )
        return {"event_id": completed_key, "state": state}
    except Exception:
        records.event(
            principal,
            identity,
            attempt_key + ":failed",
            {
                "state": "CHECK_FAILED",
                "check_id": check_id,
                "reason": "Official source check failed; previous evidence remains retained",
            },
        )
        raise
