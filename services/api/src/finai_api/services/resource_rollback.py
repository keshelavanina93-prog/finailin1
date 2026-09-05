"""Restore retained definitions through normal independent review; never rewrite history."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field, field_validator

from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.domain.review import Principal
from finai_api.services.workspace import WorkspaceError


class RollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: UUID = Field(default_factory=uuid4)
    versions: dict[UUID, UUID] = Field(min_length=1, max_length=100)
    rationale: str = Field(min_length=10, max_length=2000)
    valid_from: datetime

    @field_validator("valid_from")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Rollback effective time must include a timezone")
        return value


def validate_restoration(
    conn: psycopg.Connection[Any], principal: Principal, proposal: ResourceProposal
) -> None:
    mutations = {item.resource_id: item for item in proposal.mutations}
    if not set(proposal.restores_versions).issubset(mutations):
        raise WorkspaceError(422, "Rollback provenance must identify a proposed resource")
    with conn.cursor(row_factory=dict_row) as cursor:
        for resource_id, version_id in proposal.restores_versions.items():
            old = cursor.execute(
                "SELECT * FROM resource_versions WHERE tenant_id=%s "
                "AND resource_id=%s AND version_id=%s",
                (principal.scope.tenant_id, resource_id, version_id),
            ).fetchone()
            if old is None:
                raise WorkspaceError(404, "Rollback version not found in authorized context")
            item = mutations[resource_id]
            if old["authority_state"] != "APPROVED" or any(
                getattr(item, field) != old[field]
                for field in (
                    "object_type",
                    "display_name",
                    "attributes",
                    "evidence_class",
                    "authority_state",
                )
            ):
                raise WorkspaceError(
                    409, "Rollback must restore retained approved definition content"
                )
            dependencies = cursor.execute(
                "SELECT d.target_resource_id,d.target_version_id,h.version_id AS current_version "
                "FROM resource_dependencies d LEFT JOIN resource_heads h "
                "ON h.tenant_id=d.tenant_id AND h.resource_id=d.target_resource_id "
                "WHERE d.tenant_id=%s AND d.version_id=%s",
                (principal.scope.tenant_id, version_id),
            ).fetchall()
            for dependency in dependencies:
                target = dependency["target_resource_id"]
                retained = dependency["target_version_id"]
                if target in mutations:
                    if proposal.restores_versions.get(target) != retained:
                        raise WorkspaceError(
                            409, "Rollback must include the retained dependency definition"
                        )
                elif dependency["current_version"] != retained:
                    raise WorkspaceError(
                        409, "Rollback dependency changed; include its retained version"
                    )


def rollback_draft(principal: Principal, request: RollbackRequest) -> ResourceProposal:
    from finai_api.services.resources import resource_connection

    if "ontology_propose" not in principal.permissions:
        raise WorkspaceError(403, "Ontology proposal permission required")
    mutations: list[ResourceMutation] = []
    with resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cursor:
        conn.execute(
            "SELECT pg_advisory_xact_lock_shared(hashtextextended(%s,0))",
            (f"canonical:{principal.scope.tenant_id}",),
        )
        for resource_id, version_id in request.versions.items():
            row = cursor.execute(
                "SELECT v.*,i.identity_key,h.version_id AS current_version "
                "FROM resource_versions v "
                "JOIN canonical_identities i USING(tenant_id,resource_id) "
                "JOIN resource_heads h USING(tenant_id,resource_id) "
                "WHERE v.tenant_id=%s AND v.resource_id=%s AND v.version_id=%s",
                (principal.scope.tenant_id, resource_id, version_id),
            ).fetchone()
            if row is None:
                raise WorkspaceError(404, "Rollback version not found in authorized context")
            mutations.append(
                ResourceMutation(
                    resource_id=resource_id,
                    expected_version_id=row["current_version"],
                    access_entity=row["access_entity"],
                    object_type=row["object_type"],
                    identity_key=row["identity_key"],
                    display_name=row["display_name"],
                    attributes=row["attributes"],
                    evidence_class=row["evidence_class"],
                    valid_from=request.valid_from,
                )
            )
        scopes = {item.access_entity for item in mutations}
        envelope = next(iter(scopes)) if len(scopes) == 1 else "__TENANT__"
        if (
            envelope != principal.scope.legal_entity_id
            and "ontology_admin" not in principal.permissions
        ):
            raise WorkspaceError(403, "Rollback requires ontology administration for this scope")
        proposal = ResourceProposal(
            proposal_id=request.proposal_id,
            title="Restore retained canonical definitions",
            rationale=request.rationale,
            access_entity=envelope or "__TENANT__",
            mutations=mutations,
            restores_versions=request.versions,
        )
        validate_restoration(conn, principal, proposal)
        return proposal
