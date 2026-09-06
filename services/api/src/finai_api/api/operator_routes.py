"""Operator trace uses the same historical dependency authority as engineering."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter

from finai_api.api.ontology_routes import User
from finai_api.security import require_permission
from finai_api.services.historical_graph import historical_graph
from finai_api.services.operator_inspection import inspect

router = APIRouter(prefix="/v1/ontology/operator", tags=["operator trace"])


@router.get("/resources/{resource_id}")
def inspect_resource(
    resource_id: UUID,
    principal: User,
    version_id: UUID | None = None,
    known_at: datetime | None = None,
):
    return inspect(principal, resource_id, version_id, known_at)


@router.get("/trace/{resource_id}")
def trace(resource_id: UUID, version_id: UUID, principal: User, known_at: datetime | None = None):
    require_permission(principal, "ontology_read")
    return historical_graph(principal, resource_id, root_version_id=version_id, known_at=known_at)
