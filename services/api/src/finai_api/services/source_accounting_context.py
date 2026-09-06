"""Separate source-observed accounting scope from reviewed accounting configuration."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.services import resources
from finai_api.services.source_documents import document_bytes
from finai_api.services.source_financial_facts import read_rows
from finai_api.services.workspace import WorkspaceError


class ContextSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_use: Literal["STRUCTURAL_REFERENCE", "ACCOUNTING_INPUT"]
    ledger_id: UUID | None = None
    book_id: UUID | None = None
    period_id: UUID | None = None
    currency_id: UUID | None = None
    currency_role: Literal["FUNCTIONAL", "TRANSACTION", "PRESENTATION"] | None = None
    rationale: str = Field(min_length=10, max_length=2000)


def observe(principal, document_id, sheet, profile, company_id):
    if profile not in {"1c_tb", "1c_journal"}:
        raise WorkspaceError(422, "Unsupported accounting source profile")
    metadata, content = document_bytes(principal, document_id)
    parsed = read_rows(content, sheet, profile)
    rows = parsed["rows"]
    if not rows:
        raise WorkspaceError(422, "An accounting source scope requires observed rows")
    if profile == "1c_tb":
        starts = {r["attributes"]["period_start"] for r in rows}
        ends = {r["attributes"]["period_end"] for r in rows}
        if len(starts) != 1 or len(ends) != 1:
            raise WorkspaceError(422, "Trial balance has inconsistent source periods")
        start, end = next(iter(starts)), next(iter(ends))
        basis = "EXPLICIT_REPORT_PERIOD"
    else:
        dates = [r["attributes"]["posting_date"] for r in rows]
        start, end = min(dates), max(dates)
        basis = "OBSERVED_MOVEMENT_DATE_EXTENT"
    evidence = canonical_id(principal.scope.tenant_id, "SourceEvidence", metadata["source_sha256"])
    coordinate = f"{sheet}!rows:{rows[0]['row']}:{rows[-1]['row']}"
    attrs = {
        "document_id": document_id,
        "legal_entity_id": str(company_id),
        "chart_id": str(uuid5(company_id, "1c-observed-chart")),
        "worksheet": sheet,
        "source_profile": profile,
        "observed_from": start,
        "observed_through": end,
        "date_basis": basis,
        "coverage_state": "UNESTABLISHED",
        "evidence_id": str(evidence),
        "source_record_id": str(uuid5(evidence, coordinate)),
    }
    identity = uuid5(evidence, f"accounting-scope:{company_id}:{sheet}:{profile}")
    return identity, attrs, coordinate, parsed["company_label"]


def validate_context(principal, item, target):
    attrs, key = item.attributes, str(item.resource_id)
    if item.object_type == "SourceAccountingScope":
        identity, expected, coordinate, label = observe(
            principal,
            attrs["document_id"],
            attrs["worksheet"],
            attrs["source_profile"],
            UUID(attrs["legal_entity_id"]),
        )
        company = target(attrs["legal_entity_id"], key, "SOURCE_SCOPE_COMPANY")
        chart = target(attrs["chart_id"], key, "SOURCE_SCOPE_CHART")
        record = target(attrs["source_record_id"], key, "SOURCE_SCOPE_RECORD")
        if (
            item.evidence_class != "SOURCE_BOUND"
            or item.resource_id != identity
            or attrs != expected
            or company["display_name"] != label
            or company["attributes"].get("evidence_id") != attrs["evidence_id"]
            or chart["attributes"]["legal_entity_id"] != attrs["legal_entity_id"]
            or record["attributes"]
            != {"evidence_id": attrs["evidence_id"], "coordinate": coordinate}
        ):
            raise WorkspaceError(
                422, "Accounting scope must match original evidence and company chart"
            )
        return
    scope = target(attrs["scope_id"], key, "ACCOUNTING_SOURCE_SCOPE")
    if item.evidence_class != "USER_ASSERTED":
        raise WorkspaceError(
            422, "Accounting use is reviewed configuration, not a source observation"
        )
    expected_id = uuid5(UUID(attrs["scope_id"]), "accounting-binding")
    if item.resource_id != expected_id or scope["evidence_class"] != "SOURCE_BOUND":
        raise WorkspaceError(422, "Accounting binding requires its stable source scope identity")
    try:
        selection = ContextSelection.model_validate(
            {k: v for k, v in attrs.items() if k != "scope_id"}
        )
    except ValidationError as exc:
        raise WorkspaceError(422, "Invalid source accounting selection") from exc
    context_fields = ["ledger_id", "book_id", "period_id", "currency_id", "currency_role"]
    if selection.source_use == "STRUCTURAL_REFERENCE":
        if any(attrs.get(field) is not None for field in context_fields):
            raise WorkspaceError(
                422, "Structural references cannot carry active accounting context"
            )
        return
    if any(not attrs.get(field) for field in context_fields):
        raise WorkspaceError(
            422, "Accounting input requires explicit ledger, book, period and currency role"
        )
    ledger, book, period, currency = [
        target(attrs[field], key, "SOURCE_CONTEXT:" + field) for field in context_fields[:-1]
    ]
    if any(
        node["evidence_class"] == "REFERENCE_TEMPLATE" for node in (ledger, book, period, currency)
    ):
        raise WorkspaceError(
            422, "Reference accounting resources cannot govern source accounting input"
        )
    source_attrs, ledger_attrs, book_attrs, period_attrs = [
        node["attributes"] for node in (scope, ledger, book, period)
    ]
    if (
        ledger_attrs["legal_entity_id"] != source_attrs["legal_entity_id"]
        or ledger_attrs["chart_id"] != source_attrs["chart_id"]
        or book_attrs["ledger_id"] != attrs["ledger_id"]
        or period_attrs["calendar_id"] != ledger_attrs["calendar_id"]
        or period_attrs["starts_on"] > source_attrs["observed_from"]
        or period_attrs["ends_on"] < source_attrs["observed_through"]
        or (
            selection.currency_role == "FUNCTIONAL"
            and ledger_attrs["currency_id"] != attrs["currency_id"]
        )
    ):
        raise WorkspaceError(
            422, "Source company, chart, ledger, book, period and currency role disagree"
        )


def published_context(principal, evidence_id, sheet, profile, company_id):
    """Expose reviewed selection and immutable dependency pins without certifying source facts."""
    scope_id = uuid5(evidence_id, f"accounting-scope:{company_id}:{sheet}:{profile}")
    binding_id = uuid5(scope_id, "accounting-binding")
    heads = resources.current_resources(principal, [scope_id, binding_id])
    scope, binding = heads.get(str(scope_id)), heads.get(str(binding_id))
    accepted = bool(
        scope
        and binding
        and scope["authority_state"] == "APPROVED"
        and binding["authority_state"] == "APPROVED"
    )
    return {
        "scope_id": str(scope_id),
        "scope_version_id": scope["version_id"] if scope else None,
        "binding_version_id": binding["version_id"] if binding else None,
        "source_use": binding["attributes"]["source_use"] if accepted else "UNSELECTED",
        "canonical_references": resources.version_references(principal, UUID(binding["version_id"]))
        if accepted
        else {},
        "financial_eligibility": "NOT_CERTIFIED",
    }


def inspect(principal, document_id, sheet, profile, company_id):
    identity, attrs, coordinate, label = observe(principal, document_id, sheet, profile, company_id)
    binding_id = uuid5(identity, "accounting-binding")
    heads = resources.current_resources(
        principal, [identity, binding_id, company_id, UUID(attrs["chart_id"])]
    )
    company = heads.get(str(company_id))
    if (
        not company
        or company["authority_state"] != "APPROVED"
        or company["object_type"] != "LegalEntity"
        or company["evidence_class"] != "SOURCE_BOUND"
        or company["display_name"] != label
        or company["attributes"].get("evidence_id") != attrs["evidence_id"]
    ):
        raise WorkspaceError(409, "Select the reviewed company from this retained source")
    chart = heads.get(attrs["chart_id"])
    if not chart or chart["authority_state"] != "APPROVED" or (
        chart["object_type"] != "LocalChartOfAccounts"
        or chart["attributes"].get("legal_entity_id") != str(company_id)
    ):
        raise WorkspaceError(409, "Publish the source company chart before accounting context")
    candidates = {}
    snapshot = datetime.now(UTC)
    for kind in ["Ledger", "AccountingBook", "FiscalPeriod", "Currency"]:
        candidates[kind] = []
        offset = 0
        while True:
            page = resources.list_resources(
                principal, kind, "", offset, valid_at=snapshot, known_at=snapshot, limit=1000
            )
            candidates[kind].extend(
                r.model_dump(mode="json")
                for r in page
                if r.authority_state == "APPROVED" and r.evidence_class != "REFERENCE_TEMPLATE"
            )
            if len(page) < 1000:
                break
            offset += len(page)
    candidates["Ledger"] = [
        r
        for r in candidates["Ledger"]
        if (
            r["attributes"]["legal_entity_id"] == str(company_id)
            and r["attributes"]["chart_id"] == attrs["chart_id"]
        )
    ]
    return {
        "scope_id": str(identity),
        "binding_id": str(binding_id),
        "observed": attrs,
        "source_coordinate": coordinate,
        "scope": heads.get(str(identity)),
        "binding": heads.get(str(binding_id)),
        "candidates": candidates,
        "financial_eligibility": "NOT_CERTIFIED",
    }


def propose_scope(principal, document_id, sheet, profile, company_id):
    result = inspect(principal, document_id, sheet, profile, company_id)
    attrs = result["observed"]
    if result["scope"]:
        if result["scope"]["attributes"] != attrs:
            raise WorkspaceError(409, "Source scope changed; review a new parser binding")
        raise WorkspaceError(409, "This source accounting scope is already published")
    now = datetime.now(UTC)
    records = resources.current_resources(principal, [UUID(attrs["source_record_id"])])
    mutations = []
    if not records:
        mutations.append(
            ResourceMutation(
                resource_id=UUID(attrs["source_record_id"]),
                object_type="SourceRecord",
                identity_key="source-scope-record:" + attrs["source_record_id"],
                display_name=result["source_coordinate"],
                valid_from=now,
                evidence_class="SOURCE_BOUND",
                attributes={
                    "coordinate": result["source_coordinate"],
                    "evidence_id": attrs["evidence_id"],
                },
            )
        )
    mutations.append(
        ResourceMutation(
            resource_id=UUID(result["scope_id"]),
            object_type="SourceAccountingScope",
            identity_key="source-accounting-scope:" + result["scope_id"],
            display_name=sheet + " accounting source scope",
            attributes=attrs,
            valid_from=now,
            evidence_class="SOURCE_BOUND",
        )
    )
    return resources.propose(
        principal,
        ResourceProposal(
            title="Publish observed source accounting scope",
            rationale="Retain company, chart and observed source date bounds independently of "
            "sign-in scope. Coverage, ledger and monetary currency are not inferred.",
            access_entity=principal.scope.legal_entity_id,
            mutations=mutations,
        ),
    )


def propose_binding(principal, document_id, sheet, profile, company_id, selection):
    result = inspect(principal, document_id, sheet, profile, company_id)
    if not result["scope"] or result["scope"]["authority_state"] != "APPROVED":
        raise WorkspaceError(409, "Publish observed source scope before choosing accounting use")
    prior = result["binding"]
    attrs = {"scope_id": result["scope_id"], **selection.model_dump(mode="json", exclude_none=True)}
    if prior and prior["attributes"] == attrs:
        raise WorkspaceError(409, "This source accounting selection is already published")
    return resources.propose(
        principal,
        ResourceProposal(
            title="Review source accounting use and context",
            rationale=selection.rationale,
            access_entity=principal.scope.legal_entity_id,
            mutations=[
                ResourceMutation(
                    resource_id=UUID(result["binding_id"]),
                    expected_version_id=UUID(prior["version_id"]) if prior else None,
                    object_type="SourceAccountingBinding",
                    identity_key="source-accounting-binding:" + result["scope_id"],
                    display_name=sheet + " accounting use",
                    attributes=attrs,
                    valid_from=datetime.now(UTC),
                    evidence_class="USER_ASSERTED",
                )
            ],
        ),
    )
