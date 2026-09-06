import base64
import binascii
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from finai_api.domain.authority import ExactScope


class IngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scope: ExactScope
    filename: str = Field(min_length=1, max_length=256)
    csv_text: str | None = Field(default=None, min_length=1, max_length=1_000_000)
    xls_base64: str | None = Field(default=None, min_length=1, max_length=5_333_336)
    xlsx_base64: str | None = Field(default=None, min_length=1, max_length=21_333_336)
    source_use: Literal[
        "ACTUAL_INPUT", "HISTORICAL_REFERENCE", "REPORT_TEMPLATE", "MAPPING_REFERENCE"
    ] = "ACTUAL_INPUT"
    requested_objects: tuple[str, ...] = ()
    context_version_id: UUID | None = None
    account_version_ids: dict[str, UUID] = Field(default_factory=dict, max_length=10000)
    source_system: str | None = Field(default=None, min_length=1, max_length=128)
    inspection_version: Literal[
        "source-inspection/1", "source-inspection/2", "source-inspection/3"
    ] = "source-inspection/3"
    account_alias_version_ids: dict[str, UUID] = Field(default_factory=dict, max_length=10000)
    account_dimension_rule_version_ids: dict[str, tuple[UUID, ...]] = Field(
        default_factory=dict, max_length=10000
    )
    dimension_member_version_ids: dict[str, dict[str, UUID]] = Field(
        default_factory=dict, max_length=100
    )

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        if sum(x is not None for x in (self.csv_text, self.xls_base64, self.xlsx_base64)) != 1:
            raise ValueError("Provide exactly one CSV, XLS or XLSX source")
        if self.xlsx_base64 is not None:
            try:
                content = base64.b64decode(self.xlsx_base64, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ValueError("Invalid XLSX encoding") from exc
            if not 0 < len(content) <= 16_000_000 or not content.startswith(b"PK\x03\x04"):
                raise ValueError("Choose an XLSX workbook no larger than 16 MB")
        if self.xls_base64 is not None:
            try:
                content = base64.b64decode(self.xls_base64, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ValueError("Invalid XLS encoding") from exc
            if not 0 < len(content) <= 4_000_000 or not content.startswith(
                bytes.fromhex("d0cf11e0a1b11ae1")
            ):
                raise ValueError("Choose a BIFF XLS workbook no larger than 4 MB")
        return self

    def source_bytes(self) -> bytes:
        if self.xlsx_base64 is not None:
            return base64.b64decode(self.xlsx_base64, validate=True)
        if self.xls_base64 is not None:
            return base64.b64decode(self.xls_base64, validate=True)
        assert self.csv_text is not None
        return self.csv_text.encode("utf-8")

    @model_serializer(mode="wrap")
    def serialize_request(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        result: dict[str, Any] = handler(self)
        if self.csv_text is not None:
            result.pop("inspection_version", None)
        if self.xlsx_base64 is None:
            result.pop("xlsx_base64", None)
        if self.source_use == "ACTUAL_INPUT":
            result.pop("source_use", None)
        if self.xls_base64 is None:
            result.pop("xls_base64", None)
        if self.csv_text is None:
            result.pop("csv_text", None)
        if self.source_system is None:
            result.pop("source_system", None)
        if not self.account_alias_version_ids:
            result.pop("account_alias_version_ids", None)
        for field in ("account_dimension_rule_version_ids", "dimension_member_version_ids"):
            if not getattr(self, field):
                result.pop(field, None)
        return result


class CanonicalReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    resource_id: UUID
    version_id: UUID


class Candidate(BaseModel):
    canonical_references: dict[str, CanonicalReference] = Field(default_factory=dict)
    object_type: str
    source_row: int
    epistemic_state: Literal["OBSERVED", "DERIVED"]
    values: dict[str, str]
    function: str | None = None
    authority_state: Literal["MAPPED_CANDIDATE"] = "MAPPED_CANDIDATE"


class SourceRetention(BaseModel):
    """Storage classification; does not assert a legal retention period or hold."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    contract_version: Literal["source-retention/1"] = "source-retention/1"
    artifact_class: Literal["IMMUTABLE_SOURCE_EVIDENCE"] = "IMMUTABLE_SOURCE_EVIDENCE"
    disposition: Literal["PRESERVE_PENDING_GOVERNED_DISPOSITION"] = (
        "PRESERVE_PENDING_GOVERNED_DISPOSITION"
    )
    automatic_expiry_allowed: Literal[False] = False
    legal_policy_state: Literal["NOT_ESTABLISHED"] = "NOT_ESTABLISHED"


class SourceStorage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    backend: Literal["S3"] = "S3"
    bucket: str = Field(min_length=1, max_length=255)
    object_key: str = Field(min_length=1, max_length=1024)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    byte_length: int = Field(ge=1, le=32_000_000)
    version_id: str | None = Field(default=None, max_length=1024)
    retention: SourceRetention | None = None


class IngestReceipt(BaseModel):
    source_storage: SourceStorage | None = None
    receipt_id: str
    request_sha256: str
    context_version_id: UUID | None = None
    canonical_references: dict[str, CanonicalReference] = Field(default_factory=dict)
    binding_state: Literal["SOURCE_ONLY", "CANONICAL_BOUND"] = "SOURCE_ONLY"
    source_sha256: str
    scope: ExactScope
    source_class: Literal["TRIAL_BALANCE", "UNFAMILIAR_TABULAR", "WORKBOOK_PACKAGE"]
    source_profile: dict[str, Any] = Field(default_factory=dict)
    process_steps: tuple[dict[str, Any], ...] = ()
    classifier_version: str = "csv-header-classifier/1"
    classifier_confidence: Literal["STRUCTURAL_ONLY"] = "STRUCTURAL_ONLY"
    authority_contract_version: str
    pack_version: str
    compiler_version: str = "hydration/1"
    plan: tuple[str, ...]
    observed_bindings: dict[str, str]
    inferred_bindings: tuple[str, ...] = ()
    used_fields: tuple[str, ...]
    unused_fields: tuple[str, ...]
    candidates: tuple[Candidate, ...]
    rejects: tuple[str, ...]
    warnings: tuple[str, ...]
    reconciliation: dict[str, str]
    functions_executed: tuple[str, ...]
    deepest_authentic_drill: Literal["SOURCE_ROW"] = "SOURCE_ROW"
    authority_state: Literal["MAPPED_CANDIDATE"] = "MAPPED_CANDIDATE"
    model_version: None = None
    prompt_version: None = None
