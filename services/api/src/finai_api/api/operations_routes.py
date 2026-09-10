from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Response

from finai_api.api.ontology_routes import User
from finai_api.domain.resources import ProposalDetail
from finai_api.security import require_permission
from finai_api.services import (
    operational_binding_validation,
    operations_map,
    petroleum_control,
    petroleum_reconciliation,
)
from finai_api.services.spatial_import import SpatialImportRequest
from finai_api.services.spatial_import import import_proposal as create_import

router = APIRouter(prefix="/v1/operations", tags=["operations and maps"])


@router.get("/map")
def map_view(
    principal: User,
    response: Response,
    lens: str = "enterprise_assets",
    bbox: Annotated[str | None, Query(max_length=100)] = None,
    valid_at: datetime | None = None,
    known_at: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
    company_id: UUID | None = None,
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return operations_map.map_view(principal, lens, bbox, valid_at, known_at, limit, company_id)


@router.get("/map/{resource_id}/connections")
def connections(
    principal: User,
    response: Response,
    resource_id: UUID,
    depth: Annotated[int, Query(ge=1, le=5)] = 2,
    valid_at: datetime | None = None,
    known_at: datetime | None = None,
    company_id: UUID | None = None,
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return operations_map.connections(principal, resource_id, depth, valid_at, known_at, company_id)


@router.get("/petroleum/reconciliation")
def petroleum_reconciliation_view(
    principal: User, company_id: UUID | None = None
) -> dict[str, Any]:
    return petroleum_reconciliation.reconcile(principal, company_id)


@router.get("/petroleum/variances")
def petroleum_variances_view(
    principal: User,
    company_id: UUID | None = None,
    valid_at: datetime | None = None,
    known_at: datetime | None = None,
) -> dict[str, Any]:
    return petroleum_reconciliation.variances(principal, company_id, valid_at, known_at)


@router.post("/petroleum/variances/investigations")
def petroleum_investigation(
    principal: User, request: petroleum_control.InvestigationRequest
) -> dict[str, Any]:
    return petroleum_control.start(principal, request)


@router.get("/petroleum/variances/investigations/{control_id}")
def petroleum_investigation_read(principal: User, control_id: str) -> dict[str, Any]:
    return petroleum_control.read(principal, control_id)


@router.post("/petroleum/variances/investigations/{control_id}/decision")
def petroleum_investigation_decision(
    principal: User, control_id: str, request: petroleum_control.ControlDecisionRequest
) -> dict[str, Any]:
    return petroleum_control.decide(principal, control_id, request)


@router.post("/petroleum/variances/investigations/{control_id}/execute")
def petroleum_action_execute(principal: User, control_id: str) -> dict[str, Any]:
    return petroleum_control.execute(principal, control_id)


@router.get("/petroleum/margin")
def petroleum_margin_view(principal: User, company_id: UUID | None = None) -> dict[str, Any]:
    return petroleum_reconciliation.margin(principal, company_id)


@router.get("/petroleum/movement-journal-reconciliation")
def movement_journal_reconciliation_view(
    principal: User, company_id: UUID | None = None
) -> dict[str, Any]:
    return petroleum_reconciliation.movement_journal_reconciliation(principal, company_id)


@router.get("/petroleum/telemetry")
def petroleum_telemetry_view(principal: User, company_id: UUID | None = None) -> dict[str, Any]:
    return petroleum_reconciliation.telemetry(principal, company_id)


@router.get("/petroleum/lineage/{resource_id}")
def petroleum_lineage_view(
    principal: User, resource_id: UUID, company_id: UUID | None = None
) -> dict[str, Any]:
    return petroleum_reconciliation.lineage(principal, resource_id, company_id)


@router.get("/petroleum/intake/{receipt_id}/validation")
def petroleum_intake_validation(principal: User, receipt_id: str) -> dict[str, Any]:
    return operational_binding_validation.validate(principal, receipt_id)


@router.get("/petroleum/intake/{receipt_id}/promotion-preview")
def petroleum_intake_promotion_preview(principal: User, receipt_id: str) -> dict[str, Any]:
    return operational_binding_validation.promotion_preview(principal, receipt_id)


@router.post("/petroleum/intake/{receipt_id}/promotion-proposal")
def petroleum_intake_promotion_proposal(principal: User, receipt_id: str) -> dict[str, Any]:
    detail = operational_binding_validation.submit_governed_proposal(principal, receipt_id)
    return detail.model_dump(mode="json")


@router.post("/import-proposal", response_model=ProposalDetail)
def import_proposal(principal: User, request: SpatialImportRequest) -> ProposalDetail:
    require_permission(principal, "ontology_propose")
    return create_import(principal, request)
