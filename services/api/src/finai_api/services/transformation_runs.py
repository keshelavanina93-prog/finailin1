"""Durable orchestration references over existing workflow and Function evidence."""

from uuid import uuid5

from psycopg.types.json import Jsonb
from temporalio import activity

from finai_api.domain.authority import canonical_sha256
from finai_api.domain.function_execution import FunctionInvocation
from finai_api.domain.review import Principal
from finai_api.domain.transformation import TransformationRunRequest
from finai_api.security import require_permission
from finai_api.services import execution_publication as publication
from finai_api.services import function_execution, function_invocations, transformation_definitions
from finai_api.services import report_workflows as records
from finai_api.services.resources import resource_connection
from finai_api.services.workspace import WorkspaceError

VERSION = "transformation-functions/1"


def retain(principal: Principal, request: TransformationRunRequest) -> str:
    require_permission(principal, "ontology_read")
    identity = "transformation:" + str(request.request_id)
    request_hash = canonical_sha256(request)
    with resource_connection(principal) as conn:
        scope = records.set_scope(conn, principal)
        old = conn.execute(
            "SELECT actor_id,payload FROM workflow_requests WHERE tenant_id=%s AND workflow_id=%s",
            (principal.scope.tenant_id, identity),
        ).fetchone()
        if old:
            if old[0] != principal.actor_id or old[1].get("request_hash") != request_hash:
                raise WorkspaceError(409, "Transformation run identity already used differently")
            return identity
    compiled = transformation_definitions.plan(principal, request)
    payload = {
        "request_hash": request_hash,
        "compiled_plan": compiled,
        "definition": {
            "version": VERSION,
            "nodes": compiled["nodes"],
            "outputs": {item["output_id"]: "function-invocation/1" for item in compiled["outputs"]},
        },
    }
    with resource_connection(principal) as conn:
        scope = records.set_scope(conn, principal)
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
        old = conn.execute(
            "SELECT actor_id,payload FROM workflow_requests WHERE tenant_id=%s AND workflow_id=%s",
            (principal.scope.tenant_id, identity),
        ).fetchone()
        if not old or old[0] != principal.actor_id or old[1].get("request_hash") != request_hash:
            raise WorkspaceError(409, "Transformation run identity unavailable or conflicting")
    return identity


def read(principal: Principal, identity: str) -> dict:
    require_permission(principal, "ontology_read")
    result = records.read(principal, identity)
    if result["definition"].get("version") != VERSION:
        raise WorkspaceError(404, "Transformation run unavailable")
    compiled = result["request"]["compiled_plan"]
    request = TransformationRunRequest.model_validate(compiled["request"])
    if (
        result["request"].get("request_hash") != canonical_sha256(request)
        or identity != "transformation:" + str(request.request_id)
        or any(
            node["invocation"]["request_id"] != str(uuid5(request.request_id, node["node_id"]))
            for node in compiled["nodes"]
        )
    ):
        raise WorkspaceError(409, "Transformation invocation identity integrity failed")
    if function_execution._digest(
        {key: value for key, value in compiled.items() if key != "plan_hash"}
    ) != compiled.get("plan_hash"):
        raise WorkspaceError(409, "Retained transformation plan integrity failed")
    manifests = publication.published(result)
    expected_slots = set(result["definition"]["outputs"])
    for manifest in manifests:
        outputs = manifest.get("outputs", [])
        if (
            manifest.get("publication_id")
            != "pub_"
            + publication.digest(
                {key: value for key, value in manifest.items() if key != "publication_id"}
            )
            or manifest.get("definition_sha256") != publication.digest(result["definition"])
            or manifest.get("workflow_id") != identity
            or manifest.get("generation") != 0
            or manifest.get("authority") != "EXECUTION_ONLY"
            or len(outputs) != len(expected_slots)
            or {output.get("slot") for output in outputs} != expected_slots
            or any(
                output.get("sha256") != publication.digest(output.get("value"))
                for output in outputs
            )
        ):
            raise WorkspaceError(409, "Transformation publication integrity failed")
    return {
        **result,
        "publications": manifests,
        "current_use_authorized": False,
        "business_effect_authorized": False,
    }


def _context(context: dict) -> tuple[Principal, dict]:
    principal = records.current_principal(context["actor_id"], context["scope"])
    retained = read(principal, context["workflow_id"])
    if retained["actor_id"] != principal.actor_id:
        raise WorkspaceError(403, "Transformation activity owner does not match retained run")
    return principal, retained


@activity.defn(name="transformation_load")
def load(context: dict) -> dict:
    _, retained = _context(context)
    compiled = retained["request"]["compiled_plan"]
    # Only orchestration topology, never source values, crosses into Temporal history.
    return {
        "node_order": compiled["node_order"],
        "dependencies": {node["node_id"]: node["depends_on"] for node in compiled["nodes"]},
    }


@activity.defn(name="transformation_node")
def execute_node(context: dict) -> dict:
    principal, retained = _context(context)
    identity = context["workflow_id"]
    compiled = retained["request"]["compiled_plan"]
    node_id = context["node_id"]
    node = next((node for node in compiled["nodes"] if node["node_id"] == node_id), None)
    if node is None:
        raise WorkspaceError(409, "Node is not in the retained transformation")
    events = {event["event_id"]: event for event in retained["events"]}
    for dependency in node["depends_on"]:
        if events.get("node:" + dependency + ":terminal", {}).get("state") != "COMPLETED":
            raise WorkspaceError(409, "Transformation completion barrier is not satisfied")
    request = FunctionInvocation.model_validate(node["invocation"])
    records.event(
        principal, identity, "node:" + node_id + ":started", {"node": node_id, "state": "RUNNING"}
    )
    # Reuse terminal invocation evidence after a lost activity acknowledgement.
    try:
        result = function_invocations.history(principal, request.request_id)
    except WorkspaceError as exc:
        if exc.status != 404:
            raise
        result = None
    if result is None or result["status"] == "INTENT_RETAINED":
        if function_execution.plan(principal, request) != node["function_plan"]:
            raise WorkspaceError(
                409, "Pinned Function plan changed; create a new transformation run"
            )
        result = function_invocations.invoke(principal, request)
    succeeded = result["status"] == "SUCCEEDED"
    reference = {
        "invocation_id": result["invocation_id"],
        "receipt_hash": result["receipt_hash"],
        **({"run_id": result["output"]["run_id"]} if succeeded else {}),
    }
    terminal = {
        "node": node_id,
        "state": "COMPLETED" if succeeded else "FAILED",
        "output": reference,
        "new_run_required": not succeeded,
    }
    records.event(principal, identity, "node:" + node_id + ":terminal", terminal)
    if succeeded:
        for output in compiled["outputs"]:
            if output["node_id"] == node_id:
                publication.stage(
                    principal, identity, 0, output["output_id"], "function-invocation/1", reference
                )
    return terminal


@activity.defn(name="transformation_publish")
def publish(context: dict) -> dict:
    principal, retained = _context(context)
    completed = {
        event.get("node") for event in retained["events"] if event.get("state") == "COMPLETED"
    }
    if completed != set(retained["request"]["compiled_plan"]["node_order"]):
        raise WorkspaceError(409, "Transformation is incomplete; publication refused")
    manifest = publication.publish(principal, context["workflow_id"], 0)
    return {"publication_id": manifest["publication_id"], "generation": 0}
