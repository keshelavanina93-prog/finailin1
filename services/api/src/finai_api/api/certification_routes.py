"""Retained, narrowly scoped definition-conformance evidence."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends

from finai_api.domain.certification import CertificationEvaluationRequest
from finai_api.domain.review import Principal
from finai_api.security import authenticated_principal
from finai_api.services import certification

router = APIRouter(prefix="/v1/ontology/certifications", tags=["definition conformance"])
User = Annotated[Principal, Depends(authenticated_principal)]


@router.post("/evaluations")
def evaluate(principal: User, request: CertificationEvaluationRequest) -> dict[str, Any]:
    return certification.evaluate(principal, request)


@router.get("/receipts/{receipt_id}")
def history(principal: User, receipt_id: UUID) -> dict[str, Any]:
    return certification.history(principal, receipt_id)
