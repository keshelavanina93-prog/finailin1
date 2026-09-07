"""A transformation waits on the existing canonical binding proposal decision."""

from uuid import UUID, uuid5

from psycopg.types.json import Jsonb
from temporalio import activity

from finai_api.domain.function_execution import RetainedResultInput
from finai_api.domain.object_sets import ObjectSetQuery
from finai_api.domain.resources import ResourceProposal
from finai_api.domain.review import Principal
from finai_api.services import function_invocations, ontology_operations
from finai_api.services import report_workflows as records
from finai_api.services.workspace import WorkspaceError

EVENT = "binding-review:prepared"


def record_event(principal: Principal, identity: str, event_id: str, payload: dict) -> None:
    from finai_api.services.resources import resource_connection

    # Canonical decision reads in the SQL guard use existing caller grants.
    with resource_connection(principal) as conn:
        scope = records.set_scope(conn, principal)
        conn.execute(
            "INSERT INTO workflow_events(tenant_id,workflow_id,exact_scope,event_id,payload) "
            "VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (principal.scope.tenant_id, identity, Jsonb(scope), event_id, Jsonb(payload)),
        )


def source_receipt(principal, retained):
    compiled = retained["request"]["compiled_plan"]
    spec = compiled["binding_review"]
    nodes = {node["node_id"]: node for node in compiled["nodes"]}
    terminals = {
        event.get("node"): event
        for event in retained["events"]
        if event.get("state") == "COMPLETED"
    }
    if set(terminals) != set(nodes):
        raise WorkspaceError(409, "Binding review requires every Function node completed")
    node = nodes.get(spec["source_node_id"])
    if node is None:
        raise WorkspaceError(409, "Binding review source node is unavailable")
    receipt = function_invocations.history(principal, UUID(node["invocation"]["request_id"]))
    expected = {
        "invocation_id": receipt["invocation_id"],
        "receipt_hash": receipt["receipt_hash"],
        "run_id": receipt.get("receipt", {}).get("run_id"),
    }
    if (
        receipt["status"] != "SUCCEEDED"
        or terminals[spec["source_node_id"]].get("output") != expected
    ):
        raise WorkspaceError(
            409, "Binding review source differs from the completed Function receipt"
        )
    return receipt, expected


def projection(principal, retained):
    compiled = retained["request"]["compiled_plan"]
    spec = compiled.get("binding_review")
    if spec is None:
        return None
    request_id = str(uuid5(UUID(compiled["request"]["request_id"]), "binding-review"))
    if spec.get("operation_request_id") != request_id:
        raise WorkspaceError(409, "Binding review operation identity integrity failed")
    result = {
        **spec,
        "state": "NOT_REQUESTED",
        "operation_id": None,
        "proposal_id": None,
        "input_result": None,
        "decision": None,
        "reviewed_by": None,
        "proposal_history_independent": True,
    }
    prepared = next((e for e in retained["events"] if e["event_id"] == EVENT), None)
    if prepared:
        receipt, refs = source_receipt(principal, retained)
        operation_id = "opa_" + ontology_operations.digest(
            [principal.scope.model_dump(mode="json"), retained["actor_id"], request_id]
        )
        operation = ontology_operations.read(principal, operation_id)
        record = records.read(principal, operation_id)
        invocation = ontology_operations.BindingAction.model_validate(
            record["request"]["invocation"]
        )
        if (
            str(invocation.request_id) != request_id
            or str(invocation.binding_id) != spec["binding"]["resource_id"]
            or str(invocation.binding_version_id) != spec["binding"]["version_id"]
            or invocation.rationale != spec["rationale"]
            or invocation.input_result is None
            or str(invocation.input_result.invocation_id) != refs["invocation_id"]
            or invocation.query != ObjectSetQuery.model_validate(receipt["output"]["query"])
            or record["actor_id"] != retained["actor_id"]
            or prepared.get("state") != "PENDING"
            or prepared.get("operation_id") != operation_id
            or prepared.get("proposal_id") != operation["prepared_proposal_id"]
            or prepared.get("source_node_id") != spec["source_node_id"]
            or prepared.get("input_result") != refs
        ):
            raise WorkspaceError(409, "Retained binding review evidence integrity failed")
        proposal = operation.get("proposal")
        if proposal is None:
            raise WorkspaceError(409, "Prepared binding review canonical proposal is unavailable")
        if ResourceProposal.model_validate(proposal["proposal"]) != ResourceProposal.model_validate(
            record["request"]["prepared_proposal"]
        ):
            raise WorkspaceError(
                409, "Binding review canonical proposal differs from the retained operation"
            )
        metadata = proposal["proposal"].get("calculated_bindings", {})
        if not metadata or any(
            m.get("receipt_hash") != refs["receipt_hash"]
            or m.get("run_id") != refs["run_id"]
            or m.get("input_result") != {"invocation_id": refs["invocation_id"]}
            for m in metadata.values()
        ):
            raise WorkspaceError(
                409, "Binding review proposal does not retain its exact source receipt"
            )
        decision = proposal.get("decision")
        if decision not in (None, "APPROVED", "REJECTED"):
            raise WorkspaceError(409, "Binding review canonical decision is invalid")
        result.update(
            state=decision or "PENDING",
            decision=decision,
            reviewed_by=proposal.get("reviewed_by"),
            operation_id=operation_id,
            proposal_id=operation["prepared_proposal_id"],
            input_result=refs,
        )
    if any(event.get("command") == "cancel" for event in retained["events"]):
        result["state"] = "CANCELLED"
    return result


@activity.defn(name="transformation_binding_review")
def prepare(context: dict) -> dict:
    from finai_api.services import transformation_runs as runs

    principal, retained = runs._context(context)
    review = retained["binding_review"]
    if review is None:
        return {"state": "NOT_REQUESTED"}
    if review["state"] != "NOT_REQUESTED":
        return review
    receipt, refs = source_receipt(principal, retained)
    action = ontology_operations.BindingAction(
        request_id=review["operation_request_id"],
        binding_id=review["binding"]["resource_id"],
        binding_version_id=review["binding"]["version_id"],
        rationale=review["rationale"],
        query=receipt["output"]["query"],
        input_result=RetainedResultInput(invocation_id=refs["invocation_id"]),
    )
    operation = ontology_operations.invoke(principal, action)
    payload = {
        "state": "PENDING",
        "operation_id": operation["operation_id"],
        "proposal_id": operation["prepared_proposal_id"],
        "source_node_id": review["source_node_id"],
        "input_result": refs,
    }
    record_event(principal, context["workflow_id"], EVENT, payload)
    return runs.read(principal, context["workflow_id"])["binding_review"]
