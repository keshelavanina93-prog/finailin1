import csv
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from finai_api.domain.ingest import IngestRequest
from finai_api.domain.resources import (
    CanonicalResource,
    ProposalDetail,
    ResourceProposal,
    ResourceReview,
)
from finai_api.domain.review import Principal
from finai_api.security import authenticated_principal, require_permission
from finai_api.services import resources
from finai_api.services.enterprise_reference import socar_reference
from finai_api.services.historical_graph import historical_graph
from finai_api.services.ingest_binding import context_accounts
from finai_api.services.ingestion import SourceAuthorityDenied, compile_source
from finai_api.services.resource_rollback import RollbackRequest, rollback_draft
from finai_api.services.workspace import WorkspaceError

router = APIRouter(prefix="/v1/ontology", tags=["shared ontology and identity"])


def reader(principal: Annotated[Principal, Depends(authenticated_principal)]) -> Principal:
    require_permission(principal, "ontology_read")
    return principal


User = Annotated[Principal, Depends(reader)]


@router.post("/rollback-proposal", response_model=ResourceProposal)
def rollback_proposal(principal: User, request: RollbackRequest) -> ResourceProposal:
    require_permission(principal, "ontology_propose")
    return rollback_draft(principal, request)


@router.post("/reference-proposal", response_model=ProposalDetail)
def reference_proposal(principal: User) -> ProposalDetail:
    require_permission(principal, "ontology_admin")
    require_permission(principal, "ontology_propose")
    return resources.propose(principal, socar_reference(principal))


@router.get("/graph")
def graph(principal: User) -> dict[str, Any]:
    nodes = resources.list_resources(principal, None, "", 0, limit=1000)
    return {"resources": nodes, "bounded": len(nodes) == 1000, "limit": 1000}


@router.get("/catalog", response_model=list[CanonicalResource])
def catalog(principal: User) -> list[CanonicalResource]:
    return resources.catalog(principal)


@router.get("/resources", response_model=list[CanonicalResource])
def list_resources(
    principal: User,
    object_type: str | None = None,
    search: Annotated[str, Query(max_length=128)] = "",
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
    valid_at: datetime | None = None,
    known_at: datetime | None = None,
) -> list[CanonicalResource]:
    if any(value and value.tzinfo is None for value in (valid_at, known_at)):
        raise WorkspaceError(422, "Historical timestamps must include a timezone")
    return resources.list_resources(principal, object_type, search, offset, valid_at, known_at)


@router.get("/resources/{resource_id}")
def resource(principal: User, resource_id: UUID) -> dict[str, Any]:
    return resources.get_resource(principal, resource_id)


@router.get("/resolve/{resource_id}")
def resolve(
    principal: User,
    resource_id: UUID,
    known_at: datetime | None = None,
    valid_at: datetime | None = None,
) -> dict[str, Any]:
    if any(value and value.tzinfo is None for value in (known_at, valid_at)):
        raise WorkspaceError(422, "Historical timestamps must include a timezone")
    return resources.resolve_identity(principal, resource_id, known_at, valid_at)


@router.get("/aliases")
def aliases(
    principal: User,
    source_system: Annotated[str, Query(max_length=128)],
    external_id: Annotated[str, Query(max_length=256)],
) -> list[dict[str, Any]]:
    return resources.aliases(principal, source_system, external_id)


@router.get("/context")
def context(principal: User) -> dict[str, Any]:
    return resources.context_binding(principal)


@router.get("/proposals")
def proposals(principal: User) -> list[dict[str, Any]]:
    return resources.proposals(principal)


@router.get("/proposals/{proposal_id}", response_model=ProposalDetail)
def proposal(principal: User, proposal_id: UUID) -> ProposalDetail:
    return resources.proposal_detail(principal, proposal_id)


@router.get("/proposals/{proposal_id}/promotion-check")
def promotion_check(principal: User, proposal_id: UUID) -> dict[str, Any]:
    return resources.promotion_check(principal, proposal_id)


@router.post("/proposals", response_model=ProposalDetail)
def propose(principal: User, request: ResourceProposal) -> ProposalDetail:
    require_permission(principal, "ontology_propose")
    try:
        return resources.propose(principal, request)
    except (ValueError, KeyError, TypeError) as exc:
        raise WorkspaceError(422, "Invalid resource/schema definition: " + str(exc)) from exc


@router.post("/proposals/{proposal_id}/decision", response_model=ProposalDetail)
def review(principal: User, proposal_id: UUID, request: ResourceReview) -> ProposalDetail:
    require_permission(principal, "ontology_review")
    try:
        return resources.review(principal, proposal_id, request)
    except (ValueError, KeyError, TypeError) as exc:
        raise WorkspaceError(422, "Invalid resource/schema definition: " + str(exc)) from exc


@router.get("/context/accounts")
def account_choices(
    principal: User,
    context_version_id: UUID,
    offset: Annotated[int, Query(ge=0, le=1000000)] = 0,
) -> dict[str, Any]:
    return context_accounts(principal, context_version_id, offset)


@router.post("/context/source-accounts")
def source_accounts(principal: User, request: IngestRequest) -> dict[str, Any]:
    require_permission(principal, "ingest")
    if request.scope != principal.scope:
        raise WorkspaceError(403, "Exact scope does not match credential")
    if request.context_version_id is not None:
        context_accounts(principal, request.context_version_id)
    try:
        receipt = compile_source(request)
    except SourceAuthorityDenied as exc:
        raise WorkspaceError(403, str(exc)) from exc
    except (ValueError, csv.Error) as exc:
        raise WorkspaceError(422, str(exc)) from exc
    return {
        "source_class": receipt.source_class,
        "observed_bindings": receipt.observed_bindings,
        "dimension_values": {
            field.removeprefix("dimension:"): sorted({
                candidate.values[field] for candidate in receipt.candidates
                if field in candidate.values and candidate.values[field].strip()
            }) for field in receipt.used_fields if field.startswith("dimension:")
        },
        "rejects": receipt.rejects,
        "warnings": receipt.warnings,
        "account_codes": sorted(
            {
                candidate.values["account_code"]
                for candidate in receipt.candidates
                if candidate.object_type == "Account"
            }
        ),
    }


@router.get("/resources/{resource_id}/graph")
def resource_history_graph(
    principal: User,
    resource_id: UUID,
    valid_at: datetime | None = None,
    known_at: datetime | None = None,
) -> dict[str, Any]:
    return historical_graph(principal, resource_id, valid_at=valid_at, known_at=known_at)
