"""Separate source-observed accounting scope from reviewed accounting configuration."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.services import resources
from finai_api.services.source_financial_facts import read_rows
from finai_api.services.workspace import WorkspaceError


class ContextSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_use: Literal["STRUCTURAL_REFERENCE", "REVIEW_CANDIDATE", "ACCOUNTING_INPUT"]
    contract_version: Literal["2"] | None = None
    ledger_id: UUID | None = None
    book_id: UUID | None = None
    period_id: UUID | None = None
    currency_id: UUID | None = None
    currency_role: Literal["FUNCTIONAL", "TRANSACTION", "PRESENTATION"] | None = None
    functional_currency_id: UUID | None = None
    transaction_currency_id: UUID | None = None
    reporting_currency_id: UUID | None = None
    currency_policy: Literal["SOURCE_AMOUNT_ONLY", "MULTI_CURRENCY"] | None = None
    account_mapping_id: UUID | None = None
    dimension_mapping_id: UUID | None = None
    granularity: Literal["SOURCE_ROW", "PERIOD_ACCOUNT"] | None = None
    deepest_valid_drill: Literal["SOURCE_CELL", "SOURCE_ROW", "PERIOD_ACCOUNT"] | None = None
    amount_field: str | None = Field(default=None, min_length=1, max_length=128)
    amount_semantics: Literal["DEBIT_CREDIT", "SIGNED_MOVEMENT", "PERIOD_BALANCE"] | None = None
    unresolved_reason: str | None = Field(default=None, min_length=10, max_length=2000)
    rationale: str = Field(min_length=10, max_length=2000)


def observe(principal, document_id, sheet, profile, company_id):
    if profile not in {"1c_tb", "1c_journal", "seg_expense_base"}:
        raise WorkspaceError(422, "Unsupported accounting source profile")
    from finai_api.services.accounting_source_document import read_source

    metadata, content = read_source(principal, document_id)
    if profile == "seg_expense_base":
        from finai_api.services.seg_expense_source import read_base

        parsed = read_base(content, sheet)
    else:
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
    from finai_api.services.source_company_alias import _effective_resources

    company = _effective_resources(principal, [company_id]).get(str(company_id))
    if not direct_company_match(company, parsed["company_label"], str(evidence)):
        from finai_api.services.source_company_alias import inspect as inspect_company_alias

        match = inspect_company_alias(principal, document_id, sheet, profile, company_id)
        if match["accepted"]:
            attrs["company_alias_id"] = str(match["alias"]["resource_id"])
    identity = uuid5(evidence, f"accounting-scope:{company_id}:{sheet}:{profile}")
    return identity, attrs, coordinate, parsed["company_label"]


def direct_company_match(company, label, evidence_id):
    return bool(
        company
        and company["authority_state"] == "APPROVED"
        and company["object_type"] == "LegalEntity"
        and company["evidence_class"] == "SOURCE_BOUND"
        and company["display_name"] == label
        and company["attributes"].get("evidence_id") == evidence_id
    )


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
        company_matches = direct_company_match(company, label, attrs["evidence_id"])
        if attrs.get("company_alias_id"):
            alias = target(attrs["company_alias_id"], key, "SOURCE_COMPANY_ALIAS")
            company_matches = (
                alias["object_type"] == "Alias"
                and alias["attributes"].get("source_system") == "RETAINED_ACCOUNTING_COMPANY"
                and alias["attributes"].get("target_id") == attrs["legal_entity_id"]
                and alias["display_name"] == label
            )
        if (
            item.evidence_class != "SOURCE_BOUND"
            or item.resource_id != identity
            or attrs != expected
            or not company_matches
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
        if any(
            value is not None
            for field, value in selection.model_dump().items()
            if field not in {"source_use", "rationale", "contract_version"}
        ):
            raise WorkspaceError(
                422, "Structural references cannot carry active accounting context"
            )
        return
    if selection.source_use == "REVIEW_CANDIDATE":
        if not selection.unresolved_reason:
            raise WorkspaceError(
                422, "Review candidates must retain the unresolved accounting meaning"
            )
        return
    required = [
        "contract_version",
        "functional_currency_id",
        "currency_policy",
        "account_mapping_id",
        "dimension_mapping_id",
        "granularity",
        "deepest_valid_drill",
        "amount_field",
        "amount_semantics",
    ]
    if any(not attrs.get(field) for field in required) or selection.unresolved_reason:
        raise WorkspaceError(
            422,
            "Accounting input requires a complete version 2 interpretation; "
            "unresolved meaning must remain a review candidate",
        )
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
    extra = {}
    for field in [
        "functional_currency_id",
        "transaction_currency_id",
        "reporting_currency_id",
        "account_mapping_id",
        "dimension_mapping_id",
    ]:
        if attrs.get(field):
            extra[field] = target(attrs[field], key, "SOURCE_CONTEXT:" + field)
            expected_type = "MappingVersion" if field.endswith("mapping_id") else "Currency"
            if (
                extra[field]["object_type"] != expected_type
                or extra[field]["evidence_class"] == "REFERENCE_TEMPLATE"
            ):
                raise WorkspaceError(
                    422,
                    "Accounting interpretation requires canonical non-template "
                    "currency and mapping versions",
                )
    role_field = {
        "FUNCTIONAL": "functional_currency_id",
        "TRANSACTION": "transaction_currency_id",
        "PRESENTATION": "reporting_currency_id",
    }[selection.currency_role]
    if (
        attrs["functional_currency_id"] != ledger_attrs["currency_id"]
        or attrs.get(role_field) != attrs["currency_id"]
        or (
            selection.currency_policy == "MULTI_CURRENCY"
            and not all(
                attrs.get(field) for field in ["transaction_currency_id", "reporting_currency_id"]
            )
        )
    ):
        raise WorkspaceError(
            422, "Explicit source amount currency must agree with its selected accounting role"
        )
    depth = {"PERIOD_ACCOUNT": 0, "SOURCE_ROW": 1, "SOURCE_CELL": 2}
    if (selection.granularity == "PERIOD_ACCOUNT" and depth[selection.deepest_valid_drill] > 0) or (
        source_attrs["source_profile"] == "1c_tb" and selection.granularity != "PERIOD_ACCOUNT"
    ):
        raise WorkspaceError(
            422, "Accounting drill cannot claim finer transaction evidence than the source"
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
    from finai_api.services.accounting_binding_status import inspect as inspect_status

    return {
        "scope_id": str(scope_id),
        "scope_version_id": scope["version_id"] if scope else None,
        "binding_version_id": binding["version_id"] if binding else None,
        "source_use": binding["attributes"]["source_use"] if accepted else "UNSELECTED",
        "canonical_references": resources.version_references(principal, UUID(binding["version_id"]))
        if accepted
        else {},
        "financial_eligibility": "NOT_CERTIFIED",
        "accounting_eligibility": inspect_status(principal, binding),
    }


def validate_active_selection(attrs, scope_attrs, target):
    """Use the publication contract against a consumption's immutable dependency pins."""
    if attrs.get("source_use") != "ACCOUNTING_INPUT" or attrs.get("contract_version") != "2":
        raise WorkspaceError(
            409, "Accounting use requires an accepted version 2 accounting binding"
        )
    scope_id = attrs["scope_id"]
    item = ResourceMutation(
        resource_id=uuid5(UUID(scope_id), "accounting-binding"),
        object_type="SourceAccountingBinding",
        identity_key="accounting-binding-validation",
        display_name="Accounting interpretation",
        evidence_class="USER_ASSERTED",
        valid_from=datetime.now(UTC),
        attributes=attrs,
    )
    validate_context(
        None,
        item,
        lambda identity, *_: (
            {"attributes": scope_attrs, "evidence_class": "SOURCE_BOUND"}
            if identity == scope_id
            else target(identity)
        ),
    )


def inspect(principal, document_id, sheet, profile, company_id):
    from finai_api.services.accounting_binding_status import inspect as inspect_status
    from finai_api.services.source_company_alias import inspect as inspect_company_alias

    identity, attrs, coordinate, label = observe(principal, document_id, sheet, profile, company_id)
    binding_id = uuid5(identity, "accounting-binding")
    heads = resources.current_resources(
        principal, [identity, binding_id, UUID(attrs["chart_id"])]
    )
    company_binding = inspect_company_alias(principal, document_id, sheet, profile, company_id)
    company = company_binding["company"]
    unresolved = []
    if not (
        direct_company_match(company, label, attrs["evidence_id"]) or company_binding["accepted"]
    ):
        unresolved.append(
            "The source company label needs a reviewed binding to the selected canonical company"
        )
    chart = heads.get(attrs["chart_id"])
    if (
        not chart
        or chart["authority_state"] != "APPROVED"
        or (
            chart["object_type"] != "LocalChartOfAccounts"
            or chart["attributes"].get("legal_entity_id") != str(company_id)
        )
    ):
        unresolved.append(
            "The selected company has no accepted source chart for this accounting scope"
        )
    candidates = {}
    snapshot = datetime.now(UTC)
    for kind in ["Ledger", "AccountingBook", "FiscalPeriod", "Currency", "MappingVersion"]:
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
        "canonical_ready": not unresolved,
        "unresolved": unresolved,
        "source_company_label": label,
        "company_binding": company_binding,
        "accounting_eligibility": inspect_status(principal, heads.get(str(binding_id))),
        "source_observations": source_observations(principal, document_id, sheet, profile),
    }


def propose_scope(principal, document_id, sheet, profile, company_id):
    result = inspect(principal, document_id, sheet, profile, company_id)
    if not result["canonical_ready"]:
        raise WorkspaceError(409, "; ".join(result["unresolved"]))
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
    if not result["canonical_ready"]:
        raise WorkspaceError(409, "; ".join(result["unresolved"]))
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


def source_observations(principal, document_id, sheet, profile):
    """Expose retained evidence before canonical accounting choices are established."""
    from finai_api.services.accounting_source_document import read_source

    metadata, content = read_source(principal, document_id)
    if profile == "seg_expense_base":
        from finai_api.services.seg_expense_source import read_base

        parsed = read_base(content, sheet)
        return {
            "document_id": document_id,
            "source_sha256": metadata["source_sha256"],
            "construction_receipt_id": metadata.get("construction_receipt_id"),
            "source_snapshot": metadata.get("source_snapshot"),
            "source_company_label": parsed["company_label"],
            "row_count": len(parsed["rows"]),
            "observed_from": parsed["observed_from"],
            "observed_through": parsed["observed_through"],
            "granularity": parsed["evidence_granularity"],
            "deepest_valid_drill": parsed["deepest_valid_drill"],
            "currency_observations": parsed["currency_observations"],
            "unresolved": parsed["unresolved"],
            "accounting_mapping_available": False,
            "sample_rows": parsed["rows"][:3],
        }
    parsed = read_rows(content, sheet, profile)
    return {
        "document_id": document_id,
        "source_sha256": metadata["source_sha256"],
        "source_company_label": parsed["company_label"],
        "row_count": len(parsed["rows"]),
        "unresolved": ["Source monetary currency, ledger and book require reviewed interpretation"],
    }
