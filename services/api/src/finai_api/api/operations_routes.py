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


@router.get("/petroleum/margin")
def petroleum_margin_view(principal: User, company_id: UUID | None = None) -> dict[str, Any]:
    return petroleum_reconciliation.margin(principal, company_id)


@router.get("/petroleum/movement-journal-reconciliation")
def movement_journal_reconciliation_view(
    principal: User, company_id: UUID | None = None
) -> dict[str, Any]:
    return petroleum_reconciliation.movement_journal_reconciliation(principal, company_id)


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


@router.post("/import-proposal", response_model=ProposalDetail)
def import_proposal(principal: User, request: SpatialImportRequest) -> ProposalDetail:
    require_permission(principal, "ontology_propose")
    return create_import(principal, request)
