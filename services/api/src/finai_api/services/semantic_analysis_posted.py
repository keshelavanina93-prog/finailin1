"""Projection recipe for the existing reviewed posted-movement Function contract."""

from decimal import Decimal, InvalidOperation

from finai_api.domain.semantic_analysis import (
    Contributor,
    Coverage,
    Descriptor,
    EvidenceCell,
    FieldDefinition,
    Row,
    Value,
)
from finai_api.services.semantic_analysis_support import pin, row_key, value_options
from finai_api.services.workspace import WorkspaceError


def _require(condition):
    if not condition:
        raise WorkspaceError(409, "Posted analysis differs from its retained accounting contract")


def _literal(value):
    # Workbook lexical values are evidence. Never use a float to calculate money.
    if isinstance(value, float):
        return str(value)
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise WorkspaceError(409, "Unsupported retained source cell")


def build(history, plan, resolver, company_id):
    output = history["output"]
    source = output.get("source_document", {})
    _require(
        source == plan.get("source_document")
        and output.get("authority") == "GUARDED_POSTED_MOVEMENT_ANALYSIS"
        and output.get("coverage") == "RETAINED_SOURCE_POSTINGS_WITH_EXPLICIT_EXCLUSIONS"
    )
    if source.get("company_id") != str(company_id):
        raise WorkspaceError(404, "Analysis unavailable for this company")
    function = resolver.version(plan["function"])
    binding = resolver.version(source["binding"])
    scope = resolver.version(source["scope"])
    evidence = resolver.version(source["evidence"])
    company = resolver.field(scope, "legal_entity_id")
    _require(
        company["object_type"] == "LegalEntity" and str(company["resource_id"]) == str(company_id)
    )
    meaning = source["context"]
    _require(
        binding["object_type"] == "SourceAccountingBinding"
        and scope["object_type"] == "SourceAccountingScope"
        and str(scope["attributes"]["legal_entity_id"]) == str(company_id)
        and all(binding["attributes"].get(key) == value for key, value in meaning.items())
        and meaning["vat_treatment"] == "AS_POSTED"
        and meaning["amount_semantics"] == "DEBIT_CREDIT"
        and meaning["amount_field"] == "source_amount"
        and evidence["attributes"]["sha256"] == source["sha256"]
    )
    currency = resolver.field(binding, "currency_id")
    _require(currency["object_type"] == "Currency")
    currency_label = currency["attributes"].get("code") or currency["display_name"]
    declarations = [pin(function), pin(binding), pin(scope), pin(evidence), pin(currency)]
    context = []
    for key, label in (
        ("ledger_id", "Ledger"),
        ("book_id", "Book"),
        ("period_id", "Period"),
        ("currency_id", "Currency"),
    ):
        item = resolver.field(binding, key)
        context.append(Coverage(label=label, value=item["display_name"]))
        if pin(item) not in declarations:
            declarations.append(pin(item))

    source_rows = output["source_rows"]
    _require(len(source_rows) == source["row_count"] and len(source_rows) <= 1000)
    source_index = {}
    for row in source_rows:
        for coordinate in row["cells"]:
            _require(coordinate not in source_index)
            source_index[coordinate] = row
    movements = output["posted_movements"]
    included = movements["included_coordinates"]
    excluded = movements["excluded_rows"]
    _require(
        len(set(included)) == len(included)
        and len(included) + len(excluded) == len(source_rows)
        and movements["coverage"]
        == {
            "source_rows": len(source_rows),
            "included_rows": len(included),
            "excluded_rows": len(excluded),
            "ledger_completeness": "UNESTABLISHED",
        }
    )

    def contributor(coordinate, source_row=None):
        row = source_row or source_index.get(coordinate)
        _require(row is not None)
        cells = [
            EvidenceCell(
                label=address,
                coordinate=address,
                value=_literal(cell.get("value")),
                formula=cell.get("formula"),
            )
            for address, cell in row["cells"].items()
        ]
        if coordinate not in row["cells"]:
            cells.append(
                EvidenceCell(label="Missing posted amount", coordinate=coordinate, value=None)
            )
        return Contributor(
            label=f"{source['sheet']} · row {row['row']}",
            reference=pin(evidence),
            document_id=source["document_id"],
            source_sha256=source["sha256"],
            sheet=source["sheet"],
            coordinate=coordinate,
            cells=cells,
        )

    rows, contributors, side_coordinates = [], {}, {"debit": [], "credit": []}
    for group in movements["groups"]:
        _require(
            group["side"] in side_coordinates
            and group["account"] == source["accounts"].get(group["account_code"])
            and group["currency_id"] == meaning["currency_id"]
        )
        account = resolver.version(group["account"])
        _require(account["object_type"] == "LocalAccount")
        try:
            amount = Decimal(group["value"])
            _require(
                amount.is_finite()
                and abs(amount.adjusted()) <= 100
                and len(amount.as_tuple().digits) <= 100
            )
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise WorkspaceError(409, "Invalid retained posted amount") from exc
        coordinates = group["source_coordinates"]
        _require(
            bool(coordinates)
            and len(coordinates) == len(set(coordinates))
            and set(coordinates).issubset(included)
        )
        side_coordinates[group["side"]].extend(coordinates)
        key = row_key(output["run_id"], [group["account"], group["side"], group["currency_id"]])
        side = group["side"].capitalize()
        name = account["display_name"]
        prefix = group["account_code"] + " · "
        while name.startswith(prefix):
            name = name[len(prefix) :]
        label = prefix + name if name != group["account_code"] else name
        rows.append(
            Row(
                key=key,
                label=f"{label} · {side}",
                contributor_count=len(coordinates),
                trace=pin(account),
                values={
                    "account": Value(
                        value=str(account["resource_id"]), label=label, reference=pin(account)
                    ),
                    "side": Value(value=group["side"], label=side),
                    "posted_amount": Value(value=group["value"]),
                },
            )
        )
        contributors[key] = [contributor(coordinate) for coordinate in coordinates]
    _require(all(sorted(coords) == sorted(included) for coords in side_coordinates.values()))
    excluded_evidence = []
    for item in excluded:
        original = next((row for row in source_rows if row["row"] == item["row"]), None)
        _require(
            item["reason"] == "MISSING_LITERAL_POSTED_AMOUNT"
            and original is not None
            and original["numeric_observations"].get("source_amount", {}).get("literal_decimal")
            is None
        )
        excluded_evidence.append(contributor(item["coordinate"], original))
    fields = [
        FieldDefinition(
            key="account",
            label="Account",
            kind="reference",
            role="DIMENSION",
            definition=pin(binding),
            filterable=True,
            groupable=True,
        ),
        FieldDefinition(
            key="side",
            label="Posting side",
            kind="identifier",
            role="DIMENSION",
            definition=pin(function),
            filterable=True,
            groupable=True,
        ),
        FieldDefinition(
            key="posted_amount",
            label="Posted amount",
            kind="decimal",
            role="MEASURE",
            definition=pin(function),
            unit=currency_label,
            unit_reference=pin(currency),
            aggregation="RETAINED_VALUE_ONLY",
        ),
    ]
    fields = [
        field.model_copy(update={"options": value_options(rows, field.key)})
        if field.role == "DIMENSION"
        else field
        for field in fields
    ]
    descriptor = Descriptor(
        invocation_id=history["invocation_id"],
        receipt_hash=history["receipt_hash"],
        run_id=output["run_id"],
        function=pin(function),
        company=pin(company),
        company_label=company["display_name"],
        title=function["display_name"],
        grain=["account", "side"],
        partition_keys=["side"],
        fields=fields,
        measure="posted_amount",
        authority="Retained partial account movements · as posted",
        coverage=[
            Coverage(label="Source rows", value=str(len(source_rows))),
            Coverage(label="Included literal amounts", value=str(len(included))),
            Coverage(label="Excluded missing amounts", value=str(len(excluded))),
            Coverage(label="Ledger completeness", value="Unestablished"),
            Coverage(
                label="Observed dates",
                value=f"{source['observed_from']} to {source['observed_through']}",
            ),
        ],
        context=context,
        valid_at=output["query"]["valid_at"],
        known_at=output["query"]["known_at"],
        recorded_at=history["receipt"]["recorded_at"],
        definitions=declarations,
        excluded_evidence=excluded_evidence,
        unavailable_operations=[
            "New totals or joins require an approved calculation.",
            "Debit and credit remain separate; no netting is authorized.",
            "Statements, forecasts and cross-period comparisons are not established.",
            "Original accounting use and business effects are not authorized by this view.",
        ],
    )
    return descriptor, rows, contributors
