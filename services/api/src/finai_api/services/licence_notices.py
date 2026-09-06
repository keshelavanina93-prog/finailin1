"""Original licence issuance notices linked to canonical companies and licences."""

import re
from datetime import UTC, datetime
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.services import resources
from finai_api.services.corporate_disclosures import GroupTable
from finai_api.services.source_documents import document_bytes
from finai_api.services.workspace import WorkspaceError


class NoticeSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: UUID
    rationale: str = Field(min_length=10, max_length=2000)


def parse(content):
    if len(content) > 2_000_000:
        raise WorkspaceError(422, "Licence notice exceeds 2 MB")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeError as exc:
        raise WorkspaceError(422, "Expected a retained UTF-8 Matsne issuance notice") from exc
    doc = re.search(r"page-document-view-(\d+)\b", text)
    table = GroupTable()
    table.feed(text.replace('id="maindoc"', 'id="reports-group"'))
    rows = table.rows
    if not doc or table.found != 1 or len(rows) != 4 or any(len(r) != 7 for r in rows):
        raise WorkspaceError(422, "Recognized Matsne licence issuance table required")
    if rows[0][4:6] != ["საქმიანობის სახე", "სახელმწიფო რეგისტრაციის მონაცემები"]:
        raise WorkspaceError(422, "Licence notice headers are not recognized")
    row, notes = rows[1], rows[3]
    number = re.fullmatch(r"№\s*(\d+)", row[2])
    code = re.fullmatch(r"საიდენტიფიკაციო კოდი:\s*(\d{9})", row[5])
    issued = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})(?:\s*წ\s*\.)?", row[3])
    if not number or not code or not issued or row[4] != "ბუნებრივი გაზის განაწილება":
        raise WorkspaceError(422, "Unsupported or incomplete licence identity/activity/date")
    if "გაიცა" not in notes[5] or "გაუქმდა" in notes[5] or any(notes[i] for i in [1, 2, 3, 4, 6]):
        raise WorkspaceError(422, "This profile only interprets unambiguous issuance notices")
    try:
        date = datetime.strptime(".".join(issued.groups()), "%d.%m.%Y").date().isoformat()
    except ValueError as exc:
        raise WorkspaceError(422, "Invalid licence issuance date") from exc
    return {
        "licence_number": number[1],
        "company_code": code[1],
        "company_label": row[1],
        "issued_on": date,
        "activity": "DISTRIBUTION",
        "event": "ISSUED",
        "stated_term": "INDEFINITE" if "უვადოდ" in notes[5] else "NOT_STATED",
        "matsne_document_id": doc[1],
        "source_url": f"https://matsne.gov.ge/ka/document/view/{doc[1]}",
        "raw_rows": rows,
        "current_status": "NOT_ESTABLISHED",
    }


def observed(principal, document_id):
    metadata, content = document_bytes(principal, document_id)
    notice = parse(content)
    evidence = canonical_id(principal.scope.tenant_id, "SourceEvidence", metadata["source_sha256"])
    record = uuid5(evidence, "maindoc/licence-table")
    identity = uuid5(record, "licence-notice")
    attrs = {
        "document_id": document_id,
        "source_record_id": str(record),
        "evidence_id": str(evidence),
        "notice": notice,
    }
    return identity, attrs, metadata


def validate(principal, item, target):
    a, key = item.attributes, str(item.resource_id)
    if item.object_type == "SourceLicenceNotice":
        identity, expected, _ = observed(principal, a["document_id"])
        record = target(a["source_record_id"], key, "LICENCE_NOTICE_ROW")
        if (
            item.resource_id != identity
            or a != expected
            or item.evidence_class != "SOURCE_BOUND"
            or record["attributes"]
            != {"evidence_id": a["evidence_id"], "coordinate": "maindoc/licence-table"}
        ):
            raise WorkspaceError(422, "Licence notice must reproduce the retained source")
        return
    notice = target(a["notice_id"], key, "LICENCE_NOTICE")
    company = target(a["company_id"], key, "LICENCE_NOTICE_COMPANY")
    licence = target(a["licence_id"], key, "LICENCE_NOTICE_IDENTITY")
    raw = notice["attributes"]["notice"]
    if company["attributes"].get("registration_code") is None:
        if not a.get("identity_binding_id"):
            raise WorkspaceError(422, "Company needs an evidenced registration-code binding")
        identity = target(a["identity_binding_id"], key, "LICENCE_COMPANY_IDENTITY")
        if (
            identity["attributes"].get("reporter_id") != a["company_id"]
            or identity["attributes"].get("reporter_code") != raw["company_code"]
        ):
            raise WorkspaceError(422, "Company identity binding conflicts with licence holder")
    if (
        notice["evidence_class"] != "SOURCE_BOUND"
        or company["evidence_class"] == "REFERENCE_TEMPLATE"
        or licence["evidence_class"] == "REFERENCE_TEMPLATE"
        or item.evidence_class != "USER_ASSERTED"
        or item.resource_id != uuid5(UUID(a["notice_id"]), "company-binding")
        or a["basis"] != "ISSUANCE_NOTICE_ONLY"
        or len(a["rationale"].strip()) < 10
        or licence["attributes"]["identifier"] != raw["licence_number"]
        or licence["attributes"]["jurisdiction"] != "GE"
        or company["attributes"].get("registration_code") not in {None, raw["company_code"]}
    ):
        raise WorkspaceError(422, "Company/licence binding conflicts with issuance evidence")


def inspect(principal, document_id):
    identity, attrs, metadata = observed(principal, document_id)
    companies = []
    now = datetime.now(UTC)
    for offset in range(0, 5000, 100):
        page = resources.list_resources(principal, "LegalEntity", "", offset, now, now)
        companies.extend(
            r.model_dump(mode="json") for r in page if r.evidence_class != "REFERENCE_TEMPLATE"
        )
        if len(page) < 100:
            break
    else:
        raise WorkspaceError(422, "Company inventory exceeds supported selection limit")
    try:
        binding = resources.get_resource(principal, uuid5(identity, "company-binding"))["resource"]
    except WorkspaceError as exc:
        if exc.status != 404:
            raise
        binding = None
    return {
        "document_id": document_id,
        "sha256": metadata["source_sha256"],
        "notice": attrs["notice"],
        "companies": companies,
        "binding": binding,
    }


def propose(principal, document_id, selection):
    identity, attrs, metadata = observed(principal, document_id)
    company = resources.get_resource(principal, selection.company_id)["resource"]
    identity_binding = None
    if company["attributes"].get("registration_code") is None:
        for offset in range(0, 5000, 100):
            page = resources.list_resources(principal, "CorporateDisclosureBinding", "", offset)
            match = next(
                (
                    r
                    for r in page
                    if r.attributes.get("reporter_id") == str(selection.company_id)
                    and r.attributes.get("reporter_code") == attrs["notice"]["company_code"]
                ),
                None,
            )
            if match:
                identity_binding = str(match.resource_id)
                break
            if len(page) < 100:
                break
        if identity_binding is None:
            raise WorkspaceError(422, "Bind the company's registration identity before its licence")
    evidence, record = UUID(attrs["evidence_id"]), UUID(attrs["source_record_id"])
    licence = canonical_id(
        principal.scope.tenant_id, "Licence", "GE:GNERC:GAS:" + attrs["notice"]["licence_number"]
    )
    specs = [
        (
            evidence,
            "SourceEvidence",
            metadata["source_sha256"],
            "Retained official licence notice",
            {"sha256": metadata["source_sha256"], "source_system": "RETAINED_DOCUMENT"},
            "SOURCE_BOUND",
        ),
        (
            record,
            "SourceRecord",
            metadata["source_sha256"] + ":maindoc/licence-table",
            "Licence issuance table",
            {"evidence_id": str(evidence), "coordinate": "maindoc/licence-table"},
            "SOURCE_BOUND",
        ),
        (
            identity,
            "SourceLicenceNotice",
            str(identity),
            "Licence issuance " + attrs["notice"]["licence_number"],
            attrs,
            "SOURCE_BOUND",
        ),
        (
            licence,
            "Licence",
            "GE:GNERC:GAS:" + attrs["notice"]["licence_number"],
            "GNERC gas licence " + attrs["notice"]["licence_number"],
            {
                "identifier": attrs["notice"]["licence_number"],
                "jurisdiction": "GE",
                "evidence_id": str(evidence),
            },
            "SOURCE_BOUND",
        ),
        (
            uuid5(identity, "company-binding"),
            "LicenceNoticeBinding",
            str(identity),
            "Company binding for licence " + attrs["notice"]["licence_number"],
            {
                "notice_id": str(identity),
                "company_id": str(selection.company_id),
                "licence_id": str(licence),
                "basis": "ISSUANCE_NOTICE_ONLY",
                "rationale": selection.rationale,
                **({"identity_binding_id": identity_binding} if identity_binding else {}),
            },
            "USER_ASSERTED",
        ),
    ]
    mutations = []
    for identifier, kind, key, name, attributes, evidence_class in specs:
        prior = None
        try:
            prior = resources.get_resource(principal, identifier)["resource"]
            if prior["object_type"] != kind:
                raise WorkspaceError(409, "Licence source identity conflicts with existing type")
            if prior["attributes"] == attributes:
                continue
            # Additional notices reuse the accepted identity without replacing its evidence.
            if (
                kind == "Licence"
                and prior["attributes"].get("identifier") == attributes["identifier"]
                and prior["attributes"].get("jurisdiction") == "GE"
            ):
                continue
            if kind != "LicenceNoticeBinding":
                raise WorkspaceError(409, "Existing licence source resource cannot be overwritten")
        except WorkspaceError as exc:
            if exc.status != 404:
                raise
        mutations.append(
            ResourceMutation(
                resource_id=identifier,
                object_type=kind,
                identity_key=key,
                display_name=name,
                attributes=attributes,
                valid_from=datetime.now(UTC),
                expected_version_id=prior["version_id"] if prior else None,
                evidence_class=evidence_class,
            )
        )
    if not mutations:
        raise WorkspaceError(409, "Licence notice and company binding are already published")
    return resources.propose(
        principal,
        ResourceProposal(
            title="Publish original licence issuance evidence",
            rationale=selection.rationale,
            access_entity=principal.scope.legal_entity_id,
            mutations=mutations,
        ),
    )
