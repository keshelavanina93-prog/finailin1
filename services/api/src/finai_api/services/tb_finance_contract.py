"""Generic contract guard for 1C turnover trial-balance finance inputs.

The contract is deliberately a pure validation boundary.  It permits a
trial-balance source to feed account-period draft finance facts, while making
the unsupported interpretations explicit.  It never reads or writes the
resource store and it never creates a journal, invoice, or operating fact.
"""

import re
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from finai_api.services.workspace import WorkspaceError

CONTRACT_ID = "1c_turnover_trial_balance@v1"
PROFILE = "account_period_tb_finance"
SOURCE_CLASS = "1C_TURNOVER_TRIAL_BALANCE"
INPUT_GRAIN = "ACCOUNT_PERIOD"
SOURCE_FAMILY = "1C_ACCOUNT_PERIOD"

_ALLOWED_OPERATIONS = frozenset({"inspect", "classify", "draft", "export", "validate"})
_ALLOWED_INPUTS = frozenset(
    {
        "AccountPeriodFact",
        "TbMonthStatement",
        "TbAccountLine",
        "TbSubkontoLine",
        "SourceFamily",
        "SourcePeriodSnapshot",
        "SourceRecord",
        "ChartPack",
        "AccountClassificationProposal",
    }
)
_ALLOWED_OUTPUTS = frozenset(
    {
        "ACCOUNT_PERIOD",
        "AccountPeriodFact",
        "StatementDraft",
        "tb_statement_draft@v1",
        "ContinuityFinding",
        "CashBridgeFromTb",
        "InventoryValueDraft",
        "ReceivablesByAnalyticDraft",
        "PayablesDebtDraft",
        "NOT_CERTIFIED_EXPORT",
    }
)
_ALLOWED_CURRENCY_STATES = frozenset({"UNREVIEWED", "SOURCE_AMOUNT", "REVIEWED"})

# Values are normalized before lookup so callers cannot bypass the guard with
# punctuation, case, or a namespace prefix (for example ``finance.JournalLine``).
_FORBIDDEN_ALIASES: dict[str, str] = {
    "canonicaljournalentry": "canonical journal entry",
    "journalentry": "journal entry",
    "canonicaljournalline": "canonical journal line",
    "journalline": "journal line",
    "postedjournal": "posted journal",
    "invoice": "invoice",
    "invoiceline": "invoice line",
    "receivableaging": "receivables aging",
    "receivablesaging": "receivables aging",
    "payableaging": "payables aging",
    "payablesaging": "payables aging",
    "agingbucket": "aging buckets",
    "aging": "aging",
    "overduebyinvoice": "invoice aging",
    "overdue": "overdue-by-invoice",
    "tankdipfact": "tank-dip fact",
    "tankdip": "tank dips",
    "truckdispatchfact": "truck dispatch fact",
    "truckdispatch": "truck dispatch",
    "waybill": "truck waybills",
    "liter": "liters",
    "liters": "liters",
    "litre": "liters",
    "litres": "liters",
    "density": "density",
    "productmargin": "product margin",
    "productmarginfact": "product margin",
    "livecondition": "live conditions",
    "livemap": "live map",
    "stockout": "stockout",
    "cashflowstatement": "cash-flow statement",
    "statementofcashflows": "cash-flow statement",
    "cashflow": "cash-flow statement",
}


class TbFinanceContractRequest(BaseModel):
    """A bounded, generic request to validate TB Finance use."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    contract_id: str = Field(
        default=CONTRACT_ID,
        min_length=1,
        max_length=128,
        validation_alias=AliasChoices("contract_id", "contract"),
    )
    profile: str = Field(
        min_length=1,
        max_length=128,
        validation_alias=AliasChoices("profile", "input_profile", "source_profile"),
    )
    input_grain: str = Field(
        default=INPUT_GRAIN,
        min_length=1,
        max_length=64,
        validation_alias=AliasChoices("input_grain", "grain"),
    )
    source_class: str = Field(default=SOURCE_CLASS, min_length=1, max_length=128)
    source_family: str = Field(default=SOURCE_FAMILY, min_length=1, max_length=128)
    operation: str = Field(default="draft", min_length=1, max_length=64)
    requested_objects: tuple[str, ...] = Field(
        default=(),
        max_length=100,
        validation_alias=AliasChoices("requested_objects", "requested_object_types", "objects"),
    )
    requested_object: str | None = Field(default=None, max_length=128)
    requested_outputs: tuple[str, ...] = Field(
        default=(),
        max_length=100,
        validation_alias=AliasChoices("requested_outputs", "outputs"),
    )
    requested_output: str | None = Field(default=None, max_length=128)
    currency_status: str = Field(
        default="UNREVIEWED",
        min_length=1,
        max_length=64,
        validation_alias=AliasChoices("currency_status", "currency_state"),
    )


class TbFinanceContractDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_id: Literal["1c_turnover_trial_balance@v1"] = "1c_turnover_trial_balance@v1"
    profile: Literal["account_period_tb_finance"] = "account_period_tb_finance"
    source_class: Literal["1C_TURNOVER_TRIAL_BALANCE"] = "1C_TURNOVER_TRIAL_BALANCE"
    source_family: Literal["1C_ACCOUNT_PERIOD"] = "1C_ACCOUNT_PERIOD"
    input_grain: Literal["ACCOUNT_PERIOD"] = "ACCOUNT_PERIOD"
    operation: str
    requested_objects: tuple[str, ...]
    requested_outputs: tuple[str, ...]
    currency_status: str
    accepted: Literal[True] = True
    authority_state: Literal["DRAFT_INPUT"] = "DRAFT_INPUT"
    amount_unit: Literal["source_amount"] = "source_amount"
    accounting_use_authorized: Literal[False] = False
    business_effect_authorized: Literal[False] = False
    canonical_journal_created: Literal[False] = False
    financial_certification: None = None
    reason: str


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _forbidden_capability(value: str) -> str | None:
    normalized = _normalize(value)
    for alias, label in _FORBIDDEN_ALIASES.items():
        if alias in normalized:
            return label
    return None


def _values(request: TbFinanceContractRequest) -> tuple[str, ...]:
    return tuple(
        value
        for value in (
            *request.requested_objects,
            request.requested_object,
            *request.requested_outputs,
            request.requested_output,
        )
        if value
    )


def contract_definition() -> dict[str, Any]:
    """Return the immutable public contract description for registry/UI use."""

    return {
        "contract_id": CONTRACT_ID,
        "version": "1",
        "profile": PROFILE,
        "source_class": SOURCE_CLASS,
        "input_grain": INPUT_GRAIN,
        "source_family": SOURCE_FAMILY,
        "allowed_input_objects": sorted(_ALLOWED_INPUTS),
        "allowed_outputs": sorted(_ALLOWED_OUTPUTS),
        "currency_policy": "UNREVIEWED_OR_SOURCE_AMOUNT",
        "authority_state": "DRAFT_INPUT",
        "accounting_use_authorized": False,
        "business_effect_authorized": False,
        "canonical_journal_created": False,
        "forbidden_capabilities": sorted(set(_FORBIDDEN_ALIASES.values())),
        "guarantees": [
            "ACCOUNT_PERIOD facts retain source-row lineage and exact source hashes",
            "Month turnover is usable for draft calculations after separate review",
            "Month-end balances remain snapshots and are never summed across periods",
            "TB rows never become canonical journals, invoices, or operational facts",
        ],
    }


def validate(request: TbFinanceContractRequest | dict[str, Any]) -> TbFinanceContractDecision:
    """Validate a TB Finance input without creating or promoting any resource."""

    try:
        parsed = (
            request
            if isinstance(request, TbFinanceContractRequest)
            else TbFinanceContractRequest.model_validate(request)
        )
    except ValueError as exc:
        raise WorkspaceError(422, "Invalid 1C turnover trial-balance contract input") from exc

    if parsed.contract_id != CONTRACT_ID:
        raise WorkspaceError(422, f"TB Finance requires contract {CONTRACT_ID}")
    if parsed.profile != PROFILE:
        raise WorkspaceError(
            422,
            f"TB Finance accepts only profile {PROFILE}; raw or SEG profiles are not inputs",
        )
    if parsed.input_grain != INPUT_GRAIN:
        raise WorkspaceError(
            422, "1C turnover trial balance must enter Finance at ACCOUNT_PERIOD grain"
        )
    if parsed.source_class != SOURCE_CLASS:
        raise WorkspaceError(422, f"TB Finance requires source class {SOURCE_CLASS}")
    if parsed.source_family != SOURCE_FAMILY:
        raise WorkspaceError(422, f"TB Finance requires source family {SOURCE_FAMILY}")
    if parsed.operation not in _ALLOWED_OPERATIONS:
        raise WorkspaceError(422, f"Unsupported TB Finance operation: {parsed.operation}")
    if parsed.currency_status not in _ALLOWED_CURRENCY_STATES:
        raise WorkspaceError(
            422,
            "TB Finance keeps amounts as source_amount until a reviewed currency decision exists",
        )

    values = _values(parsed)
    for value in values:
        forbidden = _forbidden_capability(value)
        if forbidden:
            raise WorkspaceError(
                422,
                f"{CONTRACT_ID} forbids {forbidden}; a trial balance cannot supply "
                "that source family",
            )

    unsupported_inputs = sorted(
        value for value in parsed.requested_objects if value not in _ALLOWED_INPUTS
    )
    if parsed.requested_object and parsed.requested_object not in _ALLOWED_INPUTS:
        unsupported_inputs.append(parsed.requested_object)
    if unsupported_inputs:
        raise WorkspaceError(
            422,
            "TB Finance accepts only account-period inputs; unsupported object(s): "
            + ", ".join(sorted(set(unsupported_inputs))),
        )

    unsupported_outputs = sorted(
        value for value in parsed.requested_outputs if value not in _ALLOWED_OUTPUTS
    )
    if parsed.requested_output and parsed.requested_output not in _ALLOWED_OUTPUTS:
        unsupported_outputs.append(parsed.requested_output)
    if unsupported_outputs:
        raise WorkspaceError(
            422,
            "TB Finance accepts only account-period draft outputs; unsupported output(s): "
            + ", ".join(sorted(set(unsupported_outputs))),
        )

    return TbFinanceContractDecision(
        operation=parsed.operation,
        requested_objects=tuple(parsed.requested_objects)
        + ((parsed.requested_object,) if parsed.requested_object else ()),
        requested_outputs=tuple(parsed.requested_outputs)
        + ((parsed.requested_output,) if parsed.requested_output else ()),
        currency_status=parsed.currency_status,
        reason=(
            "Accepted as a source-linked ACCOUNT_PERIOD draft input; no canonical "
            "authority is created"
        ),
    )


def validate_input(request: TbFinanceContractRequest | dict[str, Any]) -> dict[str, Any]:
    """JSON-friendly service boundary used by the API and non-HTTP consumers."""

    return validate(request).model_dump(mode="json")


ContractRequest = Annotated[TbFinanceContractRequest, Field(description=CONTRACT_ID)]
