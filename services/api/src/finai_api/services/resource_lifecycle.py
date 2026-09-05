"""Independent material authority; registry approval never grants consumption authority."""

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from finai_api.domain.authority import canonical_sha256
from finai_api.domain.resource_lifecycle import (
    ConsumptionRequest,
    LifecycleRequest,
    LifecycleReview,
    VersionReference,
)
from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services.resources import resource_connection
from finai_api.services.workspace import WorkspaceError

ORDER = [
    "OBSERVED",
    "PARSED",
    "MAPPED_CANDIDATE",
    "VALIDATED",
    "RECONCILED",
    "APPROVED",
    "AUTHORITATIVE",
]


def _lock(conn: Any, p: Principal) -> None:
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f"canonical:{p.scope.tenant_id}",)
    )


def _version(c: Any, p: Principal, ref: VersionReference, current: bool = True) -> dict[str, Any]:
    row = c.execute(
        "SELECT v.*,h.version_id AS head FROM resource_versions v JOIN "
        "resource_heads h USING(tenant_id,resource_id) WHERE v.tenant_id=%s AND "
        "v.resource_id=%s AND v.version_id=%s",
        (p.scope.tenant_id, ref.resource_id, ref.version_id),
    ).fetchone()
    if row is None:
        raise WorkspaceError(404, "Version unavailable in authorized context")
    now = datetime.now(UTC)
    if current and (
        row["head"] != ref.version_id
        or row["authority_state"] != "APPROVED"
        or row["valid_from"] > now
        or (row["valid_to"] is not None and row["valid_to"] <= now)
    ):
        raise WorkspaceError(409, "Version is not eligible for current use")
    return dict(row)


def _latest(c: Any, p: Principal, version: UUID) -> dict[str, Any] | None:
    row = c.execute(
        "SELECT * FROM resource_lifecycle_events WHERE tenant_id=%s AND "
        "version_id=%s ORDER BY recorded_at DESC,event_id DESC LIMIT 1",
        (p.scope.tenant_id, version),
    ).fetchone()
    return dict(row) if row is not None else None


def _validate(c: Any, p: Principal, r: LifecycleRequest) -> dict[str, Any]:
    version = _version(c, p, r.subject)
    event = _latest(c, p, r.subject.version_id)
    if (event["event_id"] if event else None) != r.expected_event_id:
        raise WorkspaceError(409, "Lifecycle changed; submit a new reviewed request")
    prior = event["payload"]["target_state"] if event else None
    expected = (
        ORDER[0]
        if prior is None
        else (ORDER[ORDER.index(prior) + 1] if prior in ORDER[:-1] else None)
    )
    amendment = (
        event is not None
        and prior in ORDER
        and r.target_state == prior
        and any(
            getattr(r, field) != event["payload"][field]
            for field in ("epistemic_state", "business_state", "availability_state")
        )
    )
    if (
        not amendment
        and r.target_state != expected
        and not (prior in ORDER and r.target_state in ("SUPERSEDED", "REVOKED"))
    ):
        raise WorkspaceError(
            409, "Unsupported lifecycle transition; certification requires a certification contract"
        )
    return version


def request_transition(p: Principal, r: LifecycleRequest) -> dict[str, Any]:
    require_permission(p, "ontology_propose")
    with resource_connection(p) as conn, conn.cursor(row_factory=dict_row) as c:
        _lock(conn, p)
        old = c.execute(
            "SELECT * FROM resource_lifecycle_requests WHERE tenant_id=%s AND request_id=%s",
            (p.scope.tenant_id, r.request_id),
        ).fetchone()
        if old:
            if old["request_hash"] != canonical_sha256(r):
                raise WorkspaceError(409, "Request identity already used")
            return dict(old)
        v = _validate(c, p, r)
        return cast(
            dict[str, Any],
            c.execute(
                "INSERT INTO "
                "resource_lifecycle_requests(tenant_id,request_id,resource_id,version_id,"
                "access_entity,submitted_by,request_hash,payload) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                (
                    p.scope.tenant_id,
                    r.request_id,
                    r.subject.resource_id,
                    r.subject.version_id,
                    v["access_entity"],
                    p.actor_id,
                    canonical_sha256(r),
                    Jsonb(r.model_dump(mode="json")),
                ),
            ).fetchone(),
        )


def review_transition(p: Principal, request_id: UUID, r: LifecycleReview) -> dict[str, Any]:
    require_permission(p, "ontology_review")
    with resource_connection(p) as conn, conn.cursor(row_factory=dict_row) as c:
        _lock(conn, p)
        row = c.execute(
            "SELECT * FROM resource_lifecycle_requests WHERE tenant_id=%s AND request_id=%s",
            (p.scope.tenant_id, request_id),
        ).fetchone()
        if row is None:
            raise WorkspaceError(404, "Lifecycle request unavailable")
        if row["submitted_by"] == p.actor_id:
            raise WorkspaceError(409, "Independent lifecycle reviewer required")
        old = c.execute(
            "SELECT * FROM resource_lifecycle_decisions WHERE tenant_id=%s AND request_id=%s",
            (p.scope.tenant_id, request_id),
        ).fetchone()
        if old:
            if (
                old["reviewed_by"] != p.actor_id
                or old["decision"] != r.decision
                or old["reason"] != r.reason
            ):
                raise WorkspaceError(409, "Lifecycle request already reviewed")
            return dict(old)
        request = LifecycleRequest.model_validate(row["payload"])
        if r.decision == "APPROVED":
            _validate(c, p, request)
            if request.target_state == "AUTHORITATIVE":
                require_permission(p, "ontology_admin")
        decision = c.execute(
            "INSERT INTO "
            "resource_lifecycle_decisions(tenant_id,request_id,access_entity,"
            "reviewed_by,decision,reason) "
            "VALUES(%s,%s,%s,%s,%s,%s) RETURNING *",
            (p.scope.tenant_id, request_id, row["access_entity"], p.actor_id, r.decision, r.reason),
        ).fetchone()
        if r.decision == "APPROVED":
            c.execute(
                "INSERT INTO "
                "resource_lifecycle_events(tenant_id,event_id,request_id,resource_id,"
                "version_id,access_entity,payload) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (
                    p.scope.tenant_id,
                    uuid4(),
                    request_id,
                    row["resource_id"],
                    row["version_id"],
                    row["access_entity"],
                    Jsonb(row["payload"]),
                ),
            )
        assert decision is not None
        return dict(decision)


def history(
    p: Principal, ref: VersionReference, known_at: datetime | None = None
) -> dict[str, Any]:
    require_permission(p, "ontology_read")
    if known_at is not None and known_at.tzinfo is None:
        raise WorkspaceError(422, "Historical knowledge time must include a timezone")
    known_at = known_at or datetime.now(UTC)
    with resource_connection(p) as conn, conn.cursor(row_factory=dict_row) as c:
        _version(c, p, ref, False)
        rows = c.execute(
            "SELECT * FROM resource_lifecycle_events WHERE tenant_id=%s AND "
            "version_id=%s AND recorded_at<=%s ORDER BY recorded_at,event_id",
            (p.scope.tenant_id, ref.version_id, known_at),
        ).fetchall()
        return {
            "subject": ref.model_dump(mode="json"),
            "purpose": "HISTORICAL_LIFECYCLE",
            "known_at": known_at,
            "state": rows[-1]["payload"] if rows else None,
            "events": [dict(r) for r in rows],
        }


def consume(p: Principal, r: ConsumptionRequest) -> dict[str, Any]:
    require_permission(p, "ontology_read")
    if r.minimum_state not in ORDER:
        raise WorkspaceError(422, "Minimum state must be a supported progressive authority state")
    with resource_connection(p) as conn, conn.cursor(row_factory=dict_row) as c:
        _lock(conn, p)
        consumer = _version(c, p, r.consumer)
        consumer_event = _latest(c, p, r.consumer.version_id)
        if consumer_event and consumer_event["payload"]["target_state"] in (
            "REVOKED",
            "SUPERSEDED",
        ):
            raise WorkspaceError(409, "Consumer authority has been withdrawn")
        required = consumer["attributes"].get("minimum_authority_state")
        if required not in ORDER:
            raise WorkspaceError(409, "Consumer lacks a supported minimum authority contract")
        minimum = ORDER[max(ORDER.index(required), ORDER.index(r.minimum_state))]
        pins = c.execute(
            "SELECT target_resource_id,target_version_id FROM resource_dependencies "
            "WHERE tenant_id=%s AND version_id=%s",
            (p.scope.tenant_id, r.consumer.version_id),
        ).fetchall()
        expected = {(x["target_resource_id"], x["target_version_id"]) for x in pins}
        supplied = {(x.resource_id, x.version_id) for x in r.inputs}
        if len(supplied) != len(r.inputs) or supplied != expected:
            raise WorkspaceError(
                409, "Inputs must exactly match all recorded direct dependency pins"
            )
        values = []
        for ref in r.inputs:
            version = _version(c, p, ref)
            event = _latest(c, p, ref.version_id)
            state = event["payload"]["target_state"] if event else None
            if (
                event is None
                or state not in ORDER
                or ORDER.index(state) < ORDER.index(minimum)
                or event["payload"]["availability_state"] != "AVAILABLE"
            ):
                raise WorkspaceError(409, "Input does not meet required authority and availability")
            values.append(
                {
                    "subject": ref.model_dump(mode="json"),
                    "event_id": str(event["event_id"]),
                    "authority_state": state,
                    "attributes": version["attributes"],
                    "access_entity": version["access_entity"],
                    "epistemic_state": event["payload"]["epistemic_state"],
                    "business_state": event["payload"]["business_state"],
                    "availability_state": event["payload"]["availability_state"],
                }
            )
        return {
            "purpose": "GUARDED_CURRENT_CONSUMPTION",
            "consumer": r.consumer.model_dump(mode="json"),
            "minimum_state": minimum,
            "access_entity": consumer["access_entity"],
            "checked_at": datetime.now(UTC).isoformat(),
            "inputs": values,
        }
