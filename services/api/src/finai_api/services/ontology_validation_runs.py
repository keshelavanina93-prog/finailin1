"""Durable validation observations over the shared workflow and retained evidence stores."""

import json
import os
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb
from temporalio import activity

from finai_api.domain.external_ontology import RetainedDocument
from finai_api.domain.ontology_validation import (
    RetainedGraphSelection,
    ValidationPlan,
    ValidationReportDefinition,
    ValidationRunRequest,
)
from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services import execution_publication as publication
from finai_api.services import ontology_import
from finai_api.services import report_workflows as records
from finai_api.services.resources import resource_connection
from finai_api.services.workspace import WorkspaceError
from finai_api.storage import connection

VERSION = "ontology-validation/1"
DEFINITION = {
    "version": VERSION,
    "nodes": [{"id": "validate", "function": "pyshacl/0.40.1-core-offline/1", "depends_on": []}],
    "outputs": {"report": "ontology-validation-report/1"},
}
TERMINAL = "validation:terminal"
CANCELLATION = "validation:cancelled"


def _permission(principal: Principal) -> None:
    for permission in ("ontology_read", "read", "ingest"):
        require_permission(principal, permission)


def compile_plan(
    principal: Principal, request: ValidationRunRequest, *, conn: Any = None
) -> ValidationPlan:
    from finai_api.services import constraint_validator as engine
    from finai_api.services.ontology_profiles import resolve_run

    _, constraint, data, shapes = resolve_run(principal, request, conn=conn)
    selection = engine.ValidationSelection(
        mode=constraint.selection.mode,
        focus_iris=tuple(constraint.selection.focus_iris),
        shape_iris=tuple(constraint.selection.shape_iris),
    )
    return ValidationPlan(
        request_sha256=ontology_import.digest(request.model_dump(mode="json")),
        ontology_profile=constraint.ontology_profile,
        constraint_profile=request.constraint_profile,
        data=RetainedGraphSelection(
            **request.data.model_dump(), canonical_dataset=data.canonical_dataset
        ),
        shapes=RetainedGraphSelection(
            **constraint.shapes.model_dump(), canonical_dataset=shapes.canonical_dataset
        ),
        selection=constraint.selection,
        validator_manifest_sha256=ontology_import.digest(
            engine.validator_manifest(selection=selection)
        ),
    )


def _lock(conn: Any, principal: Principal, identity: str) -> None:
    # Same order as canonical review; never hold either lock while running the child.
    for key in (
        f"canonical:{principal.scope.tenant_id}",
        f"ontology-validation:{principal.scope.tenant_id}:{identity}",
    ):
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (key,))


def _snapshot(principal: Principal, identity: str, conn: Any = None) -> dict:
    if conn is None:
        result = records.read(principal, identity)
    else:
        scope = records.set_scope(conn, principal)
        row = conn.execute(
            "SELECT payload,actor_id,created_at FROM workflow_requests "
            "WHERE tenant_id=%s AND exact_scope=%s AND workflow_id=%s",
            (principal.scope.tenant_id, Jsonb(scope), identity),
        ).fetchone()
        if row is None:
            raise WorkspaceError(404, "Validation unavailable in this exact scope")
        events = conn.execute(
            "SELECT event_id,payload,created_at FROM workflow_events "
            "WHERE tenant_id=%s AND exact_scope=%s AND workflow_id=%s ORDER BY created_at,event_id",
            (principal.scope.tenant_id, Jsonb(scope), identity),
        ).fetchall()
        result = {
            "workflow_id": identity,
            "actor_id": row[1],
            "created_at": row[2].isoformat(),
            "request": row[0],
            "definition": row[0].get("definition"),
            "events": [{"event_id": e[0], **e[1], "created_at": e[2].isoformat()} for e in events],
        }
    if result["definition"] != DEFINITION:
        raise WorkspaceError(404, "Validation workflow family unavailable")
    payload = result["request"]
    try:
        request = ValidationRunRequest.model_validate(payload["request"])
        plan = ValidationPlan.model_validate(payload["plan"])
    except (ValueError, KeyError) as exc:
        raise WorkspaceError(409, "Retained validation intent is invalid") from exc
    if (
        identity != "ontology-validation:" + str(request.request_id)
        or plan.request_sha256 != ontology_import.digest(request.model_dump(mode="json"))
        or payload.get("plan_sha256") != ontology_import.digest(plan.model_dump(mode="json"))
        or plan.constraint_profile != request.constraint_profile
        or plan.data.release != request.data.release
        or plan.data.graph_iris != request.data.graph_iris
    ):
        raise WorkspaceError(409, "Retained validation intent integrity failed")
    return result


def _event(conn: Any, principal: Principal, identity: str, key: str, value: dict) -> None:
    scope = records.set_scope(conn, principal)
    previous = conn.execute(
        "SELECT payload FROM workflow_events WHERE tenant_id=%s AND workflow_id=%s "
        "AND exact_scope=%s AND event_id=%s",
        (principal.scope.tenant_id, identity, Jsonb(scope), key),
    ).fetchone()
    if previous is not None:
        if previous[0] != value:
            raise WorkspaceError(409, "Validation event identity conflicts with retained evidence")
        return
    conn.execute(
        "INSERT INTO workflow_events(tenant_id,workflow_id,exact_scope,event_id,payload) "
        "VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
        (principal.scope.tenant_id, identity, Jsonb(scope), key, Jsonb(value)),
    )
    old = conn.execute(
        "SELECT payload FROM workflow_events WHERE tenant_id=%s AND workflow_id=%s "
        "AND exact_scope=%s AND event_id=%s",
        (principal.scope.tenant_id, identity, Jsonb(scope), key),
    ).fetchone()
    if old is None or old[0] != value:
        raise WorkspaceError(409, "Validation event identity conflicts with retained evidence")


def _events(record: dict) -> dict:
    return {event["event_id"]: event for event in record["events"]}


def _current(principal: Principal, record: dict, conn: Any = None) -> None:
    request = ValidationRunRequest.model_validate(record["request"]["request"])
    if (
        compile_plan(principal, request, conn=conn).model_dump(mode="json")
        != record["request"]["plan"]
    ):
        raise WorkspaceError(409, "Validation plan changed; retain a new validation request")


def _owner(principal: Principal, record: dict) -> None:
    _permission(principal)
    if record["actor_id"] != principal.actor_id:
        raise WorkspaceError(403, "Validation activity owner differs from the retained request")


def retain(principal: Principal, request: ValidationRunRequest) -> str:
    _permission(principal)
    identity = "ontology-validation:" + str(request.request_id)
    with resource_connection(principal) as conn:
        records.set_scope(conn, principal)
        _lock(conn, principal, identity)
        plan = compile_plan(principal, request, conn=conn)
        payload = {
            "request": request.model_dump(mode="json"),
            "plan": plan.model_dump(mode="json"),
            "plan_sha256": ontology_import.digest(plan.model_dump(mode="json")),
            "definition": DEFINITION,
        }
        conn.execute(
            "INSERT INTO workflow_requests"
            "(tenant_id,workflow_id,exact_scope,actor_id,definition_version,payload) "
            "VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (
                principal.scope.tenant_id,
                identity,
                Jsonb(principal.scope.model_dump(mode="json")),
                principal.actor_id,
                VERSION,
                Jsonb(payload),
            ),
        )
        old = _snapshot(principal, identity, conn)
        if old["actor_id"] != principal.actor_id or old["request"] != payload:
            raise WorkspaceError(409, "Validation request identity already used differently")
    return identity


def _terminal(record: dict) -> ValidationReportDefinition | None:
    event = _events(record).get(TERMINAL)
    if event is None:
        return None
    try:
        result = ValidationReportDefinition.model_validate(event["report"])
    except (ValueError, KeyError) as exc:
        raise WorkspaceError(409, "Retained validation terminal is invalid") from exc
    if (
        event.get("state") != "COMPLETED"
        or result.workflow_id != record["workflow_id"]
        or result.request_sha256 != record["request"]["plan"]["request_sha256"]
        or result.plan_sha256 != record["request"]["plan_sha256"]
    ):
        raise WorkspaceError(409, "Retained validation terminal integrity failed")
    return result


def _verify_report(principal: Principal, report: ValidationReportDefinition) -> dict:
    try:
        envelope = json.loads(ontology_import.read_document(principal, report.report))
        if (
            envelope["contract"] != "ontology-validation-observation/1"
            or envelope["request_sha256"] != report.request_sha256
            or envelope["plan_sha256"] != report.plan_sha256
            or envelope["outcome"] != report.outcome
            or envelope["business_effect_authorized"] is not False
        ):
            raise ValueError("report binding")
        if envelope.get("rdf_report") is not None:
            ontology_import.read_document(
                principal, RetainedDocument.model_validate(envelope["rdf_report"])
            )
        return envelope
    except (ValueError, KeyError, TypeError) as exc:
        raise WorkspaceError(409, "Retained validation report integrity failed") from exc


def _publications(record: dict, terminal: ValidationReportDefinition | None) -> list[dict]:
    manifests = publication.published(record)
    for manifest in manifests:
        outputs = manifest.get("outputs", [])
        if (
            terminal is None
            or len(manifests) != 1
            or manifest.get("protocol") != "execution-publication/1"
            or manifest.get("generation") != 0
            or manifest.get("workflow_id") != record["workflow_id"]
            or manifest.get("authority") != "EXECUTION_ONLY"
            or manifest.get("definition_sha256") != publication.digest(DEFINITION)
            or manifest.get("publication_id")
            != "pub_"
            + publication.digest(
                {key: value for key, value in manifest.items() if key != "publication_id"}
            )
            or len(outputs) != 1
            or outputs[0].get("slot") != "report"
            or outputs[0].get("event_id") != "output:" + publication.digest([0, "report"])
            or outputs[0].get("artifact_type") != "ontology-validation-report/1"
            or outputs[0].get("value") != terminal.model_dump(mode="json")
            or outputs[0].get("sha256") != publication.digest(outputs[0].get("value"))
        ):
            raise WorkspaceError(409, "Validation publication integrity failed")
    return manifests


def read(principal: Principal, identity: str) -> dict:
    require_permission(principal, "ontology_read")
    record = _snapshot(principal, identity)
    if record["actor_id"] != principal.actor_id:
        raise WorkspaceError(403, "Validation status belongs to another actor")
    terminal = _terminal(record)
    envelope = _verify_report(principal, terminal) if terminal else None
    manifests = _publications(record, terminal)
    events = _events(record)
    return {
        **record,
        "scope": principal.scope.model_dump(mode="json"),
        "state": "CANCELLED"
        if CANCELLATION in events
        else "PUBLISHED"
        if manifests
        else "COMPLETED"
        if terminal
        else "RUNNING"
        if "validation:started" in events
        else "INTENT_RETAINED",
        "terminal": terminal.model_dump(mode="json") if terminal else None,
        "report": envelope,
        "publications": manifests,
        "current_use_authorized": False,
        "business_effect_authorized": False,
    }


def _context(context: dict) -> tuple[Principal, dict]:
    principal = records.current_principal(context["actor_id"], context["scope"])
    record = _snapshot(principal, context["workflow_id"])
    _owner(principal, record)
    return principal, record


@activity.defn(name="ontology_validation_load")
def load(context: dict) -> dict:
    principal, record = _context(context)
    _current(principal, record)
    if CANCELLATION in _events(record):
        raise WorkspaceError(409, "Validation was cancelled")
    return {
        "request_sha256": record["request"]["plan"]["request_sha256"],
        "plan_sha256": record["request"]["plan_sha256"],
    }


@contextmanager
def _execution_lock(principal: Principal, identity: str):
    with connection(principal.scope) as conn:
        row = conn.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s,0))",
            (f"ontology-validation-execution:{principal.scope.tenant_id}:{identity}",),
        ).fetchone()
        if row is None or not row[0]:
            raise WorkspaceError(409, "Validation is already executing; retry this exact request")
        conn.commit()
        yield


def execute_retained(principal: Principal, identity: str) -> dict:
    from finai_api.services import constraint_validator as engine

    _permission(principal)
    with _execution_lock(principal, identity):
        record = _snapshot(principal, identity)
        _owner(principal, record)
        _current(principal, record)
        if CANCELLATION in _events(record):
            raise WorkspaceError(409, "Validation was cancelled")
        previous = _terminal(record)
        if previous:
            _verify_report(principal, previous)
            return previous.model_dump(mode="json")
        plan = ValidationPlan.model_validate(record["request"]["plan"])
        records.event(principal, identity, "validation:started", {"state": "RUNNING"})
        data = ontology_import.read_document(principal, plan.data.canonical_dataset)
        shapes = ontology_import.read_document(principal, plan.shapes.canonical_dataset)
        envelope: dict = {
            "contract": "ontology-validation-observation/1",
            "request_sha256": plan.request_sha256,
            "plan_sha256": record["request"]["plan_sha256"],
            "business_effect_authorized": False,
        }
        try:
            result = engine.validate_constraints(
                engine.ValidationDataset(
                    data, plan.data.canonical_dataset.sha256, plan.data.graph_iris
                ),
                engine.ValidationDataset(
                    shapes, plan.shapes.canonical_dataset.sha256, plan.shapes.graph_iris
                ),
                work_dir=Path(os.environ.get("FINAI_RUNTIME_ROOT", ".finai")).resolve()
                / "ontology-validation",
                selection=engine.ValidationSelection(
                    mode=plan.selection.mode,
                    focus_iris=tuple(plan.selection.focus_iris),
                    shape_iris=tuple(plan.selection.shape_iris),
                ),
            )
            if ontology_import.digest(result.manifest) != plan.validator_manifest_sha256:
                raise WorkspaceError(409, "Validation worker manifest differs from retained plan")
            if (
                result.data_sha256 != plan.data.canonical_dataset.sha256
                or result.shapes_sha256 != plan.shapes.canonical_dataset.sha256
                or result.data_graph_iris != plan.data.graph_iris
                or result.shape_graph_iris != plan.shapes.graph_iris
                or result.conforms
                is not (
                    True
                    if result.status == "CONFORMS"
                    else False
                    if result.status == "VIOLATES"
                    else None
                )
            ):
                raise WorkspaceError(409, "Validation result differs from retained input contract")
            rdf_report = ontology_import.retained(
                principal, "ontology-validation-report.nq", result.report_nquads
            )
            if rdf_report.sha256 != result.report_sha256:
                raise WorkspaceError(409, "Validation report differs from worker digest")
            envelope.update(
                outcome=result.status,
                result={
                    key: value for key, value in asdict(result).items() if key != "report_nquads"
                },
                rdf_report=rdf_report.model_dump(mode="json"),
            )
        except engine.ConstraintValidatorError as exc:
            if exc.code in {"BUSY", "WALL_TIMEOUT", "WORKER_FAILED"}:
                raise WorkspaceError(
                    503, "Validation worker unavailable; retry retained request"
                ) from exc
            envelope.update(
                outcome="REFUSED", refusal_code=exc.code, conforms=None, rdf_report=None
            )
        report_document = ontology_import.retained(
            principal, "ontology-validation-observation.json", ontology_import.encoded(envelope)
        )
        report = ValidationReportDefinition(
            workflow_id=identity,
            request_sha256=plan.request_sha256,
            plan_sha256=record["request"]["plan_sha256"],
            report=report_document,
            outcome=envelope["outcome"],
        )
        with resource_connection(principal) as conn:
            _lock(conn, principal, identity)
            current = _snapshot(principal, identity, conn)
            principal = records.current_principal(
                current["actor_id"], principal.scope.model_dump(mode="json")
            )
            _owner(principal, current)
            _current(principal, current, conn)
            if CANCELLATION in _events(current):
                raise WorkspaceError(409, "Validation cancelled before report completion")
            _event(
                conn,
                principal,
                identity,
                TERMINAL,
                {"state": "COMPLETED", "report": report.model_dump(mode="json")},
            )
        return report.model_dump(mode="json")


@activity.defn(name="ontology_validation_execute")
def execute(context: dict) -> dict:
    principal, record = _context(context)
    return execute_retained(principal, record["workflow_id"])


@activity.defn(name="ontology_validation_publish")
def publish(context: dict) -> dict:
    principal, record = _context(context)
    identity = record["workflow_id"]
    terminal = _terminal(record)
    if terminal is None:
        raise WorkspaceError(409, "Validation has no completed report")
    _verify_report(principal, terminal)
    _current(principal, record)
    if CANCELLATION in _events(record):
        raise WorkspaceError(409, "Cancelled validation cannot publish")
    # Stage diagnostics outside the canonical lock: the shared stage writer owns
    # its own connection. The single publication commit below arbitrates cancellation.
    publication.stage(
        principal,
        identity,
        0,
        "report",
        "ontology-validation-report/1",
        terminal.model_dump(mode="json"),
    )
    with resource_connection(principal) as conn:
        _lock(conn, principal, identity)
        current = _snapshot(principal, identity, conn)
        principal = records.current_principal(
            current["actor_id"], principal.scope.model_dump(mode="json")
        )
        _owner(principal, current)
        _current(principal, current, conn)
        if CANCELLATION in _events(current):
            raise WorkspaceError(409, "Cancelled validation cannot publish")
        previous = _publications(current, terminal)
        if previous:
            return {"publication_id": previous[0]["publication_id"], "generation": 0}
        manifest = publication.publish(
            principal,
            identity,
            0,
            event_writer=lambda p, i, key, value: _event(conn, p, i, key, value),
        )
    return {"publication_id": manifest["publication_id"], "generation": 0}


def cancel(principal: Principal, identity: str, command_id: UUID, reason: str) -> dict:
    _permission(principal)
    if not 10 <= len(reason.strip()) <= 2000:
        raise WorkspaceError(422, "Cancellation requires a meaningful bounded reason")
    payload = {
        "state": "CANCELLED",
        "command": "cancel",
        "idempotency_key": str(command_id),
        "actor_id": principal.actor_id,
        "reason": reason.strip(),
    }
    with resource_connection(principal) as conn:
        _lock(conn, principal, identity)
        record = _snapshot(principal, identity, conn)
        _owner(principal, record)
        if _publications(record, _terminal(record)):
            raise WorkspaceError(409, "Published validation evidence cannot be cancelled")
        _event(conn, principal, identity, CANCELLATION, payload)
    return {"workflow_id": identity, "state": "CANCELLED"}


def publication_context(
    principal: Principal, identity: str, *, conn: Any = None
) -> tuple[ValidationRunRequest, ValidationPlan, ValidationReportDefinition]:
    require_permission(principal, "ontology_read")
    record = _snapshot(principal, identity, conn)
    terminal = _terminal(record)
    if terminal is None or CANCELLATION in _events(record) or not _publications(record, terminal):
        raise WorkspaceError(409, "Validation report requires its uncancelled publication")
    if conn is None:
        _verify_report(principal, terminal)
    else:
        _current(principal, record, conn)
    return (
        ValidationRunRequest.model_validate(record["request"]["request"]),
        ValidationPlan.model_validate(record["request"]["plan"]),
        terminal,
    )
