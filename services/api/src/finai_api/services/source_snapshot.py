"""Read-only retained-source observations for reviewed recurring-source contracts.

The caller's target resolver owns effective-version/lifecycle authorization and
dependency recording. This module neither authorizes adoption nor computes sums.
"""

import json
from hashlib import sha256
from uuid import UUID, uuid5

import xlrd

from finai_api.domain.source_adoption import AccountingMeaning, PinnedResource, SourceSnapshot
from finai_api.services import source_accounting_context, source_company_alias
from finai_api.services.accounting_source_document import read_source
from finai_api.services.seg_expense_source import read_base
from finai_api.services.source_financial_facts import read_rows
from finai_api.services.workspace import WorkspaceError
from finai_api.services.xls_source import FIELDS


def _pin(row):
    return PinnedResource.model_validate(
        {key: str(row[key]) for key in ("resource_id", "version_id", "content_hash")}
    )


def _schema(content, sheet, profile, parsed):
    """Fingerprint real header positions and parser roles, never posting values."""
    if profile == "seg_expense_base":
        headers = []
        labels = set()
        for coordinate, cell in sorted(parsed["headers"].items()):
            label = cell["value"]
            if not label:
                continue
            if (
                cell["formula"] is not None
                or cell["type"] not in {"s", "inlineStr", "str"}
                or label in labels
            ):
                raise WorkspaceError(422, "Snapshot requires unambiguous literal headers")
            labels.add(label)
            headers.append([coordinate.removeprefix(sheet + "!"), label])
        if parsed["merged_ranges"]:
            raise WorkspaceError(422, "Merged recorder-line layouts require explicit support")
        layout = {"headers": headers, "parser": parsed["profile"], "data_start": 2}
    else:
        book = xlrd.open_workbook(file_contents=content, formatting_info=True, on_demand=True)
        try:
            source = book.sheet_by_name(sheet)
            header_rows = [5, 6] if profile == "1c_tb" else [1]
            headers = []
            for row in header_rows:
                for column in range(source.ncols):
                    value = source.cell_value(row, column)
                    if value == "":
                        continue
                    if source.cell_type(row, column) != xlrd.XL_CELL_TEXT:
                        raise WorkspaceError(422, "Snapshot headers must be literal text")
                    headers.append([row + 1, column + 1, value])
            if profile == "1c_journal" and len({cell[2] for cell in headers}) != len(headers):
                raise WorkspaceError(422, "Journal snapshot headers are ambiguous")
            layout = {
                "headers": headers,
                "header_merges": sorted(
                    list(bounds)
                    for bounds in source.merged_cells
                    if any(bounds[0] <= row < bounds[1] for row in header_rows)
                ),
                "parser": "source-accounting/1",
                "data_start": 8 if profile == "1c_tb" else 3,
                "roles": (
                    {"account": 3, "measures": {k: v + 1 for k, v in FIELDS.items()}}
                    if profile == "1c_tb"
                    else {
                        "date_parts": [4, 5, 6],
                        "date": 7,
                        "document": 9,
                        "debit": 11,
                        "credit": 17,
                        "amount": 23,
                    }
                ),
            }
        finally:
            book.release_resources()
    return sha256(
        json.dumps(
            {"profile": profile, "layout": layout},
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _missing_amounts(parsed, profile, sheet, amount_field):
    if profile == "seg_expense_base":
        if amount_field != "source_amount":
            raise WorkspaceError(422, "Unsupported recorder-line accounting amount role")
        headers = [
            coordinate for coordinate, cell in parsed["headers"].items() if cell["value"] == "Сумма"
        ]
        if len(headers) != 1:
            raise WorkspaceError(422, "Snapshot amount header is missing or ambiguous")
        column = headers[0].removesuffix("1")
        return [
            column + str(row["row"])
            for row in parsed["rows"]
            if row["numeric_observations"].get("source_amount", {}).get("literal_decimal") is None
        ]
    if profile == "1c_journal" and amount_field == "amount":
        column = "W"
    elif profile == "1c_tb" and amount_field in FIELDS:
        column = xlrd.colname(FIELDS[amount_field])
    else:
        raise WorkspaceError(422, "Snapshot parser cannot observe the reviewed amount role")
    return [
        f"{sheet}!{column}{row['row']}"
        for row in parsed["rows"]
        if row["attributes"].get(amount_field) is None
    ]


def derive_snapshot(principal, binding_row, target) -> SourceSnapshot:
    """Derive observations from original bytes and exact reviewed dependencies."""

    def resource(identity, kind):
        row = target(str(identity))
        if (
            str(row["resource_id"]) != str(identity)
            or row["object_type"] != kind
            or row["evidence_class"] == "REFERENCE_TEMPLATE"
        ):
            raise WorkspaceError(409, "Snapshot dependency identity or type disagrees")
        _pin(row)
        return row

    binding = resource(binding_row["resource_id"], "SourceAccountingBinding")
    if _pin(binding) != _pin(binding_row) or binding["attributes"] != binding_row["attributes"]:
        raise WorkspaceError(409, "Snapshot requires the exact selected binding version")
    attrs = binding["attributes"]
    scope = resource(attrs["scope_id"], "SourceAccountingScope")
    source = scope["attributes"]
    if binding["evidence_class"] != "USER_ASSERTED" or scope["evidence_class"] != "SOURCE_BOUND":
        raise WorkspaceError(409, "Snapshot requires reviewed meaning over source-bound scope")
    if str(binding["resource_id"]) != str(uuid5(UUID(attrs["scope_id"]), "accounting-binding")):
        raise WorkspaceError(409, "Binding identity disagrees with its source scope")
    profile = source["source_profile"]
    if profile not in {"seg_expense_base", "1c_journal", "1c_tb"}:
        raise WorkspaceError(422, "Unsupported snapshot parser profile")
    source_accounting_context.validate_active_selection(attrs, source, target)
    evidence = resource(source["evidence_id"], "SourceEvidence")
    company = resource(source["legal_entity_id"], "LegalEntity")
    chart = resource(source["chart_id"], "LocalChartOfAccounts")
    period = resource(attrs["period_id"], "FiscalPeriod")
    if chart["attributes"].get("legal_entity_id") != str(company["resource_id"]):
        raise WorkspaceError(409, "Snapshot chart belongs to another company")
    document, sheet = source["document_id"], source["worksheet"]
    metadata, content = read_source(principal, document)
    digest = sha256(content).hexdigest()
    if digest != metadata["source_sha256"] or digest != evidence["attributes"].get("sha256"):
        raise WorkspaceError(409, "Retained bytes disagree with snapshot evidence hash")
    parsed = (
        read_base(content, sheet)
        if profile == "seg_expense_base"
        else read_rows(content, sheet, profile)
    )
    if not parsed["rows"] or len(parsed["rows"]) > 100000:
        raise WorkspaceError(422, "Snapshot requires a complete bounded retained source")
    if profile == "seg_expense_base" and not parsed["posting_identity_ready"]:
        raise WorkspaceError(409, "Ambiguous recorder identities require source review")
    identity, observed, coordinate, label = source_accounting_context.observe(
        principal, document, sheet, profile, UUID(source["legal_entity_id"])
    )
    if str(identity) != str(scope["resource_id"]) or observed != source:
        raise WorkspaceError(409, "Retained observations disagree with exact source scope")
    record = resource(source["source_record_id"], "SourceRecord")
    if record["attributes"] != {"evidence_id": source["evidence_id"], "coordinate": coordinate}:
        raise WorkspaceError(409, "Scope source record disagrees with retained coordinates")
    alias = None
    if source.get("company_alias_id"):
        alias = resource(source["company_alias_id"], "Alias")
        match = source_company_alias.inspect(
            principal, document, sheet, profile, UUID(source["legal_entity_id"])
        )
        if (
            not match["accepted"]
            or _pin(match["alias"]) != _pin(alias)
            or _pin(match["company"]) != _pin(company)
        ):
            raise WorkspaceError(409, "Snapshot requires its exact reviewed company alias")
    elif not source_accounting_context.direct_company_match(company, label, source["evidence_id"]):
        raise WorkspaceError(409, "Snapshot source company has no reviewed identity binding")
    references = {}
    for field, kind in {
        "ledger": "Ledger",
        "book": "AccountingBook",
        "currency": "Currency",
        "functional_currency": "Currency",
        "transaction_currency": "Currency",
        "reporting_currency": "Currency",
        "account_mapping": "MappingVersion",
        "dimension_mapping": "MappingVersion",
    }.items():
        if attrs.get(field + "_id"):
            references[field] = resource(attrs[field + "_id"], kind)
    rule = references["account_mapping"]["attributes"].get("definition", {})
    dimensions = references["dimension_mapping"]["attributes"].get("definition", {})
    if (
        rule.get("kind") != "EXACT_SOURCE_ACCOUNT_IDENTITIES"
        or rule.get("version") != 1
        or rule.get("company_id") != source["legal_entity_id"]
        or rule.get("chart_id") != source["chart_id"]
        or not isinstance(rule.get("accounts"), dict)
        or not 1 <= len(rule["accounts"]) <= 10000
        or dimensions.get("kind") != "PRESERVE_SOURCE_DIMENSION_COORDINATES"
        or dimensions.get("company_id") != source["legal_entity_id"]
        or dimensions.get("aggregation_dimensions") != []
    ):
        raise WorkspaceError(409, "Snapshot mapping definition lacks supported exact semantics")
    for code, ref in rule["accounts"].items():
        account = resource(ref["resource_id"], "LocalAccount")
        if (
            str(account["version_id"]) != ref["version_id"]
            or account["attributes"].get("chart_id") != source["chart_id"]
            or account["attributes"].get("account_code") != code
        ):
            raise WorkspaceError(409, "Snapshot account mapping version or identity disagrees")
    codes: set[str] = set()
    for row in parsed["rows"]:
        item = row["attributes"] if profile == "seg_expense_base" else row
        codes.update(
            item[field]
            for field in ("account_code", "credit_account_code", "debit_code", "credit_code")
            if item.get(field)
        )
    if not codes.issubset(rule["accounts"]):
        raise WorkspaceError(409, "Snapshot contains an unmapped source account")
    meaning = AccountingMeaning.model_validate(
        {
            **{field: _pin(row) for field, row in references.items()},
            **{
                field: attrs[field]
                for field in AccountingMeaning.model_fields
                if field in attrs and field not in references
            },
        }
    )
    missing = _missing_amounts(parsed, profile, sheet, attrs["amount_field"])
    return SourceSnapshot(
        binding=_pin(binding),
        scope=_pin(scope),
        evidence=_pin(evidence),
        company=_pin(company),
        chart=_pin(chart),
        company_alias=_pin(alias) if alias else None,
        period=_pin(period),
        period_starts_on=period["attributes"]["starts_on"],
        period_ends_on=period["attributes"]["ends_on"],
        observed_from=observed["observed_from"],
        observed_through=observed["observed_through"],
        source_sha256=digest,
        schema_sha256=_schema(content, sheet, profile, parsed),
        document_id=document,
        worksheet=sheet,
        source_profile=profile,
        date_basis=observed["date_basis"],
        source_rows=len(parsed["rows"]),
        meaning=meaning,
        coverage_state="UNESTABLISHED",
        missing_amount_count=len(missing),
        missing_amount_coordinates=missing[:100],
    )
