"""Independent material authority; registry approval never grants consumption authority."""

import json
from datetime import UTC, datetime
from hashlib import sha256
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
from finai_api.services.effective_version import retained_with_effective_version
from finai_api.services.resources import resource_connection
from finai_api.services.upstream_authority import upstream_authority
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
    now = datetime.now(UTC)
    row = retained_with_effective_version(
        c, p.scope.tenant_id, ref.resource_id, ref.version_id, now
    )
    if row is None:
        raise WorkspaceError(404, "Version unavailable in authorized context")
    if current and (
        row["effective_version_id"] != ref.version_id
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
        and prior in [*ORDER, "CERTIFIED"]
        and r.target_state == prior
        and any(
            getattr(r, field) != event["payload"][field]
            for field in ("epistemic_state", "business_state", "availability_state")
        )
    )
    if (
        not amendment
        and r.target_state != expected
        and not (prior == "AUTHORITATIVE" and r.target_state == "CERTIFIED")
        and not (prior in [*ORDER, "CERTIFIED"] and r.target_state in ("SUPERSEDED", "REVOKED"))
    ):
        raise WorkspaceError(
            409, "Unsupported lifecycle transition; certification requires a certification contract"
        )
    if prior == "CERTIFIED" or r.target_state == "CERTIFIED":
        from finai_api.services.certification import _envelope, receipt_for_current_use

        if r.certification_receipt_id is None or r.certification_contract is None:
            raise WorkspaceError(
                409, "Certified lifecycle requires exact receipt and contract pins"
            )
        if (
            prior == "CERTIFIED"
            and event is not None
            and (
                event["payload"].get("certification_receipt_id") != str(r.certification_receipt_id)
                or event["payload"].get("certification_contract")
                != r.certification_contract.model_dump(mode="json")
            )
        ):
            raise WorkspaceError(
                409, "Certified amendment or withdrawal must retain its original binding"
            )
        if r.target_state in ("SUPERSEDED", "REVOKED"):
            row = c.execute(
                "SELECT * FROM certification_receipts WHERE tenant_id=%s AND receipt_id=%s",
                (p.scope.tenant_id, r.certification_receipt_id),
            ).fetchone()
            if row is None:
                raise WorkspaceError(409, "Original certification evidence unavailable")
            receipt = _envelope(row)
        else:
            receipt = receipt_for_current_use(
                c,
                p,
                r.certification_receipt_id,
                r.subject,
                r.certification_contract,
                allow_subject_unavailable=prior == "CERTIFIED" and amendment,
            )
        version["certification_proof_hash"] = receipt["proof_hash"]
    elif r.certification_receipt_id is not None or r.certification_contract is not None:
        raise WorkspaceError(409, "Certification binding is only valid for a certified lifecycle")
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
                "access_entity,submitted_by,request_hash,payload,certification_proof_hash) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                (
                    p.scope.tenant_id,
                    r.request_id,
                    r.subject.resource_id,
                    r.subject.version_id,
                    v["access_entity"],
                    p.actor_id,
                    canonical_sha256(r),
                    Jsonb(r.model_dump(mode="json")),
                    v.get("certification_proof_hash"),
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
            validated = _validate(c, p, request)
            if validated.get("certification_proof_hash") != row.get("certification_proof_hash"):
                raise WorkspaceError(409, "Certification proof changed since lifecycle request")
            if request.target_state in ("AUTHORITATIVE", "CERTIFIED"):
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
                "version_id,access_entity,payload,certification_proof_hash) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    p.scope.tenant_id,
                    uuid4(),
                    request_id,
                    row["resource_id"],
                    row["version_id"],
                    row["access_entity"],
                    Jsonb(row["payload"]),
                    row.get("certification_proof_hash"),
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
    from finai_api.services.certification_consumption import certified_event, requirements_for_use

    require_permission(p, "ontology_read")
    progression = [*ORDER, "CERTIFIED"]
    if r.minimum_state not in progression:
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
        if required not in progression:
            raise WorkspaceError(409, "Consumer lacks a supported minimum authority contract")
        minimum = progression[max(progression.index(required), progression.index(r.minimum_state))]
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
        requirements, controls = (
            requirements_for_use(c, p, consumer, r.inputs)
            if minimum == "CERTIFIED"
            else ({}, set())
        )
        consumer_certification = None
        if consumer_event and consumer_event["payload"]["target_state"] == "CERTIFIED":
            consumer_certification = certified_event(c, p, r.consumer, consumer_event)
        values = []
        for ref in r.inputs:
            version = _version(c, p, ref)
            event = _latest(c, p, ref.version_id)
            state = event["payload"]["target_state"] if event else None
            input_minimum = "AUTHORITATIVE" if str(ref.resource_id) in controls else minimum
            if (
                event is None
                or state not in progression
                or progression.index(state) < progression.index(input_minimum)
                or event["payload"]["availability_state"] != "AVAILABLE"
            ):
                raise WorkspaceError(409, "Input does not meet required authority and availability")
            certification = None
            if state == "CERTIFIED":
                certification = certified_event(
                    c, p, ref, event, requirements.get(str(ref.resource_id))
                )
            values.append(
                {
                    "subject": ref.model_dump(mode="json"),
                    "event_id": str(event["event_id"]),
                    "content_hash": version["content_hash"],
                    "authority_state": state,
                    "attributes": version["attributes"],
                    "access_entity": version["access_entity"],
                    "epistemic_state": event["payload"]["epistemic_state"],
                    "business_state": event["payload"]["business_state"],
                    "availability_state": event["payload"]["availability_state"],
                    **({"certification": certification} if certification else {}),
                    **({"authority_control": True} if str(ref.resource_id) in controls else {}),
                }
            )
        proof = {
            "contract_version": "guarded-consumption/3"
            if (
                minimum == "CERTIFIED"
                or consumer_certification
                or any("certification" in item for item in values)
            )
            else "guarded-consumption/2",
            "purpose": "GUARDED_CURRENT_CONSUMPTION",
            "consumption_id": str(r.request_id),
            "consumer": r.consumer.model_dump(mode="json"),
            "consumer_content_hash": consumer["content_hash"],
            "consumer_event_id": str(consumer_event["event_id"]) if consumer_event else None,
            "minimum_state": minimum,
            "access_entity": consumer["access_entity"],
            "inputs": sorted(values, key=lambda item: item["subject"]["version_id"]),
            "upstream_authority": upstream_authority(c, p.scope.tenant_id, r.consumer.version_id),
            **(
                {"consumer_certification": consumer_certification} if consumer_certification else {}
            ),
            **(
                {
                    "certification_requirements": {
                        key: value.model_dump(mode="json") for key, value in requirements.items()
                    }
                }
                if minimum == "CERTIFIED"
                else {}
            ),
        }
        proof_hash = _proof_hash(proof)
        previous = c.execute(
            "SELECT * FROM guarded_consumption_receipts WHERE tenant_id=%s AND consumption_id=%s",
            (p.scope.tenant_id, r.request_id),
        ).fetchone()
        if previous:
            if (
                previous["request_hash"] != canonical_sha256(r)
                or previous["actor_id"] != p.actor_id
            ):
                raise WorkspaceError(409, "Consumption identity already used by another request")
            if previous["proof_hash"] != proof_hash:
                raise WorkspaceError(
                    409, "Consumption authority changed; use a new request identity"
                )
            return {
                **previous["payload"],
                "proof_hash": proof_hash,
                "checked_at": previous["recorded_at"].isoformat(),
            }
        saved = c.execute(
            "INSERT INTO guarded_consumption_receipts "
            "(tenant_id,consumption_id,consumer_resource_id,consumer_version_id,access_entity,"
            "actor_id,request_hash,proof_hash,payload) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "RETURNING recorded_at",
            (
                p.scope.tenant_id,
                r.request_id,
                r.consumer.resource_id,
                r.consumer.version_id,
                consumer["access_entity"],
                p.actor_id,
                canonical_sha256(r),
                proof_hash,
                Jsonb(proof),
            ),
        ).fetchone()
        assert saved is not None
        return {**proof, "proof_hash": proof_hash, "checked_at": saved["recorded_at"].isoformat()}


def _proof_hash(proof: dict[str, Any]) -> str:
    return sha256(json.dumps(proof, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def consumption_receipt(p: Principal, consumption_id: UUID) -> dict[str, Any]:
    require_permission(p, "ontology_read")
    with resource_connection(p) as conn, conn.cursor(row_factory=dict_row) as c:
        row = c.execute(
            "SELECT * FROM guarded_consumption_receipts WHERE tenant_id=%s AND consumption_id=%s",
            (p.scope.tenant_id, consumption_id),
        ).fetchone()
        if row is None:
            raise WorkspaceError(404, "Consumption receipt unavailable in authorized context")
        if _proof_hash(row["payload"]) != row["proof_hash"]:
            raise WorkspaceError(503, "Retained consumption proof failed integrity verification")
        return {
            "purpose": "HISTORICAL_CONSUMPTION_EVIDENCE",
            "current_use_authorized": False,
            "proof": row["payload"],
            "proof_hash": row["proof_hash"],
            "recorded_at": row["recorded_at"],
            "actor_id": row["actor_id"],
        }


def consumption_status(p: Principal, consumption_id: UUID) -> dict[str, Any]:
    from finai_api.services.certification_consumption import certified_event, requirements_for_use

    retained = consumption_receipt(p, consumption_id)
    proof = retained["proof"]
    checks = []
    references = {
        item["version_id"]: {**item, "role": "UPSTREAM"}
        for item in proof.get("upstream_authority", [])
    }
    for item in proof["inputs"]:
        references[item["subject"]["version_id"]] = {
            **item["subject"],
            "event_id": item["event_id"],
            "role": "INPUT",
        }
    references[proof["consumer"]["version_id"]] = {
        **proof["consumer"],
        "event_id": proof.get("consumer_event_id"),
        "role": "CONSUMER",
    }
    with resource_connection(p) as conn, conn.cursor(row_factory=dict_row) as c:
        _lock(conn, p)
        progression = [*ORDER, "CERTIFIED"]
        requirements: dict[str, VersionReference] = {}
        controls: set[str] = set()
        certification_contract_blocked = False
        if proof["minimum_state"] == "CERTIFIED":
            try:
                consumer = _version(c, p, VersionReference.model_validate(proof["consumer"]))
                requirements, controls = requirements_for_use(
                    c,
                    p,
                    consumer,
                    [VersionReference.model_validate(item["subject"]) for item in proof["inputs"]],
                )
            except WorkspaceError as exc:
                if exc.status not in (404, 409):
                    raise
                certification_contract_blocked = True
        for item in references.values():
            ref = VersionReference(resource_id=item["resource_id"], version_id=item["version_id"])
            reason = None
            current_event = None
            state = None
            availability = None
            try:
                _version(c, p, ref)
                current_event = _latest(c, p, ref.version_id)
                if current_event:
                    state = current_event["payload"]["target_state"]
                    availability = current_event["payload"]["availability_state"]
                if state in ("REVOKED", "SUPERSEDED"):
                    reason = "AUTHORITY_WITHDRAWN"
                elif item["role"] != "CONSUMER" and current_event and availability != "AVAILABLE":
                    reason = "AVAILABILITY_WITHDRAWN"
                elif item["role"] == "INPUT" and (
                    state not in progression
                    or proof["minimum_state"] not in progression
                    or progression.index(state)
                    < progression.index(
                        "AUTHORITATIVE"
                        if str(ref.resource_id) in controls
                        else proof["minimum_state"]
                    )
                ):
                    reason = "MINIMUM_AUTHORITY_NOT_MET"
                if reason is None and state == "CERTIFIED" and current_event:
                    try:
                        certified_event(
                            c, p, ref, current_event, requirements.get(str(ref.resource_id))
                        )
                    except WorkspaceError as exc:
                        if exc.status not in (404, 409):
                            raise
                        reason = "CERTIFICATION_UNAVAILABLE"
            except WorkspaceError as exc:
                if exc.status not in (404, 409):
                    raise
                reason = "VERSION_NOT_CURRENT_OR_ACCESSIBLE"
            current_id = str(current_event["event_id"]) if current_event else None
            checks.append(
                {
                    "subject": ref.model_dump(mode="json"),
                    "role": item["role"],
                    "retained_event_id": item.get("event_id"),
                    "current_event_id": current_id,
                    "authority_state": state,
                    "availability_state": availability,
                    "event_changed": current_id != item.get("event_id"),
                    "blocker": reason,
                }
            )
    legacy = proof.get("contract_version") not in ("guarded-consumption/2", "guarded-consumption/3")
    blocked = legacy or certification_contract_blocked or any(item["blocker"] for item in checks)
    return {
        "purpose": "CONSUMPTION_ELIGIBILITY_EXPLANATION",
        "consumption_id": str(consumption_id),
        "current_use_authorized": False,
        "proof_hash": retained["proof_hash"],
        "status": "BLOCKED" if blocked else "RECHECK_REQUIRED",
        "legacy_proof_requires_recheck": legacy,
        "certification_contract_blocked": certification_contract_blocked,
        "checks": checks,
        "checked_at": datetime.now(UTC).isoformat(),
    }
