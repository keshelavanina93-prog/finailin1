from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from finai_api.domain.authority import ExactScope
from finai_api.domain.ingest import Candidate, IngestReceipt


class Principal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    actor_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    scope: ExactScope
    permissions: tuple[
        Literal[
            "read",
            "ingest",
            "review",
            "export",
            "ontology_read",
            "ontology_propose",
            "ontology_review",
            "ontology_admin",
        ],
        ...,
    ] = ("read",)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    decision: Literal["APPROVED", "REJECTED"]
    reason: str = Field(min_length=10, max_length=2000)
    idempotency_key: UUID
    expected_head: str | None = Field(default=None, max_length=128)

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("Review rationale needs at least 10 non-padding characters")
        return value


class ReviewDecision(BaseModel):
    decision_id: UUID
    receipt_id: str
    decision: Literal["APPROVED", "REJECTED"]
    actor_id: str
    reason: str
    previous_head: str | None
    decided_at: datetime


class IntakeItem(BaseModel):
    receipt_id: str
    filename: str
    source_class: str
    source_sha256: str
    submitted_by: str | None
    ingested_at: datetime
    candidate_count: int
    reject_count: int
    reconciliation_status: str
    review_state: Literal["PENDING", "APPROVED", "REJECTED"]
    is_current: bool


class ReceiptDetail(BaseModel):
    receipt: IngestReceipt
    filename: str
    submitted_by: str | None
    ingested_at: datetime
    decision: ReviewDecision | None
    current_head: str | None
    approval_blockers: tuple[str, ...]
    impact: dict[str, int]


class WorkspaceObject(BaseModel):
    object_id: str
    receipt_id: str
    object_index: int
    object_type: str
    source_row: int
    epistemic_state: Literal["OBSERVED", "DERIVED"]
    values: dict[str, str]
    function: str | None = None
    authority_state: Literal["APPROVED"] = "APPROVED"


class ObjectDetail(BaseModel):
    object: WorkspaceObject
    scope: ExactScope
    source_sha256: str
    source_row_values: dict[str, str]
    decision: ReviewDecision
    is_current: bool


class WorkspaceSummary(BaseModel):
    scope: ExactScope
    pending_count: int
    approved_count: int
    rejected_count: int
    active_versions: list[dict[str, str]]


def approval_blockers(
    receipt: IngestReceipt, submitted_by: str | None, principal: Principal
) -> tuple[str, ...]:
    blockers: list[str] = []
    if "review" not in principal.permissions:
        blockers.append("This identity has no review permission.")
    if not submitted_by:
        blockers.append(
            "Legacy intake has no submitter identity; re-ingest with an identified user."
        )
    elif submitted_by == principal.actor_id:
        blockers.append("A different reviewer must approve this construction.")
    if receipt.rejects:
        blockers.append("Rejected rows must be resolved in a new source version.")
    if not receipt.candidates:
        blockers.append("No candidate objects were constructed.")
    if receipt.source_class == "TRIAL_BALANCE" and receipt.reconciliation.get("status") != "PASS":
        blockers.append("Trial balance reconciliation has not passed.")
    return tuple(blockers)


def workspace_object(receipt_id: str, index: int, candidate: Candidate) -> WorkspaceObject:
    return WorkspaceObject(
        object_id=f"{receipt_id}:{index}",
        receipt_id=receipt_id,
        object_index=index,
        **candidate.model_dump(exclude={"authority_state"}),
    )
