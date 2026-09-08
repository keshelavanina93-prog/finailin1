"""Reviewed compatibility keeps source identity separate from publication semantics."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CompatibilityDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract: Literal["source-journal-compatibility/1"]
    source_profile: str = Field(min_length=1)
    source_family: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    binding_version_id: UUID
    scope_version_id: UUID
    sheet: str = Field(min_length=1)
    grain: Literal["SOURCE_ROW"]
    amount_field: Literal["source_amount"]
    amount_column: str = Field(min_length=1)
    amount_header: str = Field(min_length=1)
    amount_semantics: Literal["DEBIT_CREDIT"]
    vat_treatment: Literal["AS_POSTED"]
    row_identity: Literal["RECORDER_AND_LINE"]
    amount_conversion: Literal["NONE"]
    rationale: str = Field(min_length=20, max_length=2000)
