"""Bind observed account usage to canonical company charts and exact 1C definitions."""

import re
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid5

import xlrd

from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.domain.review import Principal
from finai_api.services import resources
from finai_api.services.company_source import observe_companies, observe_tb_company
from finai_api.services.source_documents import document_bytes
from finai_api.services.workspace import WorkspaceError


def account_code(book, sheet, row: int, column: int) -> str:
    cell = sheet.cell(row, column)
    if cell.ctype == xlrd.XL_CELL_TEXT:
        return cell.value.strip()
    if cell.ctype != xlrd.XL_CELL_NUMBER:
        raise WorkspaceError(422, "Account codes must be text or explicitly formatted numbers")
    value = Decimal(str(cell.value))
    fmt = book.format_map[book.xf_list[cell.xf_index].format_key].format_str
    if re.fullmatch(r"0+(?:\.0+)?", fmt):
        places = len(fmt.partition(".")[2])
        rendered = f"{value:.{places}f}"
        if Decimal(rendered) != value:
            raise WorkspaceError(422, "Account cell format would round its stored identity")
        width = len(fmt.partition(".")[0])
        whole, dot, fraction = rendered.partition(".")
        return whole.zfill(width) + (dot + fraction if dot else "")
    if fmt == "General" and value == value.to_integral_value():
        return str(int(value))
    raise WorkspaceError(422, "Account number format requires explicit identity review")


def observe_usage(content: bytes, sheet_name: str, profile: str) -> dict:
    company = (
        observe_tb_company(content, sheet_name)
        if profile == "1c_tb"
        else observe_companies(content, sheet_name, 2, 10)
    )
    if len(company["companies"]) != 1 or company["unassigned_row_count"]:
        raise WorkspaceError(422, "This chart binding requires one unambiguous source company")
    try:
        book = xlrd.open_workbook(file_contents=content, on_demand=True, formatting_info=True)
        try:
            sheet = book.sheet_by_name(sheet_name)
            if profile == "1c_tb":
                expected = {(6, 2): "Код", (6, 3): "Наименование"}
                columns, start = [2], 7
            elif profile == "1c_journal":
                expected = {
                    (1, 10): "Dr Account",
                    (1, 16): "Cr Account",
                    (1, 22): "Сумма",
                    (1, 8): "Document",
                }
                columns, start = [10, 16], 2
            else:
                raise WorkspaceError(422, "Unknown account source profile")
            if any(sheet.cell_value(r, c) != label for (r, c), label in expected.items()):
                raise WorkspaceError(422, "Account source headers differ from the selected profile")
            groups, controls = {}, []
            for row in range(start, sheet.nrows):
                for column in columns:
                    if sheet.cell_value(row, column) == "":
                        if profile == "1c_journal" and any(sheet.row_values(row)):
                            raise WorkspaceError(
                                422, "A populated journal row is missing an account"
                            )
                        continue
                    code = account_code(book, sheet, row, column)
                    coordinate = f"{sheet_name}!{xlrd.colname(column)}{row + 1}"
                    if "X" in code.upper() and re.fullmatch(r"[0-9X]+", code.upper()):
                        controls.append({"code": code, "coordinate": coordinate})
                        continue
                    item = groups.setdefault(
                        code, {"code": code, "coordinate": coordinate, "occurrences": 0}
                    )
                    item["occurrences"] += 1
            return {
                "company_label": company["companies"][0]["source_label"],
                "accounts": sorted(groups.values(), key=lambda x: x["code"]),
                "control_groups": controls,
                "profile": profile,
                "sheet": sheet_name,
            }
        finally:
            book.release_resources()
    except (xlrd.XLRDError, IndexError) as exc:
        raise WorkspaceError(422, "The account source layout cannot be read") from exc


def inspect(principal: Principal, document_id: str, sheet: str, profile: str) -> dict:
    metadata, content = document_bytes(principal, document_id)
    observed = observe_usage(content, sheet, profile)
    definitions = []
    for offset in range(0, 10000, 1000):
        page = resources.list_resources(
            principal, "SourceAccountDefinition", "", offset, limit=1000
        )
        definitions.extend(page)
        if len(page) < 1000:
            break
    else:
        raise WorkspaceError(422, "Account-definition inventory exceeds the supported limit")
    for account in observed["accounts"]:
        matches = [d for d in definitions if d.attributes["account_code"] == account["code"]]
        account["definition_candidates"] = [
            {
                "resource_id": str(d.resource_id),
                "version_id": str(d.version_id),
                "name": d.attributes["source_name"],
            }
            for d in matches
        ]
        account["status"] = "EXACT_MATCH" if len(matches) == 1 else "RESOLUTION_REQUIRED"
    evidence_id = canonical_id(
        principal.scope.tenant_id, "SourceEvidence", metadata["source_sha256"]
    )
    companies = resources.list_resources(principal, "LegalEntity", observed["company_label"], 0)
    candidates = [
        {"resource_id": str(c.resource_id), "name": c.display_name}
        for c in companies
        if c.evidence_class == "SOURCE_BOUND"
        and c.display_name == observed["company_label"]
        and c.attributes.get("evidence_id") == str(evidence_id)
    ]
    return {
        "document_id": document_id,
        "sha256": metadata["source_sha256"],
        "company_candidates": candidates,
        **observed,
    }


def propose(
    principal: Principal, document_id: str, sheet: str, profile: str, company_id: UUID, offset: int
) -> object:
    observed = inspect(principal, document_id, sheet, profile)
    company = resources.get_resource(principal, company_id)["resource"]
    evidence_id = canonical_id(principal.scope.tenant_id, "SourceEvidence", observed["sha256"])
    if (
        company["object_type"] != "LegalEntity"
        or company["evidence_class"] != "SOURCE_BOUND"
        or company["attributes"].get("evidence_id") != str(evidence_id)
        or company["display_name"] != observed["company_label"]
    ):
        raise WorkspaceError(409, "Select the reviewed company identity from this source")
    if any(a["status"] != "EXACT_MATCH" for a in observed["accounts"]):
        raise WorkspaceError(409, "Resolve all account definitions before binding this chart")
    selected = observed["accounts"][offset : offset + 20]
    if not selected:
        raise WorkspaceError(422, "No account observations in this page")
    chart_id = uuid5(company_id, "1c-observed-chart")
    now = datetime.now(UTC)
    mutations, pins = [], {}

    def add(identity, kind, name, attributes, sources=None):
        try:
            prior = resources.get_resource(principal, identity)["resource"]
            if prior["object_type"] != kind or prior["attributes"] != attributes:
                raise WorkspaceError(409, "Existing chart binding conflicts with this source")
            return
        except WorkspaceError as exc:
            if exc.status != 404:
                raise
        mutations.append(
            ResourceMutation(
                resource_id=identity,
                object_type=kind,
                identity_key="source-chart:" + str(identity),
                display_name=name[:200],
                attributes=attributes,
                valid_from=now,
                evidence_class="SOURCE_BOUND",
            )
        )
        if sources:
            pins[identity] = sources

    add(
        chart_id,
        "LocalChartOfAccounts",
        "Observed 1C chart · " + company["display_name"],
        {
            "legal_entity_id": str(company_id),
            "code": "observed-1c-" + str(company_id),
            "evidence_id": str(evidence_id),
        },
        {company_id: UUID(company["version_id"])},
    )
    for account in selected:
        definition = account["definition_candidates"][0]
        record_id = uuid5(evidence_id, account["coordinate"])
        account_id = uuid5(chart_id, account["code"])
        add(
            record_id,
            "SourceRecord",
            account["coordinate"],
            {"evidence_id": str(evidence_id), "coordinate": account["coordinate"]},
        )
        add(
            account_id,
            "LocalAccount",
            account["code"] + " · " + definition["name"],
            {
                "chart_id": str(chart_id),
                "account_code": account["code"],
                "evidence_id": str(evidence_id),
            },
            {UUID(definition["resource_id"]): UUID(definition["version_id"])},
        )
        add(
            uuid5(account_id, "observed-in:" + str(record_id)),
            "Relationship",
            "Account usage at " + account["coordinate"],
            {
                "relation_id": str(
                    canonical_id(principal.scope.tenant_id, "LinkType", "DERIVED_FROM")
                ),
                "source_id": str(account_id),
                "target_id": str(record_id),
                "evidence_id": str(evidence_id),
            },
        )
    if not mutations:
        raise WorkspaceError(409, "This account page is already published")
    return resources.propose(
        principal,
        ResourceProposal(
            title="Bind source-observed 1C accounts to company chart",
            rationale="Bind accounts observed in this company source to exact reviewed account "
            "definition versions. Source control groups are excluded. Chart completeness, "
            "ledger context, mandatory analytics and financial mappings remain unestablished.",
            access_entity=principal.scope.legal_entity_id,
            mutations=mutations,
            source_versions=pins,
        ),
    )
