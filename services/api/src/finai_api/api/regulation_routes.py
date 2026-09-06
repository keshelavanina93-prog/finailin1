"""Regulatory workspace over the shared reviewed, bitemporal ontology authority."""

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field
from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from finai_api.api.ontology_routes import User
from finai_api.api.workflow_routes import client
from finai_api.domain.regulation import RegulatoryDefinition, assess_rule
from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.regulatory_workflow import RegulatorySourceCheck
from finai_api.security import require_permission
from finai_api.services import regulatory_monitors, regulatory_sources, resources
from finai_api.services import report_workflows as records
from finai_api.services.fact_runs import read_run, retain_run
from finai_api.services.regulatory_licence_context import bind_assessment, licence_bindings
from finai_api.services.workspace import WorkspaceError

router = APIRouter(prefix="/v1/ontology/regulation", tags=["regulation"])


@router.post("/monitors")
async def start_monitor(principal: User, request: regulatory_monitors.MonitorRequest):
    identity = await asyncio.to_thread(regulatory_monitors.retain, principal, request)
    runtime = await client()
    with suppress(ScheduleAlreadyRunningError):
        await runtime.create_schedule(
            identity,
            Schedule(
                action=ScheduleActionStartWorkflow(
                    RegulatorySourceCheck.run,
                    {
                        "workflow_id": identity,
                        "actor_id": principal.actor_id,
                        "scope": principal.scope.model_dump(mode="json"),
                    },
                    id=identity + "-check",
                    task_queue="g8-report-source-v1",
                    execution_timeout=timedelta(minutes=15),
                ),
                spec=ScheduleSpec(
                    intervals=[ScheduleIntervalSpec(every=timedelta(hours=request.cadence_hours))]
                ),
                policy=SchedulePolicy(
                    overlap=ScheduleOverlapPolicy.SKIP, catchup_window=timedelta(hours=1)
                ),
            ),
            trigger_immediately=True,
        )
    return {"workflow_id": identity}


@router.get("/monitors")
def list_monitors(principal: User):
    return regulatory_monitors.listing(principal)


@router.get("/monitors/{identity}")
async def read_monitor(identity: str, principal: User):
    result = await asyncio.to_thread(regulatory_monitors.read, principal, identity)
    successes = [e for e in result["events"] if "signature" in e]
    checks = [e for e in result["events"] if e.get("check_id")]
    result["last_success"] = successes[-1] if successes else None
    changed = [e for e in successes if e["state"] != "UNCHANGED"]
    result["last_new_item"] = changed[-1] if changed else None
    result["source_health"] = checks[-1]["state"] if checks else "NOT_CHECKED"
    last_check = datetime.fromisoformat(
        successes[-1]["checked_at"] if successes else result["created_at"]
    )
    result["freshness"] = (
        "OVERDUE"
        if datetime.now(UTC) - last_check > timedelta(hours=result["request"]["cadence_hours"] + 1)
        else "WITHIN_CHECK_WINDOW"
    )
    try:
        runtime = await client()
        description = await runtime.get_schedule_handle(identity).describe()
        result["runtime"] = {
            "state": "PAUSED" if description.schedule.state.paused else "ENABLED",
            "next_checks": [value.isoformat() for value in description.info.next_action_times],
            "running_checks": len(description.info.running_actions),
            "started_actions": description.info.num_actions,
        }
        if description.info.recent_actions:
            latest = description.info.recent_actions[-1].action
            execution = await runtime.get_workflow_handle(latest.workflow_id).describe()
            status = execution.status.name if execution.status else "UNKNOWN"
            result["runtime"]["latest_execution"] = status
            if status in {"FAILED", "TIMED_OUT", "TERMINATED", "CANCELED"}:
                result["source_health"] = "CHECK_FAILED"
            elif status == "RUNNING":
                result["source_health"] = "CHECKING"
    except Exception:
        result["runtime"] = {"state": "UNOBSERVABLE", "next_checks": []}
    return result


class MonitorControl(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: Literal["pause", "resume"]
    reason: str = Field(min_length=10, max_length=2000)
    idempotency_key: UUID


@router.post("/monitors/{identity}/control")
async def control_monitor(identity: str, principal: User, request: MonitorControl):
    require_permission(principal, "ingest")
    record = await asyncio.to_thread(regulatory_monitors.read, principal, identity)
    key = "control:" + str(request.idempotency_key)
    payload = {"command": request.command, "reason": request.reason, "actor_id": principal.actor_id}
    # Persist intent first. Reusing a key with altered content is rejected by shared storage.
    await asyncio.to_thread(records.event, principal, identity, key, payload)
    if any(e["event_id"] == key + ":applied" for e in record["events"]):
        return {"workflow_id": identity, "state": "ALREADY_APPLIED"}
    runtime = await client()
    handle = runtime.get_schedule_handle(identity)
    if request.command == "pause":
        await handle.pause(note=request.reason)
    else:
        await handle.unpause(note=request.reason)
    await asyncio.to_thread(records.event, principal, identity, key + ":applied", payload)
    return {"workflow_id": identity, "state": "APPLIED"}


@router.post("/sources/capture")
def capture_source(principal: User, request: regulatory_sources.Capture):
    return regulatory_sources.capture(principal, request)


@router.post("/sources/proposals")
def publish_source(principal: User, request: regulatory_sources.Publication):
    require_permission(principal, "ontology_propose")
    return regulatory_sources.propose(principal, request)


@router.get("/sources")
def source_publications(principal: User, offset: Annotated[int, Query(ge=0)] = 0):
    rows = resources.list_resources(principal, "SourceRegulatoryPublication", "", offset)
    return {"publications": rows, "next_offset": offset + 100 if len(rows) == 100 else None}


@router.post("/sources/compare")
def compare_sources(principal: User, request: regulatory_sources.Comparison):
    return retain_run(
        principal,
        regulatory_sources.compare(principal, request),
        runtime="regulatory-source-comparison/1",
    )


@router.get("/sources/inspect")
def inspect_source(principal: User, document_id: str):
    metadata, observed = regulatory_sources.inspect(principal, document_id)
    return {
        "document": {"document_id": document_id, "sha256": metadata["source_sha256"]},
        "observation": observed,
        "source_url": f"https://matsne.gov.ge/ka/document/view/{observed['matsne_id']}?publication={observed['publication']}",
    }


class RuleProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=3, max_length=200)
    key: str = Field(min_length=1, max_length=256)
    act_id: UUID
    legal_entity_id: UUID
    licence_id: UUID
    evidence_id: UUID
    definition: RegulatoryDefinition
    rationale: str = Field(min_length=10, max_length=2000)


@router.post("/proposals")
def propose_rule(principal: User, request: RuleProposal):
    require_permission(principal, "ontology_propose")
    entity = resources.get_resource(principal, request.legal_entity_id)["resource"]
    if entity["object_type"] != "LegalEntity":
        raise WorkspaceError(422, "Regulatory scope requires a legal entity")
    # Persist the interpretation now; its legal effective dates are independently evaluated.
    attributes = request.model_dump(mode="json", exclude={"name", "key", "rationale"})
    proposal = ResourceProposal(
        title=request.name,
        rationale=request.rationale,
        access_entity=entity["access_entity"],
        mutations=[
            ResourceMutation(
                object_type="RegulatoryRule",
                identity_key=request.key,
                display_name=request.name,
                attributes=attributes,
                valid_from=datetime.now(UTC),
                evidence_class="SOURCE_BOUND",
            )
        ],
    )
    return resources.propose(principal, proposal)


@router.get("/rules")
def rules(
    principal: User,
    legal_entity_id: UUID,
    activity: Literal["DISTRIBUTION", "TRANSMISSION", "SUPPLY"],
    customer_count: Annotated[int | None, Query(ge=0)] = None,
    at: datetime | None = None,
    known_at: datetime | None = None,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
):
    at, known_at = at or datetime.now(UTC), known_at or datetime.now(UTC)
    if at.tzinfo is None or known_at.tzinfo is None:
        raise WorkspaceError(422, "Assessment timestamps require a timezone")
    entity = resources.get_resource(principal, legal_entity_id)["resource"]
    if entity["object_type"] != "LegalEntity":
        raise WorkspaceError(422, "Regulatory scope requires a legal entity")
    # Registry valid time describes the interpretation's availability, not the legal period.
    page = resources.list_resources(principal, "RegulatoryRule", "", offset, known_at, known_at)
    holders, complete = licence_bindings(principal, legal_entity_id, at, known_at)
    results = []
    for item in page:
        if str(item.attributes["legal_entity_id"]) != str(legal_entity_id):
            continue
        definition = RegulatoryDefinition.model_validate(item.attributes["definition"])
        dependencies = resources.version_references(principal, item.version_id)
        base = assess_rule(definition, at.date(), activity, customer_count)
        assessed = bind_assessment(base.copy(), dependencies, holders, complete)
        blockers = []
        if base["legal_state"] != "CURRENT_EFFECTIVE":
            blockers.append(base["legal_state"])
        if base["applicability"] != "APPLICABLE":
            blockers.append(base["applicability"])
        if assessed["applicability"] not in {"APPLICABLE", base["applicability"]}:
            blockers.append(assessed["applicability"])
        assessed["blocking_reasons"] = blockers
        results.append(
            {
                "resource": item,
                "dependencies": dependencies,
                "assessment": assessed,
            }
        )
    return {
        "rules": results,
        "at": at,
        "known_at": known_at,
        "context_basis": "USER_SUPPLIED_SCENARIO",
        "company": {key: entity[key] for key in ("resource_id", "version_id", "display_name")},
        "accounting_effects_created": False,
        "next_offset": offset + 100 if len(page) == 100 else None,
    }


class AssessmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    legal_entity_id: UUID
    activity: Literal["DISTRIBUTION", "TRANSMISSION", "SUPPLY"]
    customer_count: int | None = Field(default=None, ge=0)
    at: datetime | None = None
    known_at: datetime | None = None


@router.post("/assessments")
def retain_assessment(principal: User, request: AssessmentRequest):
    at, known = request.at or datetime.now(UTC), request.known_at or datetime.now(UTC)
    collected = []
    for offset in range(0, 10000, 100):
        page = rules(
            principal,
            request.legal_entity_id,
            request.activity,
            request.customer_count,
            at,
            known,
            offset,
        )
        collected.extend(page["rules"])
        if page["next_offset"] is None:
            break
    else:
        raise WorkspaceError(422, "Rule population exceeds complete assessment capacity")
    return retain_run(
        principal,
        {
            **page,
            "rules": collected,
            "next_offset": None,
            "contract": "regulatory-assessment/1",
            "coverage": "COMPLETE_AUTHORIZED_RULE_SCAN",
            "assessment_context": request.model_dump(mode="json") | {"at": at, "known_at": known},
            "no_rules_found": not collected,
        },
        runtime="regulatory-applicability/1",
    )


@router.get("/assessments/{run_id}")
def read_assessment(principal: User, run_id: str):
    result = read_run(principal, run_id)
    if result.get("contract") != "regulatory-assessment/1":
        raise WorkspaceError(404, "Regulatory assessment unavailable")
    return result
