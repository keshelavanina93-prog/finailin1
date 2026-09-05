"""User-asserted GIS imports retained in governed proposals, never silently accepted."""

import json
from datetime import datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from finai_api.domain.resources import ProposalDetail, ResourceMutation, ResourceProposal
from finai_api.domain.review import Principal
from finai_api.domain.spatial import validate_geojson
from finai_api.services import resources
from finai_api.services.operations_map import company_scope, snapshot


class SpatialImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    title: str = Field(min_length=3, max_length=200)
    rationale: str = Field(min_length=10, max_length=2000)
    valid_from: datetime
    geojson: dict[str, Any]

    @field_validator("geojson")
    @classmethod
    def valid_document(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_geojson(value)

    @field_validator("valid_from")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Effective timestamp must include a timezone")
        return value


def import_proposal(principal: Principal, request: SpatialImportRequest) -> ProposalDetail:
    rows, _, _, _ = snapshot(principal, request.valid_from, None)
    company_scope(rows, request.company_id)
    digest = sha256(
        json.dumps(
            request.geojson,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()
    source = ResourceMutation(
        object_type="SpatialImport",
        identity_key=f"gis:{request.company_id}:{digest}",
        display_name=request.title,
        valid_from=request.valid_from,
        evidence_class="USER_ASSERTED",
        attributes={
            "legal_entity_id": str(request.company_id),
            "document": request.geojson,
            "canonical_document_sha256": digest,
        },
    )
    mutations = [source]
    for feature in request.geojson["features"]:
        properties = feature["properties"]
        mutations.append(
            ResourceMutation(
                object_type="Location",
                identity_key=f"gis-location:{request.company_id}:{properties['code']}",
                display_name=properties["name"],
                valid_from=request.valid_from,
                evidence_class="USER_ASSERTED",
                attributes={
                    "code": properties["code"],
                    "geometry": feature["geometry"],
                    "legal_entity_id": str(request.company_id),
                    "spatial_import_id": str(source.resource_id),
                },
            )
        )
    proposal = ResourceProposal(
        title=request.title,
        rationale=request.rationale,
        access_entity=principal.scope.legal_entity_id,
        mutations=mutations,
    )
    return resources.propose(principal, proposal)
