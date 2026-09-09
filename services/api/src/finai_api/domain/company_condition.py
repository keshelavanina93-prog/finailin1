"""Read-only company connections and independently observed retained work."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

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


class CompanyJournalReviewItem(Model):
    request_id: UUID
    proposal_id: UUID
    company_id: UUID
    invocation_id: UUID
    coordinate: str = Field(min_length=1, max_length=512)
    title: str = Field(max_length=200)
    state: Literal["PREPARED", "PENDING_REVIEW", "PUBLISHED", "REJECTED"]
    created_at: AwareDatetime
    reason: str = Field(max_length=2000)
    basis: Literal["EXPLICIT_JOURNAL_PRODUCTION_REQUEST"] = "EXPLICIT_JOURNAL_PRODUCTION_REQUEST"


class CompanyJournalReviews(Model):
    state: Literal["AVAILABLE", "UNAVAILABLE"] = "AVAILABLE"
    reason: str | None = None
    observed_at: AwareDatetime
    authority: Literal["CURRENT_CANONICAL_JOURNAL_REVIEW"] = "CURRENT_CANONICAL_JOURNAL_REVIEW"
    items: list[CompanyJournalReviewItem] = Field(max_length=25)
    truncated: bool
    limit: Literal[25] = 25


class UnavailableCondition(Model):
    key: Literal[
        "financial_performance",
        "live_operations",
        "findings",
        "investigations",
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
    journal_reviews: CompanyJournalReviews
    unavailable: list[UnavailableCondition]
    current_use_authorized: Literal[False] = False
    business_effect_authorized: Literal[False] = False


class DefinitionPin(Model):
    resource_id: UUID
    version_id: UUID
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class CompanyOperatingResourceGroup(Model):
    key: str
    label: str
    definition: CanonicalResource
    definition_pins: list[DefinitionPin] = Field(min_length=1, max_length=201)
    state: Literal["AVAILABLE", "EMPTY", "UNAVAILABLE"]
    resources: list[CanonicalResource]
    valid_at: AwareDatetime
    known_at: AwareDatetime
    count: int | None = Field(ge=0)
    count_basis: Literal["EXPLICIT_CONNECTED_RESOURCE_SNAPSHOT"] = (
        "EXPLICIT_CONNECTED_RESOURCE_SNAPSHOT"
    )
    completeness: Literal["COMPLETE_WITHIN_CONNECTION_SNAPSHOT", "UNAVAILABLE"]
    reason: str

    @model_validator(mode="after")
    def exact_definition_pin(self) -> "CompanyOperatingResourceGroup":
        identities = [pin.resource_id for pin in self.definition_pins]
        if len(identities) != len(set(identities)):
            raise ValueError("Group definition dependency resource identities must be unique")
        own = [
            pin for pin in self.definition_pins if pin.resource_id == self.definition.resource_id
        ]
        if (
            len(own) != 1
            or own[0].version_id != self.definition.version_id
            or own[0].content_hash != self.definition.content_hash
        ):
            raise ValueError(
                "Group requires exactly one matching definition identity/version/hash pin"
            )
        return self


class CompanyConditionDescriptorV2(Model):
    contract: Literal["g8-company-condition/2"] = "g8-company-condition/2"
    company: CanonicalResource
    valid_at: AwareDatetime
    known_at: AwareDatetime
    connection_depth: Literal[2] = 2
    connections: list[Connection]
    resource_groups: list[CompanyOperatingResourceGroup]
    resource_groups_state: Literal["AVAILABLE", "UNAVAILABLE"]
    resource_groups_reason: str | None
    licence_evidence: list[LicenceEvidence]
    work: CompanyWork
    journal_reviews: CompanyJournalReviews
    unavailable: list[UnavailableCondition]
    current_use_authorized: Literal[False] = False
    business_effect_authorized: Literal[False] = False
