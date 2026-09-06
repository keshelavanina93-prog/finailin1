"""Source-column company observations, without inferred registration or ownership."""

from datetime import UTC, datetime
from uuid import uuid5

import xlrd

from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.domain.review import Principal
from finai_api.services import resources
from finai_api.services.source_documents import document_bytes
from finai_api.services.workspace import WorkspaceError


def observe_companies(content: bytes, sheet_name: str, header_row: int, column: int) -> dict:
    if not content.startswith(bytes.fromhex("d0cf11e0a1b11ae1")):
        raise WorkspaceError(422, "Company-column inspection currently supports BIFF XLS sources")
    try:
        book = xlrd.open_workbook(file_contents=content, on_demand=True)
        try:
            sheet = book.sheet_by_name(sheet_name)
            if sheet.nrows > 100000 or sheet.ncols > 256:
                raise WorkspaceError(422, "Source sheet exceeds the company inspection limit")
            if not 1 <= header_row < sheet.nrows or not 1 <= column <= sheet.ncols:
                raise WorkspaceError(
                    422, "Source header row or column is outside the selected sheet"
                )
            header = str(sheet.cell_value(header_row - 1, column - 1)).strip()
            if not header:
                raise WorkspaceError(422, "Select a labelled company column")
            if header.casefold() not in {
                "company-eng",
                "company",
                "organization",
                "организация",
                "კომპანია",
                "ორგანიზაცია",
            }:
                raise WorkspaceError(422, "The selected header is not a recognized company field")
            groups = {}
            blank_rows = []
            for row in range(header_row, sheet.nrows):
                value = sheet.cell_value(row, column - 1)
                if value == "":
                    if any(sheet.row_values(row)):
                        blank_rows.append(row + 1)
                    continue
                if sheet.cell_type(row, column - 1) != xlrd.XL_CELL_TEXT:
                    raise WorkspaceError(422, "Company names require text cells")
                label = value.strip()
                if not label or len(label) > 200:
                    raise WorkspaceError(422, "Company label is empty or exceeds 200 characters")
                groups.setdefault(label, []).append(row + 1)
                if len(groups) > 30:
                    raise WorkspaceError(
                        422, "More than 30 company labels; narrow the source sheet"
                    )
            return {
                "sheet": sheet_name,
                "header_row": header_row,
                "column": column,
                "header": header,
                "companies": [
                    {
                        "source_label": label,
                        "row_count": len(rows),
                        "first_coordinate": f"{sheet_name}!{xlrd.colname(column - 1)}{rows[0]}",
                    }
                    for label, rows in sorted(groups.items())
                ],
                "unassigned_row_count": len(blank_rows),
                "authority": "SOURCE_COMPANY_LABELS_ONLY",
            }
        finally:
            book.release_resources()
    except (xlrd.XLRDError, IndexError) as exc:
        raise WorkspaceError(422, "Workbook or selected company sheet cannot be read") from exc


def inspect_companies(
    principal: Principal,
    document_id: str,
    sheet: str,
    header_row: int,
    column: int,
    mode: str = "company_column",
) -> dict:
    document, content = document_bytes(principal, document_id)
    return {
        "document_id": document_id,
        "sha256": document["source_sha256"],
        **(
            observe_tb_company(content, sheet)
            if mode == "1c_tb_title"
            else observe_companies(content, sheet, header_row, column)
        ),
    }


def observe_tb_company(content: bytes, sheet_name: str) -> dict:
    """Recognize the original 1C TB title; never interpret it as a journal row."""
    try:
        book = xlrd.open_workbook(file_contents=content, on_demand=True)
        try:
            sheet = book.sheet_by_name(sheet_name)
            if sheet.nrows < 7 or sheet.ncols < 3:
                raise WorkspaceError(422, "The selected sheet is not a recognized 1C trial balance")
            if str(sheet.cell_value(1, 2)).strip() != "Оборотно-сальдовая ведомость":
                raise WorkspaceError(422, "The 1C trial balance title is missing at C2")
            label = sheet.cell_value(0, 2)
            if not isinstance(label, str) or not 1 <= len(label.strip()) <= 200:
                raise WorkspaceError(422, "A company title is required at C1")
            return {
                "sheet": sheet_name,
                "mode": "1c_tb_title",
                "companies": [
                    {
                        "source_label": label.strip(),
                        "row_count": 1,
                        "first_coordinate": f"{sheet_name}!C1",
                    }
                ],
                "unassigned_row_count": 0,
                "authority": "SOURCE_COMPANY_LABELS_ONLY",
            }
        finally:
            book.release_resources()
    except (xlrd.XLRDError, IndexError) as exc:
        raise WorkspaceError(422, "Workbook or selected company sheet cannot be read") from exc


def propose_companies(
    principal: Principal,
    document_id: str,
    sheet: str,
    header_row: int,
    column: int,
    mode: str = "company_column",
):
    observed = inspect_companies(principal, document_id, sheet, header_row, column, mode)
    if not observed["companies"] or observed["unassigned_row_count"]:
        raise WorkspaceError(
            422, "Resolve empty or unassigned company observations before publication"
        )
    evidence = canonical_id(principal.scope.tenant_id, "SourceEvidence", observed["sha256"])
    now = datetime.now(UTC)
    mutations = []
    specs = [
        (
            evidence,
            "SourceEvidence",
            observed["sha256"],
            "Retained company source",
            {"sha256": observed["sha256"], "source_system": "RETAINED_DOCUMENT"},
        )
    ]
    for company in observed["companies"]:
        coordinate = company["first_coordinate"]
        record = uuid5(evidence, coordinate)
        identity = uuid5(evidence, "company:" + company["source_label"])
        specs.extend(
            [
                (
                    record,
                    "SourceRecord",
                    observed["sha256"] + ":" + coordinate,
                    coordinate,
                    {"evidence_id": str(evidence), "coordinate": coordinate},
                ),
                (
                    identity,
                    "LegalEntity",
                    "observed-company:" + str(identity),
                    company["source_label"],
                    {"evidence_id": str(evidence)},
                ),
                (
                    uuid5(identity, "source-record"),
                    "Relationship",
                    "company-source:" + str(identity),
                    "Company observed in " + coordinate,
                    {
                        "relation_id": str(
                            canonical_id(principal.scope.tenant_id, "LinkType", "DERIVED_FROM")
                        ),
                        "source_id": str(identity),
                        "target_id": str(record),
                        "evidence_id": str(evidence),
                    },
                ),
            ]
        )
    for identity, kind, key, name, attributes in specs:
        try:
            prior = resources.get_resource(principal, identity)["resource"]
            if prior["attributes"] != attributes or prior["object_type"] != kind:
                raise WorkspaceError(
                    409, "An existing source identity conflicts with this observation"
                )
            continue
        except WorkspaceError as exc:
            if exc.status != 404:
                raise
        mutations.append(
            ResourceMutation(
                resource_id=identity,
                object_type=kind,
                identity_key=key,
                display_name=name,
                attributes=attributes,
                valid_from=now,
                evidence_class="SOURCE_BOUND",
            )
        )
    if not mutations:
        raise WorkspaceError(409, "These source company observations are already published")
    return resources.propose(
        principal,
        ResourceProposal(
            title="Publish observed company identities from retained source",
            rationale=(
                "Preserve source company names and exact cells; registration, "
                "group membership, licences and chart applicability remain unestablished."
            ),
            access_entity=principal.scope.legal_entity_id,
            mutations=mutations,
        ),
    )
