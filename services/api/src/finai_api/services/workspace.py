import csv
import io
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from finai_api.domain.authority import canonical_sha256
from finai_api.domain.ingest import IngestReceipt
from finai_api.domain.review import (
    IntakeItem,
    ObjectDetail,
    Principal,
    ReceiptDetail,
    ReviewDecision,
    ReviewRequest,
    WorkspaceObject,
    WorkspaceSummary,
    approval_blockers,
    workspace_object,
)
from finai_api.storage import connection


class WorkspaceError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status, self.detail = status, detail


def _scope(principal: Principal) -> Jsonb:
    return Jsonb(principal.scope.model_dump(mode="json"))


def _decision(row: dict[str, Any]) -> ReviewDecision:
    return ReviewDecision.model_validate(row)


def _run(conn: psycopg.Connection[Any], principal: Principal, receipt_id: str) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            "SELECT * FROM hydration_runs WHERE tenant_id=%s AND receipt_id=%s AND exact_scope=%s",
            (principal.scope.tenant_id, receipt_id, _scope(principal)),
        ).fetchone()
    if row is None:
        raise WorkspaceError(404, "Construction not found in authorized scope")
    return row


def _head(conn: psycopg.Connection[Any], principal: Principal, source_class: str) -> str | None:
    row = conn.execute(
        "SELECT receipt_id FROM workspace_heads WHERE tenant_id=%s AND scope_hash=%s "
        "AND source_class=%s AND exact_scope=%s",
        (
            principal.scope.tenant_id,
            canonical_sha256(principal.scope),
            source_class,
            _scope(principal),
        ),
    ).fetchone()
    return str(row[0]) if row else None


def detail(principal: Principal, receipt_id: str) -> ReceiptDetail:
    with connection(principal.scope) as conn:
        run = _run(conn, principal, receipt_id)
        receipt = IngestReceipt.model_validate(run["receipt"])
        current_head = _head(conn, principal, receipt.source_class)
        previous = (
            IngestReceipt.model_validate(_run(conn, principal, current_head)["receipt"])
            if current_head
            else None
        )

        def indexed(value: IngestReceipt | None) -> dict[str, dict[str, str]]:
            return (
                {
                    f"{item.object_type}:{item.values.get('account_code', str(item.source_row))}": item.values
                    for item in value.candidates
                }
                if value
                else {}
            )

        before, after = indexed(previous), indexed(receipt)
        shared = before.keys() & after.keys()
        impact = {
            "added": len(after.keys() - before.keys()),
            "removed": len(before.keys() - after.keys()),
            "changed": sum(before[key] != after[key] for key in shared),
            "unchanged": sum(before[key] == after[key] for key in shared),
        }
        with conn.cursor(row_factory=dict_row) as cursor:
            decision = cursor.execute(
                "SELECT * FROM construction_decisions WHERE tenant_id=%s AND receipt_id=%s "
                "AND exact_scope=%s",
                (principal.scope.tenant_id, receipt_id, _scope(principal)),
            ).fetchone()
        return ReceiptDetail(
            receipt=receipt,
            filename=run["request"]["filename"],
            submitted_by=run["submitted_by"],
            ingested_at=run["ingested_at"],
            decision=_decision(decision) if decision else None,
            current_head=current_head,
            impact=impact,
            approval_blockers=approval_blockers(receipt, run["submitted_by"], principal),
        )


def list_intake(principal: Principal, offset: int, state: str | None) -> list[IntakeItem]:
    with connection(principal.scope) as conn, conn.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            "SELECT r.receipt_id, r.request->>'filename' AS filename, "
            "r.receipt->>'source_class' AS source_class, r.source_sha256, r.submitted_by, "
            "r.ingested_at, jsonb_array_length(r.receipt->'candidates') AS candidate_count, "
            "jsonb_array_length(r.receipt->'rejects') AS reject_count, "
            "r.receipt->'reconciliation'->>'status' AS reconciliation_status, "
            "coalesce(d.decision, 'PENDING') AS review_state, (h.receipt_id IS NOT NULL) AS is_current "
            "FROM hydration_runs r LEFT JOIN construction_decisions d "
            "ON r.tenant_id=d.tenant_id AND r.receipt_id=d.receipt_id "
            "LEFT JOIN workspace_heads h ON r.tenant_id=h.tenant_id AND r.receipt_id=h.receipt_id "
            "WHERE r.tenant_id=%s AND r.exact_scope=%s "
            "AND (%s::text IS NULL OR coalesce(d.decision,'PENDING')=%s) "
            "ORDER BY r.ingested_at DESC, r.receipt_id LIMIT 50 OFFSET %s",
            (principal.scope.tenant_id, _scope(principal), state, state, offset),
        ).fetchall()
        return [IntakeItem.model_validate(row) for row in rows]


def decide(principal: Principal, receipt_id: str, request: ReviewRequest) -> ReviewDecision:
    with connection(principal.scope) as conn:
        # One writer per exact scope; serializes competing approvals without mutating source rows.
        lock_id = f"{principal.scope.tenant_id}:{canonical_sha256(principal.scope)}"
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (lock_id,))
        run = _run(conn, principal, receipt_id)
        receipt = IngestReceipt.model_validate(run["receipt"])
        with conn.cursor(row_factory=dict_row) as cursor:
            existing = cursor.execute(
                "SELECT * FROM construction_decisions WHERE tenant_id=%s AND receipt_id=%s",
                (principal.scope.tenant_id, receipt_id),
            ).fetchone()
            if existing:
                if (
                    str(existing["decision_id"]) == str(request.idempotency_key)
                    and existing["actor_id"] == principal.actor_id
                    and existing["decision"] == request.decision
                    and existing["reason"] == request.reason
                    and (
                        request.decision == "REJECTED"
                        or existing["previous_head"] == request.expected_head
                    )
                ):
                    return _decision(existing)
                raise WorkspaceError(409, "This construction already has an immutable decision")
            if "review" not in principal.permissions:
                raise WorkspaceError(403, "Review permission required")
            if not run["submitted_by"] or run["submitted_by"] == principal.actor_id:
                raise WorkspaceError(
                    403, "An identified submitter and a separate reviewer are required"
                )
            head = _head(conn, principal, receipt.source_class)
            if request.decision == "APPROVED":
                blockers = approval_blockers(receipt, run["submitted_by"], principal)
                if blockers:
                    raise WorkspaceError(409, " ".join(blockers))
                if head != request.expected_head:
                    raise WorkspaceError(
                        409, "Accepted version changed. Refresh and review the new impact."
                    )
            decision = cursor.execute(
                "INSERT INTO construction_decisions "
                "(tenant_id, receipt_id, decision_id, exact_scope, decision, actor_id, reason, previous_head) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                (
                    principal.scope.tenant_id,
                    receipt_id,
                    request.idempotency_key,
                    _scope(principal),
                    request.decision,
                    principal.actor_id,
                    request.reason,
                    head,
                ),
            ).fetchone()
        if request.decision == "APPROVED":
            rows = []
            for index, candidate in enumerate(receipt.candidates):
                obj = workspace_object(receipt_id, index, candidate)
                rows.append(
                    (
                        principal.scope.tenant_id,
                        obj.object_id,
                        receipt_id,
                        _scope(principal),
                        index,
                        candidate.object_type,
                        Jsonb(obj.model_dump(mode="json")),
                    )
                )
            with conn.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO workspace_objects (tenant_id, object_id, receipt_id, exact_scope, "
                    "object_index, object_type, object_payload) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    rows,
                )
            conn.execute(
                "INSERT INTO workspace_heads (tenant_id, scope_hash, source_class, exact_scope, receipt_id) "
                "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (tenant_id, scope_hash, source_class) "
                "DO UPDATE SET receipt_id=EXCLUDED.receipt_id, updated_at=clock_timestamp()",
                (
                    principal.scope.tenant_id,
                    canonical_sha256(principal.scope),
                    receipt.source_class,
                    _scope(principal),
                    receipt_id,
                ),
            )
        if decision is None:
            raise RuntimeError("Decision could not be retained")
        return _decision(decision)


def objects(
    principal: Principal, offset: int, object_type: str | None, search: str, receipt_id: str | None
) -> list[WorkspaceObject]:
    with connection(principal.scope) as conn:
        rows = conn.execute(
            "SELECT o.object_payload FROM workspace_objects o "
            "LEFT JOIN workspace_heads h ON o.tenant_id=h.tenant_id AND o.receipt_id=h.receipt_id "
            "WHERE o.tenant_id=%s AND o.exact_scope=%s "
            "AND ((%s::text IS NULL AND h.receipt_id IS NOT NULL) OR o.receipt_id=%s) "
            "AND (%s::text IS NULL OR o.object_type=%s) "
            "AND position(lower(%s) in lower((o.object_payload->'values')::text))>0 "
            "ORDER BY o.receipt_id, o.object_index LIMIT 100 OFFSET %s",
            (
                principal.scope.tenant_id,
                _scope(principal),
                receipt_id,
                receipt_id,
                object_type,
                object_type,
                search,
                offset,
            ),
        ).fetchall()
        return [WorkspaceObject.model_validate(row[0]) for row in rows]


def object_detail(principal: Principal, object_id: str) -> ObjectDetail:
    with connection(principal.scope) as conn:
        row = conn.execute(
            "SELECT object_payload FROM workspace_objects WHERE tenant_id=%s AND object_id=%s "
            "AND exact_scope=%s",
            (principal.scope.tenant_id, object_id, _scope(principal)),
        ).fetchone()
        if row is None:
            raise WorkspaceError(404, "Object not found in authorized scope")
        obj = WorkspaceObject.model_validate(row[0])
        run = _run(conn, principal, obj.receipt_id)
        reader = csv.DictReader(
            io.StringIO(bytes(run["source_bytes"]).decode("utf-8").removeprefix("\ufeff"))
        )
        source_row = next(
            (values for index, values in enumerate(reader, 2) if index == obj.source_row), {}
        )
        with conn.cursor(row_factory=dict_row) as cursor:
            decision = cursor.execute(
                "SELECT * FROM construction_decisions WHERE tenant_id=%s AND receipt_id=%s",
                (principal.scope.tenant_id, obj.receipt_id),
            ).fetchone()
        if decision is None:
            raise RuntimeError("Object is missing its approval")
        return ObjectDetail(
            object=obj,
            scope=principal.scope,
            source_sha256=run["source_sha256"],
            source_row_values=source_row,
            decision=_decision(decision),
            is_current=_head(conn, principal, run["receipt"]["source_class"]) == obj.receipt_id,
        )


def summary(principal: Principal) -> WorkspaceSummary:
    with connection(principal.scope) as conn:
        counts = conn.execute(
            "SELECT coalesce(d.decision,'PENDING'), count(*) FROM hydration_runs r "
            "LEFT JOIN construction_decisions d ON r.tenant_id=d.tenant_id AND r.receipt_id=d.receipt_id "
            "WHERE r.tenant_id=%s AND r.exact_scope=%s GROUP BY coalesce(d.decision,'PENDING')",
            (principal.scope.tenant_id, _scope(principal)),
        ).fetchall()
        heads = conn.execute(
            "SELECT source_class, receipt_id FROM workspace_heads WHERE tenant_id=%s AND exact_scope=%s",
            (principal.scope.tenant_id, _scope(principal)),
        ).fetchall()
        state_counts = dict(counts)
        return WorkspaceSummary(
            scope=principal.scope,
            pending_count=state_counts.get("PENDING", 0),
            approved_count=state_counts.get("APPROVED", 0),
            rejected_count=state_counts.get("REJECTED", 0),
            active_versions=[
                {"source_class": str(row[0]), "receipt_id": str(row[1])} for row in heads
            ],
        )


def source_bytes(principal: Principal, receipt_id: str) -> bytes:
    with connection(principal.scope) as conn:
        return bytes(_run(conn, principal, receipt_id)["source_bytes"])
