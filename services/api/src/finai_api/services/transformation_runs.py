"""Durable orchestration references over existing workflow and Function evidence."""

from uuid import UUID, uuid5

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
MEASUREMENT = "POSTGRES_JSONB_TEXT_UTF8_V1"
USAGE_KEYS = ("returned_rows", "derived_evaluations", "published_result_bytes")


def measured_usage(principal: Principal, run_id: str) -> dict:
    """Represented retained-result bytes, not disk allocation or a hard storage quota."""
    with records.scope_connection(principal) as conn:
        records.set_scope(conn, principal)
        row = conn.execute(
            "SELECT CASE WHEN payload->'implementation'->>'implementation_id'="
            "'source.retained-xls-worksheet/v1' THEN jsonb_array_length(payload->'source_rows') "
            "ELSE jsonb_array_length(payload->'objects') END,"
            "jsonb_array_length(payload->'derived_values'),"
            "octet_length(convert_to(payload::text,'UTF8')) FROM fact_calculation_runs "
            "WHERE tenant_id=%s AND run_id=%s",
            (principal.scope.tenant_id, run_id),
        ).fetchone()
    if row is None or any(value is None for value in row):
        raise WorkspaceError(409, "Retained Function result cannot be measured")
    return {"measurement": MEASUREMENT, **dict(zip(USAGE_KEYS, row, strict=True))}


def cumulative_usage(
    events: list[dict], node_id: str | None = None, usage: dict | None = None
) -> dict:
    unique = {
        event["node"]: event["usage"]
        for event in events
        if event.get("state") == "COMPLETED" and "usage" in event
    }
    if node_id is not None and usage is not None:
        unique[node_id] = usage
    return {
        "measurement": MEASUREMENT,
        **{key: sum(item[key] for item in unique.values()) for key in USAGE_KEYS},
    }


def exceeded_budget(usage: dict, budget: dict) -> bool:
    return any(usage[key] > budget["max_" + key] for key in USAGE_KEYS)


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
    from finai_api.services.transformation_bindings import projection as binding_projection

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
        "publication_review": review_projection(result),
        "binding_review": binding_projection(principal, result),
        "current_use_authorized": False,
        "business_effect_authorized": False,
    }


def review_projection(retained: dict) -> dict | None:
    compiled = retained["request"]["compiled_plan"]
    spec = compiled.get("publication_review")
    if spec is None:
        return None
    events = {event["event_id"]: event for event in retained["events"]}
    task = events.get("publication-review:task")
    decision = events.get("publication-review:decision")
    task_id = str(uuid5(UUID(compiled["request"]["request_id"]), "publication"))
    completed = {
        event.get("node"): event
        for event in retained["events"]
        if event.get("state") == "COMPLETED"
    }
    if task:
        expected = [
            {
                "output_id": output["output_id"],
                "node_id": output["node_id"],
                **completed.get(output["node_id"], {}).get("output", {}),
            }
            for output in sorted(compiled["outputs"], key=lambda output: output["output_id"])
        ]
        if (
            task.get("task_id") != task_id
            or task.get("question") != spec["question"]
            or task.get("outputs") != expected
            or set(completed) != set(compiled["node_order"])
        ):
            raise WorkspaceError(409, "Publication review task integrity failed")
    if decision and (
        not task
        or decision.get("task_id") != task_id
        or decision.get("state") not in ("APPROVED", "REJECTED")
        or decision.get("actor_id") == retained["actor_id"]
    ):
        raise WorkspaceError(409, "Publication review decision integrity failed")
    cancelled = any(event.get("command") == "cancel" for event in retained["events"])
    return {
        "task_id": task_id,
        "question": spec["question"],
        "state": "CANCELLED"
        if cancelled
        else decision["state"]
        if decision
        else "PENDING"
        if task
        else "NOT_REQUESTED",
        "outputs": task["outputs"] if task else [],
        "decision": decision,
        "run_actor_id": retained["actor_id"],
    }


def decide_review(
    principal: Principal, identity: str, decision_id: UUID, decision: str, reason: str
) -> dict:
    require_permission(principal, "ontology_read")
    require_permission(principal, "review")
    if decision not in ("APPROVED", "REJECTED") or not 10 <= len(reason.strip()) <= 2000:
        raise WorkspaceError(422, "Publication review requires a decision and meaningful reason")
    retained = read(principal, identity)
    review = retained["publication_review"]
    if principal.actor_id == retained["actor_id"]:
        raise WorkspaceError(403, "Run maker cannot decide its publication review")
    if review is None:
        raise WorkspaceError(409, "Publication review is not pending")
    payload = {
        "task_id": review["task_id"],
        "state": decision,
        "decision_id": str(decision_id),
        "actor_id": principal.actor_id,
        "reason": reason,
    }
    with resource_connection(principal) as conn:
        scope = records.set_scope(conn, principal)
        conn.execute("SELECT set_config('finai.actor_id',%s,true)", (principal.actor_id,))
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (f"transformation-review:{principal.scope.tenant_id}:{identity}",),
        )
        previous = conn.execute(
            "SELECT payload FROM workflow_events WHERE tenant_id=%s AND workflow_id=%s "
            "AND event_id='publication-review:decision'",
            (principal.scope.tenant_id, identity),
        ).fetchone()
        if previous is not None and previous[0] != payload:
            raise WorkspaceError(409, "Publication review decision identity conflicts")
        if previous is None:
            current_events = conn.execute(
                "SELECT event_id,payload FROM workflow_events "
                "WHERE tenant_id=%s AND workflow_id=%s",
                (principal.scope.tenant_id, identity),
            ).fetchall()
            current = review_projection(
                {**retained, "events": [{"event_id": row[0], **row[1]} for row in current_events]}
            )
            if current is None or current["state"] != "PENDING":
                raise WorkspaceError(409, "Publication review is not pending")
            conn.execute(
                "INSERT INTO workflow_events(tenant_id,workflow_id,exact_scope,event_id,payload) "
                "VALUES(%s,%s,%s,'publication-review:decision',%s)",
                (principal.scope.tenant_id, identity, Jsonb(scope), Jsonb(payload)),
            )
    return read(principal, identity)["publication_review"]


@activity.defn(name="transformation_publication_review")
def publication_review(context: dict) -> dict:
    from finai_api.services.transformation_bindings import record_event

    principal, retained = _context(context)
    if retained["binding_review"] is not None and retained["binding_review"]["state"] != "APPROVED":
        raise WorkspaceError(
            409, "Publication review requires the canonical binding proposal approval"
        )
    review = retained["publication_review"]
    if review is None:
        return {"state": "NOT_REQUIRED"}
    if review["state"] != "NOT_REQUESTED":
        return review
    compiled = retained["request"]["compiled_plan"]
    completed = {
        event.get("node"): event
        for event in retained["events"]
        if event.get("state") == "COMPLETED"
    }
    if set(completed) != set(compiled["node_order"]):
        raise WorkspaceError(409, "Publication review requires every completed node")
    outputs = [
        {
            "output_id": output["output_id"],
            "node_id": output["node_id"],
            **completed[output["node_id"]]["output"],
        }
        for output in sorted(compiled["outputs"], key=lambda output: output["output_id"])
    ]
    writer = record_event if retained["binding_review"] is not None else records.event
    writer(
        principal,
        context["workflow_id"],
        "publication-review:task",
        {
            "task_id": review["task_id"],
            "state": "PENDING",
            "question": review["question"],
            "outputs": outputs,
        },
    )
    return read(principal, context["workflow_id"])["publication_review"]


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
        **({"publication_review": True} if compiled.get("publication_review") else {}),
        **({"binding_review": True} if compiled.get("binding_review") else {}),
        **(
            {"execution_policy": compiled["execution_policy"]}
            if compiled.get("execution_policy")
            else {}
        ),
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
    if node.get("input_binding"):
        source_id = node["input_binding"]["upstream_node_id"]
        source_node = next(row for row in compiled["nodes"] if row["node_id"] == source_id)
        if (
            source_id not in node["depends_on"]
            or request.input_result is None
            or str(request.input_result.invocation_id) != source_node["invocation"]["request_id"]
        ):
            raise WorkspaceError(409, "Transformation retained input identity is inconsistent")
        source_receipt = function_invocations.history(principal, request.input_result.invocation_id)
        expected = {
            "invocation_id": source_receipt["invocation_id"],
            "receipt_hash": source_receipt["receipt_hash"],
            "run_id": (source_receipt.get("output") or {}).get("run_id"),
        }
        if (
            source_receipt["status"] != "SUCCEEDED"
            or events["node:" + source_id + ":terminal"].get("output") != expected
        ):
            raise WorkspaceError(409, "Transformation retained input receipt is inconsistent")
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
    terminal = retain_terminal(principal, identity, compiled, terminal)
    if terminal["state"] == "BUDGET_REFUSED":
        return terminal
    if succeeded:
        for output in compiled["outputs"]:
            if output["node_id"] == node_id:
                publication.stage(
                    principal, identity, 0, output["output_id"], "function-invocation/1", reference
                )
    return terminal


def retain_terminal(principal: Principal, identity: str, compiled: dict, terminal: dict) -> dict:
    """Commit measured usage once, atomically with the node's immutable terminal event."""
    node_id = terminal["node"]
    budget = compiled.get("resource_budget")
    succeeded = terminal["state"] == "COMPLETED"
    usage = (
        measured_usage(principal, terminal["output"]["run_id"])
        if succeeded and budget is not None
        else None
    )
    with records.scope_connection(principal) as conn:
        scope = records.set_scope(conn, principal)
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            ("transformation-review:" + str(principal.scope.tenant_id) + ":" + identity,),
        )
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,45))",
            (str(principal.scope.tenant_id) + ":" + identity,),
        )
        rows = conn.execute(
            "SELECT event_id,payload FROM workflow_events WHERE tenant_id=%s AND workflow_id=%s",
            (principal.scope.tenant_id, identity),
        ).fetchall()
        events = {row[0]: row[1] for row in rows}
        for key in ("node:" + node_id + ":terminal", "node:" + node_id + ":budget-refused"):
            if key in events:
                prior = events[key]
                if prior.get("output") != terminal["output"]:
                    raise WorkspaceError(
                        409, "Node terminal receipt conflicts with retained evidence"
                    )
                return prior
        key = "node:" + node_id + ":terminal"
        if usage is not None:
            assert budget is not None
            totals = cumulative_usage(list(events.values()), node_id, usage)
            terminal = {**terminal, "usage": usage}
            if exceeded_budget(totals, budget):
                key = "node:" + node_id + ":budget-refused"
                terminal = {
                    **terminal,
                    "state": "BUDGET_REFUSED",
                    "cumulative_usage": totals,
                    "resource_budget": budget,
                    "new_run_required": True,
                }
        conn.execute(
            "INSERT INTO workflow_events(tenant_id,workflow_id,exact_scope,event_id,payload) "
            "VALUES(%s,%s,%s,%s,%s)",
            (principal.scope.tenant_id, identity, Jsonb(scope), key, Jsonb(terminal)),
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
    compiled = retained["request"]["compiled_plan"]
    review = retained["publication_review"]
    binding_review = retained["binding_review"]
    if binding_review is not None and binding_review["state"] != "APPROVED":
        raise WorkspaceError(409, "Publication requires the canonical binding proposal approval")
    if review is not None and review["state"] != "APPROVED":
        raise WorkspaceError(409, "Publication requires its retained independent approval")
    if review is not None and not retained["publications"]:
        checker = records.current_principal(review["decision"]["actor_id"], context["scope"])
        require_permission(checker, "ontology_read")
        require_permission(checker, "review")
    if compiled.get("resource_budget") is not None:
        usage_events = [event for event in retained["events"] if event.get("state") == "COMPLETED"]
        if any("usage" not in event for event in usage_events) or exceeded_budget(
            cumulative_usage(usage_events), compiled["resource_budget"]
        ):
            raise WorkspaceError(409, "Transformation publication budget is not satisfied")
    from finai_api.services.transformation_bindings import record_event

    manifest = publication.publish(
        principal,
        context["workflow_id"],
        0,
        event_writer=record_event if binding_review is not None else records.event,
    )
    return {"publication_id": manifest["publication_id"], "generation": 0}
