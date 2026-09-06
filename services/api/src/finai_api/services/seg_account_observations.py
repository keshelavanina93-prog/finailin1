"""Literal SEG account usage and definition candidates, without chart or mapping authority."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from finai_api.domain.resources import CanonicalResource
from finai_api.services import resources, source_company_alias
from finai_api.services.accounting_source_document import read_source
from finai_api.services.seg_expense_source import read_base
from finai_api.services.workspace import WorkspaceError

MAX_DEFINITIONS = 5000
MAX_COORDINATES_PER_CODE = 1000
MAX_CODES = 1000


def inspect(principal, document_id, sheet, profile, company_id: UUID):
    if profile != "seg_expense_base":
        raise WorkspaceError(422, "Select the SEG Base account-observation profile")
    company_binding = source_company_alias.inspect(
        principal, document_id, sheet, profile, company_id
    )
    if not company_binding["accepted"]:
        raise WorkspaceError(
            409, "Review the retained company alias before inspecting account candidates"
        )
    metadata, content = read_source(principal, document_id)
    parsed = read_base(content, sheet)
    if metadata["source_sha256"] != company_binding["source_sha256"]:
        raise WorkspaceError(409, "Source bytes differ from the reviewed company alias")
    columns = {}
    for coordinate, cell in parsed["headers"].items():
        if cell["value"] in {"Account Dr", "Account Cr"}:
            columns[cell["value"]] = coordinate.removeprefix(sheet + "!").removesuffix("1")
    observed: dict[str, dict[str, Any]] = {}
    for source in parsed["rows"]:
        for side, field, header in (
            ("DEBIT", "account_code", "Account Dr"),
            ("CREDIT", "credit_account_code", "Account Cr"),
        ):
            code = source["attributes"][field]
            # The parser requires literal text. Do not trim, case-fold or parse account numbers.
            entry = observed.setdefault(
                code,
                {
                    "code": code,
                    "debit_count": 0,
                    "credit_count": 0,
                    "coordinates": [],
                    "definitions": [],
                },
            )
            entry["debit_count" if side == "DEBIT" else "credit_count"] += 1
            if len(entry["coordinates"]) < MAX_COORDINATES_PER_CODE:
                entry["coordinates"].append(
                    {"coordinate": f"{sheet}!{columns[header]}{source['row']}", "side": side}
                )
        if len(observed) > MAX_CODES:
            raise WorkspaceError(
                409, "Account observation exceeds the supported distinct-code bound"
            )
    snapshot = datetime.now(UTC)
    definitions: list[CanonicalResource] = []
    for offset in range(0, MAX_DEFINITIONS + 1, 1000):
        page = resources.list_resources(
            principal,
            "SourceAccountDefinition",
            "",
            offset,
            valid_at=snapshot,
            known_at=snapshot,
            limit=1000,
        )
        if len(definitions) + len(page) > MAX_DEFINITIONS:
            raise WorkspaceError(
                409, "Account definition candidates exceed the supported inventory bound"
            )
        definitions.extend(page)
        if len(page) < 1000:
            break
    for definition in definitions:
        if definition.authority_state != "APPROVED" or definition.evidence_class != "SOURCE_BOUND":
            continue
        code = definition.attributes.get("account_code")
        if code in observed:
            observed[code]["definitions"].append(
                {
                    "resource_id": str(definition.resource_id),
                    "version_id": str(definition.version_id),
                    "display_name": definition.display_name,
                    "evidence_class": definition.evidence_class,
                    "attributes": definition.attributes,
                }
            )
    rows = []
    for _, entry in sorted(observed.items()):
        entry["coordinate_count"] = entry["debit_count"] + entry["credit_count"]
        entry["coordinates_truncated"] = entry["coordinate_count"] > len(entry["coordinates"])
        entry["candidate_state"] = (
            "NO_EXACT_CANDIDATE"
            if not entry["definitions"]
            else "EXACT_CODE_CANDIDATE"
            if len(entry["definitions"]) == 1
            else "AMBIGUOUS_CANDIDATES"
        )
        rows.append(entry)
    return {
        "company_id": str(company_id),
        "source_receipt_id": document_id,
        "source_sha256": metadata["source_sha256"],
        "source_label": parsed["company_label"],
        "accounting_use_authorized": False,
        "mapping_state": "CANDIDATE_REVIEW",
        "rows": rows,
        "row_count": len(parsed["rows"]),
        "observed_code_count": len(rows),
        "known_at": snapshot.isoformat(),
        "effective_at": snapshot.isoformat(),
        "observed_from": parsed["observed_from"],
        "observed_through": parsed["observed_through"],
        "max_coordinates_per_code": MAX_COORDINATES_PER_CODE,
        "blockers": [
            "A reviewed chart selection is required before LocalAccount publication.",
            "Exact code matches are candidates, not approved account meanings "
            "or financial mappings.",
        ],
    }
