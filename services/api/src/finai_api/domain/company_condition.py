"""Read-only company connections and independently observed retained work."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from finai_api.domain.resources import CanonicalResource


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Connection(Model):
    record: CanonicalResource
    relation: CanonicalResource
    source: CanonicalResource
    target: CanonicalResource


class ResourceGroup(Model):
    state: Literal["AVAILABLE", "EMPTY"]
    resources: list[CanonicalResource]
    coverage: Literal["EXPLICIT_CONNECTED_RESOURCE_SNAPSHOT"] = (
        "EXPLICIT_CONNECTED_RESOURCE_SNAPSHOT"
    )
    reason: str


class LicenceEvidence(Model):
    binding: CanonicalResource
    notice: CanonicalResource | None
    licence: CanonicalResource | None


class CompanyWorkItem(Model):
    workflow_id: str
    proposal_id: UUID | None
    company_id: UUID
    title: str
    state: Literal["PREPARED", "PENDING_REVIEW", "PUBLISHED", "REJECTED"]
    created_at: AwareDatetime
    reason: str
    basis: Literal["EXPLICIT_INVOCATION"] = "EXPLICIT_INVOCATION"


class CompanyWork(Model):
    state: Literal["AVAILABLE", "UNAVAILABLE"] = "AVAILABLE"
    reason: str | None = None
    observed_at: AwareDatetime
    authority: Literal["CURRENT_RETAINED_WORK"] = "CURRENT_RETAINED_WORK"
    items: list[CompanyWorkItem] = Field(max_length=25)
    truncated: bool
    limit: Literal[25] = 25


class UnavailableCondition(Model):
    key: Literal[
        "financial_performance", "live_operations", "findings", "investigations",
        "regulatory_compliance",
    ]
    label: str
    reason: str


class CompanyConditionDescriptor(Model):
    contract: Literal["g8-company-condition/1"] = "g8-company-condition/1"
    company: CanonicalResource
    valid_at: AwareDatetime
    known_at: AwareDatetime
    connection_depth: Literal[2] = 2
    connections: list[Connection]
    assets: ResourceGroup
    parties: ResourceGroup
    contracts: ResourceGroup
    products: ResourceGroup
    licence_evidence: list[LicenceEvidence]
    work: CompanyWork
    unavailable: list[UnavailableCondition]
    current_use_authorized: Literal[False] = False
    business_effect_authorized: Literal[False] = False
