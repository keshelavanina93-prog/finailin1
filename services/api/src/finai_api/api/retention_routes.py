"""Retention evaluation is preserved evidence, never a deletion command."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from finai_api.domain.artifact_retention import (
    ArtifactReference,
    RetentionEvaluationRequest,
    RetentionHistoryRequest,
    RetentionPolicyDiscoveryRequest,
)
from finai_api.domain.review import Principal
from finai_api.security import authenticated_principal
from finai_api.services import artifact_retention
from finai_api.services.artifact_references import resolve_artifact

router = APIRouter(prefix="/v1/ontology/retention", tags=["artifact preservation"])
User = Annotated[Principal, Depends(authenticated_principal)]


class ArtifactInspection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact: ArtifactReference


@router.post("/inspect")
def inspect(principal: User, request: ArtifactInspection) -> dict[str, Any]:
    return {
        "artifact": resolve_artifact(principal, request.artifact),
        "execution_authorized": False,
        "legal_compliance_established": False,
    }


@router.post("/evaluations")
def evaluate(principal: User, request: RetentionEvaluationRequest) -> dict[str, Any]:
    return artifact_retention.evaluate(principal, request)


@router.get("/receipts/{evaluation_id}")
def history(principal: User, evaluation_id: UUID) -> dict[str, Any]:
    return artifact_retention.history(principal, evaluation_id)


@router.post("/history")
def artifact_history(principal: User, request: RetentionHistoryRequest) -> dict[str, Any]:
    return artifact_retention.artifact_history(principal, request)


@router.post("/policies")
def policies(principal: User, request: RetentionPolicyDiscoveryRequest) -> dict[str, Any]:
    return artifact_retention.discover_policies(principal, request)
