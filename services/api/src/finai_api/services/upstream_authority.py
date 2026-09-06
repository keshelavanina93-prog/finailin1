"""Current-use withdrawal checks across exact retained lineage, including indirect inputs."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg.errors import RaiseException

from finai_api.services.effective_version import retained_with_effective_version
from finai_api.services.workspace import WorkspaceError


def upstream_authority(
    cursor: Any, tenant: UUID, consumer: UUID, *, check_certification: bool = True
) -> list[dict[str, Any]]:
    pending = [consumer]
    seen = {consumer}
    proof = []
    edges = 0
    now = datetime.now(UTC)
    while pending:
        source = pending.pop()
        dependencies = cursor.execute(
            "SELECT DISTINCT target_resource_id,target_version_id FROM resource_dependencies "
            "WHERE tenant_id=%s AND version_id=%s LIMIT 5001",
            (tenant, source),
        ).fetchall()
        edges += len(dependencies)
        if edges > 5000:
            raise WorkspaceError(409, "Current-use lineage exceeds the bounded edge limit")
        for dependency in dependencies:
            version = dependency["target_version_id"]
            if version in seen:
                continue
            seen.add(version)
            if len(seen) > 1000:
                raise WorkspaceError(409, "Current-use lineage exceeds the bounded resource limit")
            row = retained_with_effective_version(
                cursor, tenant, dependency["target_resource_id"], version, now
            )
            if (
                row is None
                or row["effective_version_id"] != version
                or row["authority_state"] != "APPROVED"
                or (
                    row["valid_from"] > now
                    or (row["valid_to"] is not None and row["valid_to"] <= now)
                )
            ):
                raise WorkspaceError(409, "Upstream dependency is unavailable for current use")
            event = cursor.execute(
                "SELECT event_id,payload,certification_proof_hash FROM resource_lifecycle_events "
                "WHERE tenant_id=%s "
                "AND version_id=%s ORDER BY recorded_at DESC,event_id DESC LIMIT 1",
                (tenant, version),
            ).fetchone()
            if event and (
                event["payload"]["target_state"] in ("REVOKED", "SUPERSEDED")
                or event["payload"]["availability_state"] != "AVAILABLE"
            ):
                raise WorkspaceError(
                    409, "Upstream dependency authority or availability was withdrawn"
                )
            if check_certification and event and event["payload"]["target_state"] == "CERTIFIED":
                payload = event["payload"]
                try:
                    policy = payload["certification_contract"]
                    checked = cursor.execute(
                        "SELECT g8_check_certification_receipt(%s,%s,%s,%s,%s,%s) AS proof_hash",
                        (
                            tenant,
                            payload["certification_receipt_id"],
                            row["resource_id"],
                            version,
                            policy["resource_id"],
                            policy["version_id"],
                        ),
                    ).fetchone()
                    if (
                        checked is None
                        or checked["proof_hash"] != event["certification_proof_hash"]
                    ):
                        raise WorkspaceError(409, "Upstream certification proof does not match")
                except (KeyError, TypeError, RaiseException) as exc:
                    raise WorkspaceError(409, "Upstream certification is unavailable") from exc
            proof.append(
                {
                    "resource_id": str(row["resource_id"]),
                    "version_id": str(version),
                    "content_hash": row["content_hash"],
                    "access_entity": row["access_entity"],
                    "event_id": str(event["event_id"]) if event else None,
                }
            )
            pending.append(version)
    return sorted(proof, key=lambda item: item["version_id"])
