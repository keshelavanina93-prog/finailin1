"""A company Home composes existing authorities; it does not create financial facts."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from finai_api.domain.resources import CanonicalResource
from finai_api.domain.semantic_analysis import Projection


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CompanyHomeRequest(Model):
    company_id: UUID
    invocation_ids: list[UUID] = Field(default_factory=list, max_length=6)
    valid_at: AwareDatetime | None = None
    known_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def distinct_results(self) -> "CompanyHomeRequest":
        if len(set(self.invocation_ids)) != len(self.invocation_ids):
            raise ValueError("Home selections must reference distinct retained invocations")
        return self


class HomeOperations(Model):
    lens: Literal["gas_network", "enterprise_assets"]
    authority: Literal["GEOGRAPHY_CONTEXT_ONLY"] = "GEOGRAPHY_CONTEXT_ONLY"
    valid_at: AwareDatetime
    known_at: AwareDatetime
    domain_pack_ids: list[UUID]
    limitation: str


class MissingFinancial(Model):
    key: Literal["profit_loss", "balance_sheet", "cash_flow", "working_capital"]
    label: str
    reason: str


class CompanyHomeDescriptor(Model):
    contract: Literal["g8-company-home/1"] = "g8-company-home/1"
    company: CanonicalResource
    company_label: str
    valid_at: AwareDatetime
    known_at: AwareDatetime
    domain_packs: list[CanonicalResource]
    analyses: list[Projection] = Field(max_length=6)
    operations: HomeOperations
    unavailable_financials: list[MissingFinancial]
    current_use_authorized: Literal[False] = False
    business_effect_authorized: Literal[False] = False
