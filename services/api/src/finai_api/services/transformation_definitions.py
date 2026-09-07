"""Compile reviewed Transformation definitions into bounded shared Function plans."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid5

from psycopg.rows import dict_row

from finai_api.domain.function_execution import FunctionDefinition, FunctionInvocation
from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.domain.resources import ResourceMutation
from finai_api.domain.review import Principal
from finai_api.domain.transformation import TransformationDefinition, TransformationRunRequest
from finai_api.security import require_permission
from finai_api.services import function_execution
from finai_api.services.certification import _current
from finai_api.services.resources import resource_connection
from finai_api.services.upstream_authority import upstream_authority
from finai_api.services.workspace import WorkspaceError


def validate_transformation(
    item: ResourceMutation, target: Callable[[str, str, str], dict]
) -> None:
    definition = TransformationDefinition.model_validate(item.attributes)
    for node in definition.definition.nodes:
        function = target(
            str(node.function_id), str(item.resource_id), "TRANSFORMATION_FUNCTION:" + node.node_id
        )
        if function["object_type"] != "FunctionDefinition":
            raise WorkspaceError(409, "Transformation nodes require canonical Function definitions")
        function_execution._check_implementation(
            FunctionDefinition.model_validate(function["attributes"])
        )


def plan(p: Principal, request: TransformationRunRequest) -> dict[str, Any]:
    require_permission(p, "ontology_read")
    if request.known_at > datetime.now(UTC):
        raise WorkspaceError(422, "Transformation knowledge time cannot be in the future")
    with resource_connection(p) as conn, conn.cursor(row_factory=dict_row) as c:
        resource = _current(c, p, request.transformation)
        if (
            resource["object_type"] != "TransformationDefinition"
            or resource["access_entity"] != p.scope.legal_entity_id
        ):
            raise WorkspaceError(409, "Transformation must belong to the selected company context")
        definition = TransformationDefinition.model_validate(resource["attributes"])
        dependencies = c.execute(
            "SELECT d.relation,v.* FROM resource_dependencies d JOIN resource_versions v "
            "ON v.tenant_id=d.tenant_id AND v.resource_id=d.target_resource_id "
            "AND v.version_id=d.target_version_id WHERE d.tenant_id=%s AND d.version_id=%s",
            (p.scope.tenant_id, request.transformation.version_id),
        ).fetchall()
        upstream_authority(c, p.scope.tenant_id, request.transformation.version_id)
    order = definition.definition.topological_order()
    definitions = {node.node_id: node for node in definition.definition.nodes}
    nodes = []
    for node_id in order:
        node = definitions[node_id]
        pins = [
            row for row in dependencies if row["relation"] == "TRANSFORMATION_FUNCTION:" + node_id
        ]
        if (
            len(pins) != 1
            or pins[0]["resource_id"] != node.function_id
            or pins[0]["object_type"] != "FunctionDefinition"
        ):
            raise WorkspaceError(409, "Transformation node lacks its exact canonical Function pin")
        reference = VersionReference(resource_id=node.function_id, version_id=pins[0]["version_id"])
        invocation = FunctionInvocation(
            request_id=uuid5(request.request_id, node_id),
            function=reference,
            valid_at=request.valid_at,
            known_at=request.known_at,
            offset=node.offset,
            limit=node.limit,
        )
        function_plan = function_execution.plan(p, invocation)
        nodes.append(
            {
                "node_id": node_id,
                "depends_on": sorted(node.depends_on),
                "function": function_execution._pin(pins[0]),
                "invocation": invocation.model_dump(mode="json"),
                "function_plan": function_plan,
            }
        )
    result = {
        "contract": "transformation-plan/1",
        "request": request.model_dump(mode="json"),
        "exact_scope": p.scope.model_dump(mode="json"),
        "transformation": function_execution._pin(resource),
        "mode": "EVIDENCE_ANALYSIS_ONLY",
        "dependency_semantics": "COMPLETION_BARRIER_ONLY",
        "node_order": order,
        "nodes": nodes,
        "outputs": [output.model_dump(mode="json") for output in definition.definition.outputs],
        "coverage": "DECLARED_QUERY_PAGES_ONLY",
        "business_effect_authorized": False,
        "current_use_authorized": False,
    }
    result["plan_hash"] = function_execution._digest(result)
    return result
