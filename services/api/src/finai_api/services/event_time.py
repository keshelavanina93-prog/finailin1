"""Retained event-time observations; no accounting or material authority is inferred."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from finai_api.domain.authority import canonical_sha256
from finai_api.domain.review import Principal
from finai_api.domain.source_event import SourceEvent
from finai_api.security import require_permission
from finai_api.services.resource_lifecycle import _version
from finai_api.services.resources import resource_connection
from finai_api.services.workspace import WorkspaceError


def retain_event(p: Principal, request: SourceEvent) -> dict[str, Any]:
    require_permission(p, "ingest")
    with resource_connection(p) as conn, conn.cursor(row_factory=dict_row) as cursor:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (f"canonical:{p.scope.tenant_id}",),
        )
        request_hash = canonical_sha256(request)
        existing = cursor.execute(
            "SELECT * FROM retained_source_events WHERE tenant_id=%s "
            "AND stream_id=%s AND event_id=%s",
            (p.scope.tenant_id, request.stream.resource_id, request.event_id),
        ).fetchone()
        if existing:
            if existing["request_hash"] != request_hash:
                raise WorkspaceError(
                    409, "Source event identity already has different retained content"
                )
            return _observation(existing)
        stream = _version(cursor, p, request.stream)
        policy = stream["attributes"]
        if stream["access_entity"] == "__PLATFORM__":
            raise WorkspaceError(403, "Source observations require an enterprise policy boundary")
        lateness = policy.get("allowed_lateness_seconds")
        future = policy.get("allowed_future_seconds")
        if (
            policy.get("event_time_policy_version") != "event-time/1"
            or policy.get("late_policy") != "RETAIN_ONLY"
            or type(lateness) is not int
            or not 0 <= lateness <= 31536000
            or type(future) is not int
            or not 0 <= future <= 86400
        ):
            raise WorkspaceError(409, "An accepted bounded event-time policy is required")
        if request.event_time > datetime.now(UTC) + timedelta(seconds=future):
            raise WorkspaceError(422, "Source event exceeds its accepted future-time allowance")
        prior = cursor.execute(
            "SELECT max(event_time) AS high FROM retained_source_events "
            "WHERE tenant_id=%s AND stream_id=%s AND stream_version_id=%s",
            (p.scope.tenant_id, request.stream.resource_id, request.stream.version_id),
        ).fetchone()
        high = prior["high"] if prior else None
        watermark = high - timedelta(seconds=lateness) if high else None
        admission = "RETAINED_LATE" if watermark and request.event_time < watermark else "IN_WINDOW"
        row = cursor.execute(
            "INSERT INTO retained_source_events "
            "(tenant_id,stream_id,stream_version_id,access_entity,"
            "event_id,partition_key,event_time,request_hash,admission,watermark,payload,actor_id) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            (
                p.scope.tenant_id,
                request.stream.resource_id,
                request.stream.version_id,
                stream["access_entity"],
                request.event_id,
                request.partition_key,
                request.event_time,
                request_hash,
                admission,
                watermark,
                Jsonb(request.payload),
                p.actor_id,
            ),
        ).fetchone()
        assert row is not None
        return _observation(row)


def _observation(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "authority_state": "OBSERVED",
        "event_id": row["event_id"],
        "stream_id": str(row["stream_id"]),
        "stream_version_id": str(row["stream_version_id"]),
        "partition_key": row["partition_key"],
        "event_time": row["event_time"],
        "processing_time": row["recorded_at"],
        "arrival_sequence": row["arrival_sequence"],
        "admission": row["admission"],
        "watermark": row["watermark"],
        "request_hash": row["request_hash"],
        "access_entity": row["access_entity"],
        "payload": row["payload"],
    }


def replay(
    p: Principal, stream_id: UUID, known_at: datetime, include_late: bool = False
) -> dict[str, Any]:
    require_permission(p, "ontology_read")
    if known_at.tzinfo is None:
        raise WorkspaceError(422, "Replay knowledge time must include a timezone")
    with resource_connection(p) as conn, conn.cursor(row_factory=dict_row) as cursor:
        # Backfill is a separate observation view; it never changes retained admission decisions.
        rows = cursor.execute(
            "SELECT * FROM retained_source_events WHERE tenant_id=%s AND stream_id=%s "
            "AND recorded_at<=%s ORDER BY arrival_sequence LIMIT 10001",
            (p.scope.tenant_id, stream_id, known_at),
        ).fetchall()
        if not rows:
            raise WorkspaceError(404, "Retained stream unavailable in authorized context")
        if len(rows) > 10000:
            raise WorkspaceError(409, "Replay exceeds the bounded observation limit")
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            if row["admission"] == "RETAINED_LATE" and not include_late:
                continue
            previous = latest.get(row["partition_key"])
            if previous is None or (row["event_time"], row["event_id"]) > (
                previous["event_time"],
                previous["event_id"],
            ):
                latest[row["partition_key"]] = row
        return {
            "purpose": "BACKFILL_OBSERVATION" if include_late else "AS_RECORDED_OBSERVATION",
            "authority_state": "OBSERVED",
            "current_use_authorized": False,
            "known_at": known_at,
            "stream_id": str(stream_id),
            "event_count": len(rows),
            "late_event_count": sum(row["admission"] == "RETAINED_LATE" for row in rows),
            "ordering": "event_time,event_id",
            "admission_order": "arrival_sequence",
            "projection": [_observation(latest[key]) for key in sorted(latest)],
        }
