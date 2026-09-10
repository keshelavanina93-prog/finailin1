"""Read-only enterprise target diagnosis over the caller's authorized resource graph."""

import base64
from collections.abc import Callable
from decimal import Decimal
from mimetypes import guess_type
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict

from finai_api.domain.calculation_graph import CalculationGraph
from finai_api.domain.enterprise_diagnostics import DiagnosticRequest
from finai_api.domain.executable_enterprise_model import (
    ExecutablePreflightRequest,
    resolve_function,
)
from finai_api.domain.multidimensional_runtime import (
    CalculationBlock,
    Coordinate,
    DimensionalSignature,
    IntersectionSet,
    compile_sparse_plan,
    execute_sparse_decimal_plan,
)
from finai_api.domain.nyx_reasoning import ReasonRequest
from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.domain.review import Principal
from finai_api.domain.workspace_projections import (
    WorkspaceSelection,
    eligible_projections,
    normalize_projection_rows,
    projection_catalog,
    replay_timestamp,
)
from finai_api.security import authenticated_principal, require_permission
from finai_api.services import (
    accounting_source_document,
    enterprise_diagnostics,
    executable_function_registry,
    nyx_reasoning,
    operations_map,
    planning,
)
from finai_api.services.workspace import WorkspaceError


class CalculationCompileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    graph: CalculationGraph
    signatures: tuple[DimensionalSignature, ...] = ()
    blocks: tuple[CalculationBlock, ...] = ()
    intersections: tuple[IntersectionSet, ...] = ()
    changed_nodes: tuple[str, ...] = ()
    changed_coordinates: tuple[Coordinate, ...] = ()


class SparseValueInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    coordinate: Coordinate
    value: Decimal


class CalculationExecuteRequest(CalculationCompileRequest):
    values: tuple[SparseValueInput, ...] = ()
    target: str = "UNSPECIFIED"
    input_pins: tuple[str, ...] = ()
    valid_at: str | None = None
    known_at: str | None = None


class ProjectionDataRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    projection_id: str
    selection: WorkspaceSelection


router = APIRouter(prefix="/v1/workspace", tags=["enterprise diagnostics"])


def reader(principal: Annotated[Principal, Depends(authenticated_principal)]) -> Principal:
    require_permission(principal, "read")
    require_permission(principal, "ontology_read")
    return principal


User = Annotated[Principal, Depends(reader)]


def preflight_reader(
    principal: Annotated[Principal, Depends(authenticated_principal)],
) -> Principal:
    """A preflight is a read-only contract evaluation, not ontology discovery."""

    require_permission(principal, "read")
    return principal


ReadUser = Annotated[Principal, Depends(preflight_reader)]


@router.get("/diagnostic-targets")
def diagnostic_targets(principal: User, response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return enterprise_diagnostics.catalog()


@router.post("/diagnostics")
def diagnose_target(
    request: DiagnosticRequest, principal: User, response: Response
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return enterprise_diagnostics.diagnose(principal, request)


@router.post("/executable-preflight")
def executable_preflight(
    request: ExecutablePreflightRequest, principal: ReadUser, response: Response
) -> dict[str, object]:
    """Evaluate an executable dependency contract without changing enterprise state."""

    response.headers["Cache-Control"] = "no-store"
    function = (
        executable_function_registry.get_registered_function(request.function_id)
        if request.function_id is not None
        else request.function
    )
    assert function is not None
    result = resolve_function(function, request.available)
    return {
        "preflight": result.model_dump(mode="json"),
        "function": function.model_dump(mode="json"),
        "registry_state": (
            "AUTHORITATIVE_REGISTERED"
            if request.function_id is not None
            else "REQUEST_SUPPLIED_CONTRACT"
        ),
        "authority_effect": "NONE",
    }


@router.get("/executable-functions")
def executable_functions(principal: ReadUser, response: Response) -> dict[str, object]:
    """List server-registered executable verbs without executing any verb."""

    response.headers["Cache-Control"] = "no-store"
    return {
        "contract": "executable-function-registry/1",
        "functions": [
            item.model_dump(mode="json")
            for item in executable_function_registry.list_registered_functions()
        ],
        "authority_effect": "NONE",
    }


@router.get("/projections/catalog")
def projections_catalog(principal: ReadUser, response: Response) -> dict[str, object]:
    """Return the server-owned projection registry; no projection executes here."""

    response.headers["Cache-Control"] = "no-store"
    return {
        "contract": "workspace-projection-catalog/1",
        "projections": projection_catalog(),
        "authority_effect": "NONE",
    }


@router.post("/projections/selection")
def project_selection(
    selection: WorkspaceSelection, principal: ReadUser, response: Response
) -> dict[str, object]:
    """Validate and echo an exact selection for downstream projection requests."""

    response.headers["Cache-Control"] = "no-store"
    return {
        "contract": "workspace-selection/1",
        "selection": selection.model_dump(mode="json"),
        "scope_state": "EXACT_CONTEXT_REQUIRED",
        "eligible_projections": eligible_projections(selection),
        "authority_effect": "NONE",
    }


@router.post("/projections/data")
def projection_data(
    request: ProjectionDataRequest, principal: ReadUser, response: Response
) -> dict[str, object]:
    """Read a real governed projection using the validated exact selection."""

    response.headers["Cache-Control"] = "no-store"
    eligible = {item["projection_id"]: item for item in eligible_projections(request.selection)}
    projection = eligible.get(request.projection_id)
    if projection is None:
        raise WorkspaceError(
            409, "Projection is unavailable for the selected workspace and exact context"
        )
    try:
        replay_as_of = replay_timestamp(request.selection)
    except ValueError as exc:
        raise WorkspaceError(422, str(exc)) from exc

    if request.projection_id in {"planning-grid", "formatted-table", "executive-kpi"}:
        catalog = planning.catalog(principal)
        company_id = str(principal.scope.legal_entity_id)
        rows = []
        for item in catalog["cells"]:
            attrs = item["attributes"]
            if request.selection.scenario_id and str(
                attrs.get("scenario_version_id")
            ) != request.selection.scenario_id:
                continue
            if request.selection.period and str(attrs.get("period_id")) != (
                request.selection.period
            ):
                continue
            rows.append(item)
        return {
            "contract": "workspace-projection-data/1",
            "projection": projection,
            "selection": request.selection.model_dump(mode="json"),
            "data_state": "ACCEPTED_CANONICAL",
            "rows": rows,
            "normalized_rows": [
                item.model_dump(mode="json") for item in normalize_projection_rows(rows)
            ],
            "scope": {"company_id": company_id},
            "authority_effect": "NONE",
        }

    if request.projection_id == "field-input":
        field_labels = {
            "company_id": "Company",
            "facility_id": "Facility",
            "tank_id": "Tank",
            "product_id": "Product",
            "station_id": "Station",
            "period": "Period",
            "scenario_id": "Scenario",
            "version_id": "Version",
            "comparison_baseline": "Comparison baseline",
            "replay_as_of": "Replay as of",
        }
        rows = [
            {
                "row_id": f"selection:{field}",
                "label": label,
                "field": field,
                "value": value,
                "authority_state": "SELECTION_CONTEXT",
            }
            for field, label in field_labels.items()
            if (value := request.selection.model_dump().get(field)) is not None
        ]
        return {
            "contract": "workspace-projection-data/1",
            "projection": projection,
            "selection": request.selection.model_dump(mode="json"),
            "data_state": "ACCEPTED_CANONICAL",
            "rows": rows,
            "normalized_rows": [
                item.model_dump(mode="json") for item in normalize_projection_rows(rows)
            ],
            "coverage": "workspace-selection/1",
            "scope": {"company_id": request.selection.company_id},
            "authority_effect": "NONE",
        }

    if request.projection_id == "action-control":
        action_rows = [
            {
                "row_id": "action:scope",
                "label": "Action scope",
                "field": "scope",
                "value": request.selection.selected_object_id or "No selected workflow",
                "authority_state": "ACTION_CONTEXT",
            },
            {
                "row_id": "action:approval",
                "label": "Approval state",
                "field": "approval_state",
                "value": "APPROVAL_REQUIRED",
                "authority_state": "ACTION_CONTEXT",
            },
            {
                "row_id": "action:execution",
                "label": "External execution",
                "field": "execution",
                "value": "NOT_PERMITTED_FROM_PROJECTION",
                "authority_state": "ACTION_CONTEXT",
            },
            {
                "row_id": "action:readback",
                "label": "Readback",
                "field": "readback",
                "value": "REQUIRED_AFTER_APPROVED_ACTION",
                "authority_state": "ACTION_CONTEXT",
            },
        ]
        return {
            "contract": "workspace-projection-data/1",
            "projection": projection,
            "selection": request.selection.model_dump(mode="json"),
            "data_state": "CONTEXT_ONLY",
            "rows": action_rows,
            "normalized_rows": [
                item.model_dump(mode="json") for item in normalize_projection_rows(action_rows)
            ],
            "coverage": "workflow/control",
            "scope": {"company_id": request.selection.company_id},
            "authority_effect": "NONE",
        }

    if request.projection_id == "nyx-context":
        if not request.selection.selected_object_id or not request.selection.version_id:
            return {
                "contract": "workspace-projection-data/1",
                "projection": projection,
                "selection": request.selection.model_dump(mode="json"),
                "data_state": "UNAVAILABLE_REQUIRED_CONTEXT",
                "rows": [],
                "authority_effect": "NONE",
            }
        try:
            selected = VersionReference(
                resource_id=UUID(request.selection.selected_object_id),
                version_id=UUID(request.selection.version_id),
            )
        except ValueError:
            return {
                "contract": "workspace-projection-data/1",
                "projection": projection,
                "selection": request.selection.model_dump(mode="json"),
                "data_state": "UNAVAILABLE_REQUIRED_CONTEXT",
                "rows": [],
                "authority_effect": "NONE",
            }
        explanation = nyx_reasoning.reason(
            principal,
            ReasonRequest(
                question="Explain the selected evidence and its authority boundary.",
                selected=selected,
                known_at=replay_as_of,
            ),
        )
        rows = [
            {
                "row_id": "nyx:answer",
                "label": "NYX explanation",
                "field": "answer",
                "value": explanation["answer"],
                "authority_state": explanation["state"],
            },
            {
                "row_id": "nyx:state",
                "label": "Reasoning state",
                "field": "state",
                "value": explanation["state"],
                "authority_state": explanation["state"],
            },
        ]
        if explanation.get("refusal_code"):
            rows.append(
                {
                    "row_id": "nyx:refusal",
                    "label": "Refusal code",
                    "field": "refusal_code",
                    "value": explanation["refusal_code"],
                    "authority_state": explanation["state"],
                }
            )
        return {
            "contract": "workspace-projection-data/1",
            "projection": projection,
            "selection": request.selection.model_dump(mode="json"),
            "data_state": "CONTEXT_ONLY",
            "rows": rows,
            "normalized_rows": [
                item.model_dump(mode="json") for item in normalize_projection_rows(rows)
            ],
            "coverage": explanation["contract"],
            "scope": {"company_id": request.selection.company_id},
            "authority_effect": "NONE",
        }

    if request.projection_id == "operations-map":
        try:
            map_result = operations_map.map_view(
                principal,
                lens="enterprise_assets",
                valid_at=None,
                known_at=replay_as_of,
                limit=500,
                company_id=UUID(request.selection.company_id),
            )
        except ValueError as exc:
            raise WorkspaceError(
                422, "Company scope must be a valid identifier for map data"
            ) from exc
        return {
            "contract": "workspace-projection-data/1",
            "projection": projection,
            "selection": request.selection.model_dump(mode="json"),
            "data_state": "ACCEPTED_CANONICAL",
            "rows": map_result.get("features", []),
            "normalized_rows": [
                item.model_dump(mode="json")
                for item in normalize_projection_rows(map_result.get("features", []))
            ],
            "coverage": map_result.get("contract", "operations-map/1"),
            "scope": {"company_id": request.selection.company_id},
            "authority_effect": "NONE",
        }

    if request.projection_id in {"movement-network", "hierarchy-drilldown"}:
        if not request.selection.selected_object_id:
            return {
                "contract": "workspace-projection-data/1",
                "projection": projection,
                "selection": request.selection.model_dump(mode="json"),
                "data_state": "UNAVAILABLE_REQUIRED_CONTEXT",
                "rows": [],
                "authority_effect": "NONE",
            }
        try:
            network_result = operations_map.connections(
                principal,
                UUID(request.selection.selected_object_id),
                2,
                None,
                replay_as_of,
                UUID(request.selection.company_id),
            )
        except ValueError as exc:
            raise WorkspaceError(
                422, "Selected object and company scope must be valid identifiers"
            ) from exc
        return {
            "contract": "workspace-projection-data/1",
            "projection": projection,
            "selection": request.selection.model_dump(mode="json"),
            "data_state": "ACCEPTED_CANONICAL",
            "rows": network_result.get("edges", []),
            "normalized_rows": [
                item.model_dump(mode="json")
                for item in normalize_projection_rows(network_result.get("edges", []))
            ],
            "coverage": network_result.get("contract", "operations-connections/1"),
            "scope": {"company_id": request.selection.company_id},
            "authority_effect": "NONE",
        }

    if request.selection.scenario_id and request.selection.comparison_baseline:
        try:
            comparison = planning.compare(
                principal,
                UUID(request.selection.scenario_id),
                UUID(request.selection.comparison_baseline),
            )
        except ValueError as exc:
            raise WorkspaceError(
                422, "Scenario and comparison baseline must be valid identifiers"
            ) from exc
        return {
            "contract": "workspace-projection-data/1",
            "projection": projection,
            "selection": request.selection.model_dump(mode="json"),
            "data_state": "ACCEPTED_DETERMINISTIC_COMPARISON",
            "rows": comparison["rows"],
            "normalized_rows": [
                item.model_dump(mode="json")
                for item in normalize_projection_rows(comparison["rows"])
            ],
            "coverage": comparison["coverage"],
            "authority_effect": "NONE",
        }
    if request.projection_id == "image-evidence":
        identity = request.selection.selected_object_id
        if not identity or not (identity.startswith("doc_") or identity.startswith("ir_")):
            return {
                "contract": "workspace-projection-data/1",
                "projection": projection,
                "selection": request.selection.model_dump(mode="json"),
                "data_state": "UNAVAILABLE_REQUIRED_CONTEXT",
                "rows": [],
                "authority_effect": "NONE",
            }
        metadata, content = accounting_source_document.read_source(principal, identity)
        filename = str(metadata.get("filename", ""))
        media_type = guess_type(filename)[0] or "application/octet-stream"
        if not media_type.startswith("image/") or len(content) > 5_000_000:
            return {
                "contract": "workspace-projection-data/1",
                "projection": projection,
                "selection": request.selection.model_dump(mode="json"),
                "data_state": "UNAVAILABLE_AUTHORITY_PAYLOAD",
                "rows": [],
                "authority_effect": "NONE",
            }
        rows = [
            {
                "row_id": f"image:{identity}",
                "label": "Retained evidence image",
                "field": "filename",
                "value": filename,
                "authority_state": "RETAINED_EVIDENCE",
            },
            {
                "row_id": f"image-hash:{identity}",
                "label": "Source SHA-256",
                "field": "sha256",
                "value": metadata.get("source_sha256"),
                "authority_state": "RETAINED_EVIDENCE",
            },
        ]
        return {
            "contract": "workspace-projection-data/1",
            "projection": projection,
            "selection": request.selection.model_dump(mode="json"),
            "data_state": "ACCEPTED_CANONICAL",
            "rows": rows,
            "normalized_rows": [
                item.model_dump(mode="json") for item in normalize_projection_rows(rows)
            ],
            "media": {
                "data_url": f"data:{media_type};base64,{base64.b64encode(content).decode('ascii')}",
                "media_type": media_type,
                "sha256": metadata.get("source_sha256"),
            },
            "coverage": "retained-image/1",
            "scope": {"company_id": request.selection.company_id},
            "authority_effect": "NONE",
        }
    return {
        "contract": "workspace-projection-data/1",
        "projection": projection,
        "selection": request.selection.model_dump(mode="json"),
        "data_state": "UNAVAILABLE_REQUIRED_COMPARISON_CONTEXT",
        "rows": [],
        "authority_effect": "NONE",
    }


@router.post("/calculation/compile")
def compile_calculation(
    request: CalculationCompileRequest, principal: ReadUser, response: Response
) -> dict[str, object]:
    """Compile a sparse physical plan without executing or promoting values."""

    response.headers["Cache-Control"] = "no-store"
    plan = compile_sparse_plan(
        request.graph,
        request.signatures,
        request.blocks,
        request.intersections,
        request.changed_nodes,
        request.changed_coordinates,
    )
    return {
        "contract": "calculation-compile/1",
        "plan": plan.model_dump(mode="json"),
        "authority_effect": "NONE",
        "execution_performed": False,
    }


@router.post("/calculation/execute")
def execute_calculation(
    request: CalculationExecuteRequest, principal: ReadUser, response: Response
) -> dict[str, object]:
    """Execute a compiled sparse plan with owner-registered Decimal operators.

    The request carries values and graph metadata only. It cannot provide a
    formula or callable; the closed registry below is the only executable
    surface. Results remain derived candidates and never mutate authority.
    """

    response.headers["Cache-Control"] = "no-store"
    plan = compile_sparse_plan(
        request.graph,
        request.signatures,
        request.blocks,
        request.intersections,
        request.changed_nodes,
        request.changed_coordinates,
    )
    values = {
        (item.node_id, item.coordinate): item.value
        for item in request.values
    }
    if len(values) != len(request.values):
        plan = plan.model_copy(
            update={"state": "BLOCKED", "refusal_reason": "Duplicate sparse value identity"}
        )
    result = execute_sparse_decimal_plan(
        plan,
        request.graph,
        values,
        _SAFE_DECIMAL_EVALUATORS,
        target=request.target,
        input_pins=request.input_pins,
        valid_at=request.valid_at,
        known_at=request.known_at,
    )
    return {
        "contract": "calculation-execute/1",
        "result": result.model_dump(mode="json"),
        "authority_effect": "NONE",
        "execution_performed": result.state.value != "BLOCKED",
    }


def _decimal_add(*values: Decimal) -> Decimal:
    return sum(values, Decimal(0))


def _decimal_subtract(left: Decimal, right: Decimal) -> Decimal:
    return left - right


def _decimal_multiply(left: Decimal, right: Decimal) -> Decimal:
    return left * right


def _decimal_divide(left: Decimal, right: Decimal) -> Decimal:
    if right == 0:
        raise ValueError("Division by zero")
    return left / right


_SAFE_DECIMAL_EVALUATORS: dict[str, Callable[..., Decimal]] = {
    "add": _decimal_add,
    "subtract": _decimal_subtract,
    "multiply": _decimal_multiply,
    "divide": _decimal_divide,
}
