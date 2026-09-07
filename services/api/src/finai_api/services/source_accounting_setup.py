"""Explicit user-asserted accounting structure through canonical independent review."""

import re
from datetime import UTC, date, datetime
from typing import Annotated
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator, model_validator

from finai_api.domain.authority import canonical_sha256
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ProposalRequestBinding, ResourceMutation, ResourceProposal
from finai_api.security import require_permission
from finai_api.services import resources, source_accounting_context
from finai_api.services.source_company_alias import _effective_resources
from finai_api.services.workspace import WorkspaceError

Code = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")]
Name = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^\S(?:.*\S)?$")]


class ExistingSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    resource_id: UUID


class NewCalendar(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: Code
    name: Name


class NewPeriod(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: Name
    starts_on: date
    ends_on: date

    @field_validator("starts_on", "ends_on", mode="before")
    @classmethod
    def strict_date(cls, value):
        if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
            raise ValueError("Fiscal period dates require YYYY-MM-DD")
        return value

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.ends_on < self.starts_on:
            raise ValueError("Fiscal period end must not precede its start")
        return self


class SetupSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: UUID
    ledger_code: Code
    ledger_name: Name
    book_code: Code
    book_name: Name
    currency_id: UUID | None = None
    currency_code: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    calendar: ExistingSelection | NewCalendar
    period: ExistingSelection | NewPeriod
    rationale: str = Field(min_length=10, max_length=2000)

    @model_validator(mode="after")
    def explicit_currency(self):
        if (self.currency_id is None) == (self.currency_code is None):
            raise ValueError("Choose exactly one currency resource or explicit currency code")
        return self

    @field_validator("ledger_name", "book_name", "rationale")
    @classmethod
    def meaningful(cls, value):
        if not value.strip() or value != value.strip():
            raise ValueError("Accounting setup text cannot be empty or padded")
        return value


def planned_identities(tenant, company_id, chart_id, setup):
    ledger_key = f"company:{company_id}:ledger:{setup.ledger_code}"
    ledger = canonical_id(tenant, "Ledger", ledger_key)
    calendar_key = None
    if isinstance(setup.calendar, ExistingSelection):
        calendar = setup.calendar.resource_id
    else:
        calendar_key = f"company:{company_id}:calendar:{setup.calendar.code}"
        calendar = canonical_id(tenant, "FiscalCalendar", calendar_key)
    period_key = None
    if isinstance(setup.period, ExistingSelection):
        period = setup.period.resource_id
    else:
        period_key = f"calendar:{calendar}:period:{setup.period.starts_on}:{setup.period.ends_on}"
        period = canonical_id(tenant, "FiscalPeriod", period_key)
    book_key = f"ledger:{ledger}:book:{setup.book_code}"
    return {
        "company_id": str(company_id),
        "chart_id": str(chart_id),
        "ledger_id": str(ledger),
        "book_id": str(canonical_id(tenant, "AccountingBook", book_key)),
        "calendar_id": str(calendar),
        "period_id": str(period),
        "currency_id": str(
            setup.currency_id or canonical_id(tenant, "Currency", setup.currency_code)
        ),
    }, {
        "Ledger": ledger_key,
        "AccountingBook": book_key,
        "FiscalCalendar": calendar_key,
        "FiscalPeriod": period_key,
        "Currency": setup.currency_code,
    }


def response(proposal, planned, decision=None):
    pins = {
        str(identity): str(version)
        for versions in proposal.source_versions.values()
        for identity, version in versions.items()
    }
    return {
        "proposal_id": str(proposal.proposal_id),
        "planned": planned,
        "created": [
            {"resource_id": str(item.resource_id), "object_type": item.object_type}
            for item in proposal.mutations
        ],
        "reused": [
            {"resource_id": identity, "version_id": version}
            for identity, version in sorted(pins.items())
        ],
        "authority": "USER_ASSERTED_PROPOSAL",
        "decision": decision,
        "review_required": decision is None,
    }


def propose(principal, document_id, sheet, profile, company_id, setup: SetupSelection, offset=0):
    require_permission(principal, "ontology_read")
    require_permission(principal, "ontology_propose")
    binding = ProposalRequestBinding(
        operation="source-accounting-setup/1",
        content_sha256=canonical_sha256(
            RootModel(
                {
                    "document_id": document_id,
                    "sheet": sheet,
                    "profile": profile,
                    "company_id": str(company_id),
                    "offset": offset,
                    "scope": principal.scope.model_dump(mode="json"),
                    "setup": setup.model_dump(mode="json"),
                }
            )
        ),
    )
    with resources.resource_connection(principal) as conn:
        old = conn.execute(
            "SELECT submitted_by,access_entity,payload FROM resource_proposals "
            "WHERE tenant_id=%s AND proposal_id=%s",
            (principal.scope.tenant_id, setup.request_id),
        ).fetchone()
    if old:
        proposal = ResourceProposal.model_validate(old[2]["request"])
        if (
            old[0] != principal.actor_id
            or old[1] != principal.scope.legal_entity_id
            or proposal.request_binding != binding
        ):
            raise WorkspaceError(409, "Setup request identity was reused for different content")
        ledger = next((item for item in proposal.mutations if item.object_type == "Ledger"), None)
        chart_id = (
            ledger.attributes["chart_id"] if ledger else str(uuid5(company_id, "1c-observed-chart"))
        )
        planned, _ = planned_identities(principal.scope.tenant_id, company_id, chart_id, setup)
        detail = resources.proposal_detail(principal, setup.request_id)
        return response(proposal, planned, detail.decision)
    context = source_accounting_context.inspect(principal, document_id, sheet, profile, company_id)
    if not context["canonical_ready"]:
        raise WorkspaceError(
            409, "Reviewed source company and chart are required before accounting setup"
        )
    attrs = context["observed"]
    planned, keys = planned_identities(
        principal.scope.tenant_id, company_id, attrs["chart_id"], setup
    )
    input_ids = {
        company_id,
        UUID(attrs["chart_id"]),
        UUID(attrs["evidence_id"]),
        *(UUID(value) for value in planned.values()),
    }
    if attrs.get("company_alias_id"):
        input_ids.add(UUID(attrs["company_alias_id"]))
    effective = _effective_resources(principal, list(input_ids))
    heads = resources.current_resources(principal, list(input_ids))
    pinned = {}

    def accepted(identity, kind):
        key = str(identity)
        row = effective.get(key)
        if (
            not row
            or row["object_type"] != kind
            or row["authority_state"] != "APPROVED"
            or row["evidence_class"] == "REFERENCE_TEMPLATE"
            or row["access_entity"] not in (principal.scope.legal_entity_id, "__PLATFORM__")
            or not heads.get(key)
            or heads[key]["version_id"] != row["version_id"]
        ):
            raise WorkspaceError(
                409, "Accounting setup input is unavailable, incompatible or scheduled"
            )
        pinned[UUID(key)] = UUID(row["version_id"])
        return row

    accepted(company_id, "LegalEntity")
    chart = accepted(attrs["chart_id"], "LocalChartOfAccounts")
    if chart["attributes"].get("legal_entity_id") != str(company_id):
        raise WorkspaceError(409, "Source chart belongs to another company")
    accepted(attrs["evidence_id"], "SourceEvidence")
    if setup.currency_id:
        accepted(setup.currency_id, "Currency")
    if attrs.get("company_alias_id"):
        accepted(attrs["company_alias_id"], "Alias")
    now = datetime.now(UTC)
    mutations = []

    def create_or_reuse(kind, identifier, name, attributes):
        if identifier in heads:
            row = accepted(identifier, kind)
            if row["attributes"] != attributes or (
                kind != "Currency" and row["display_name"] != name
            ):
                raise WorkspaceError(
                    409, "Canonical accounting identity already has different configuration"
                )
            return
        mutations.append(
            ResourceMutation(
                resource_id=UUID(identifier),
                object_type=kind,
                identity_key=keys[kind],
                display_name=name,
                attributes=attributes,
                valid_from=now,
                evidence_class="USER_ASSERTED",
            )
        )

    if setup.currency_code:
        create_or_reuse(
            "Currency", planned["currency_id"], setup.currency_code, {"code": setup.currency_code}
        )
    if isinstance(setup.calendar, ExistingSelection):
        accepted(setup.calendar.resource_id, "FiscalCalendar")
    else:
        create_or_reuse(
            "FiscalCalendar",
            planned["calendar_id"],
            setup.calendar.name,
            {"code": setup.calendar.code},
        )
    if isinstance(setup.period, ExistingSelection):
        period = accepted(setup.period.resource_id, "FiscalPeriod")
        if period["attributes"].get("calendar_id") != planned["calendar_id"]:
            raise WorkspaceError(409, "Selected fiscal period belongs to another calendar")
        if date.fromisoformat(period["attributes"]["ends_on"]) < date.fromisoformat(
            period["attributes"]["starts_on"]
        ):
            raise WorkspaceError(409, "Selected fiscal period has invalid date bounds")
        period_start = date.fromisoformat(period["attributes"]["starts_on"])
        period_end = date.fromisoformat(period["attributes"]["ends_on"])
    else:
        period_start, period_end = setup.period.starts_on, setup.period.ends_on
        create_or_reuse(
            "FiscalPeriod",
            planned["period_id"],
            setup.period.name,
            {
                "calendar_id": planned["calendar_id"],
                "starts_on": setup.period.starts_on.isoformat(),
                "ends_on": setup.period.ends_on.isoformat(),
            },
        )
    if period_start > date.fromisoformat(attrs["observed_from"]) or period_end < date.fromisoformat(
        attrs["observed_through"]
    ):
        raise WorkspaceError(409, "Fiscal period must cover the observed source date extent")
    create_or_reuse(
        "Ledger",
        planned["ledger_id"],
        setup.ledger_name,
        {key: planned[key] for key in ("calendar_id", "chart_id", "currency_id")}
        | {"legal_entity_id": str(company_id)},
    )
    create_or_reuse(
        "AccountingBook",
        planned["book_id"],
        setup.book_name,
        {"ledger_id": planned["ledger_id"], "code": setup.book_code},
    )
    if not mutations:
        raise WorkspaceError(
            409, "This accounting structure is already reviewed; select its existing resources"
        )
    proposal = ResourceProposal(
        proposal_id=setup.request_id,
        title="Set up company accounting structure",
        rationale=setup.rationale,
        access_entity=principal.scope.legal_entity_id,
        mutations=mutations,
        source_versions={item.resource_id: pinned for item in mutations},
        request_binding=binding,
    )
    resources.propose(principal, proposal)
    return response(proposal, planned)
