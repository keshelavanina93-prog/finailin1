"""Retained corporate disclosures and reviewed identity bindings, not ownership inference."""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.services import resources
from finai_api.services.source_documents import document_bytes
from finai_api.services.workspace import WorkspaceError


class DisclosureContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reporter_id: UUID
    reporting_year: int = Field(ge=2000, le=2100)
    reporter_code: str = Field(pattern=r"^[0-9]{9}$")
    rationale: str = Field(min_length=10, max_length=2000)
    bindings: dict[int, UUID | None] = Field(min_length=1, max_length=24)


class GroupTable(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.active = False
        self.cell = None
        self.row = []
        self.rows = []
        self.found = 0

    def handle_starttag(self, tag, attrs):
        if tag == "div":
            if dict(attrs).get("id") == "reports-group":
                self.active = True
                self.found += 1
            if self.active:
                self.depth += 1
        if self.active and tag == "tr":
            self.row = []
        if self.active and tag in {"td", "th"}:
            self.cell = []

    def handle_data(self, data):
        if self.active and self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if self.active and tag in {"td", "th"} and self.cell is not None:
            self.row.append(" ".join(" ".join(self.cell).split()))
            self.cell = None
        if self.active and tag == "tr":
            self.rows.append(self.row)
        if self.active and tag == "div":
            self.depth -= 1
            if self.depth == 0:
                self.active = False


def parse(content: bytes) -> list[dict]:
    if len(content) > 2_000_000:
        raise WorkspaceError(422, "Corporate disclosure exceeds the 2 MB inspection limit")
    parser = GroupTable()
    try:
        parser.feed(content.decode("utf-8-sig"))
    except UnicodeError as exc:
        raise WorkspaceError(422, "Expected a retained UTF-8 Reportal group disclosure") from exc
    if (
        parser.found != 1
        or not parser.rows
        or parser.rows[0][:3]
        != ["მშობელი/შვილობილი საწარმო", "საფირმო სახელწოდება", "საიდენტიფიკაციო ნომერი"]
    ):
        raise WorkspaceError(422, "Recognized Reportal group structure table required")
    if len(parser.rows) > 51:
        raise WorkspaceError(422, "Disclosure exceeds 50 company rows")
    result = []
    for index, cells in enumerate(parser.rows[1:], 1):
        if len(cells) != 6 or cells[0] not in {"მშობელი საწარმო", "შვილობილი საწარმო"}:
            raise WorkspaceError(422, "Unrecognized corporate disclosure row")
        relation, name, code, country, percent, former = cells
        if not name or not code:
            raise WorkspaceError(422, "Corporate source row requires a name and identifier")
        value = None
        if percent:
            try:
                number = Decimal(percent.replace(" ", "").replace(",", "."))
                if not number.is_finite() or not 0 <= number <= 100:
                    raise InvalidOperation
                value = str(number)
            except InvalidOperation as exc:
                raise WorkspaceError(422, "Invalid reported participation percentage") from exc
        result.append(
            {
                "row_number": index,
                "reported_role": "PARENT" if relation == "მშობელი საწარმო" else "SUBSIDIARY",
                "reported_name": name,
                "reported_code": code,
                "reported_country": country,
                "reported_percent": value,
                "former_indicator": former,
                "raw_cells": cells,
            }
        )
    return result


def observation(principal, document_id, row_number):
    metadata, content = document_bytes(principal, document_id)
    rows = parse(content)
    if not 1 <= row_number <= len(rows):
        raise WorkspaceError(422, "Corporate disclosure row is outside the retained table")
    evidence = canonical_id(principal.scope.tenant_id, "SourceEvidence", metadata["source_sha256"])
    coordinate = f"reports-group/row:{row_number}"
    record = uuid5(evidence, coordinate)
    attrs = {
        "document_id": document_id,
        "source_record_id": str(record),
        "evidence_id": str(evidence),
        "observation": rows[row_number - 1],
    }
    return uuid5(record, "corporate-observation"), attrs, coordinate, metadata


def validate(principal, item, target):
    a, key = item.attributes, str(item.resource_id)
    if item.object_type == "SourceCorporateObservation":
        if type(a["observation"].get("row_number")) is not int:
            raise WorkspaceError(422, "Corporate observation requires an integer source row")
        identity, expected, coordinate, _ = observation(
            principal, a["document_id"], a["observation"]["row_number"]
        )
        record = target(a["source_record_id"], key, "CORPORATE_SOURCE_ROW")
        if (
            item.resource_id != identity
            or a != expected
            or item.evidence_class != "SOURCE_BOUND"
            or record["attributes"] != {"evidence_id": a["evidence_id"], "coordinate": coordinate}
        ):
            raise WorkspaceError(
                422, "Corporate observation must reproduce the retained source row"
            )
        return
    source = target(a["observation_id"], key, "CORPORATE_DISCLOSURE")
    if (
        source["object_type"] != "SourceCorporateObservation"
        or source["evidence_class"] != "SOURCE_BOUND"
    ):
        raise WorkspaceError(422, "Corporate binding requires a retained corporate observation")
    reporter = target(a["reporter_id"], key, "DISCLOSURE_REPORTER")
    related = target(a["related_entity_id"], key, "DISCLOSURE_RELATED_ENTITY")
    if (
        reporter["object_type"] != "LegalEntity"
        or related["object_type"] != "LegalEntity"
        or "REFERENCE_TEMPLATE" in {reporter["evidence_class"], related["evidence_class"]}
        or a["reporter_id"] == a["related_entity_id"]
    ):
        raise WorkspaceError(422, "Disclosure requires two distinct non-template legal entities")
    try:
        DisclosureContext(
            reporter_id=a["reporter_id"],
            reporting_year=a["reporting_year"],
            reporter_code=a["reporter_code"],
            rationale=a["rationale"],
            bindings={1: None},
        )
    except ValidationError as exc:
        raise WorkspaceError(422, "Invalid corporate disclosure context") from exc
    expected_url = f"https://reportal.ge/ka/Reports/OrgReportsByYear?q={a['reporter_code']}&year={a['reporting_year']}"
    if (
        a["source_url"] != expected_url
        or a["relationship_basis"] != "REPORTED_GROUP_DISCLOSURE"
        or item.evidence_class != "USER_ASSERTED"
        or item.resource_id != uuid5(UUID(a["observation_id"]), "identity-binding")
    ):
        raise WorkspaceError(
            422, "Corporate binding must preserve its disclosure identity and basis"
        )
    code = source["attributes"]["observation"]["reported_code"]
    for node, expected_code in [(related, code), (reporter, a["reporter_code"])]:
        if node["attributes"].get("registration_code") not in {None, expected_code}:
            raise WorkspaceError(422, "Selected company registration conflicts with the disclosure")


def inspect(principal, document_id):
    metadata, content = document_bytes(principal, document_id)
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
        raise WorkspaceError(422, "Company inventory exceeds disclosure selection limit")
    rows = []
    evidence = canonical_id(principal.scope.tenant_id, "SourceEvidence", metadata["source_sha256"])
    for row in parse(content):
        record = uuid5(evidence, f"reports-group/row:{row['row_number']}")
        identity = uuid5(record, "corporate-observation")
        try:
            binding = resources.get_resource(principal, uuid5(identity, "identity-binding"))[
                "resource"
            ]
        except WorkspaceError as exc:
            if exc.status != 404:
                raise
            binding = None
        rows.append({**row, "binding": binding})
    return {
        "document_id": document_id,
        "sha256": metadata["source_sha256"],
        "rows": rows,
        "companies": companies,
        "interpretation": "REPORTED_GROUP_DISCLOSURE",
    }


def propose(principal, document_id, context: DisclosureContext):
    data = inspect(principal, document_id)
    if not set(context.bindings).issubset({r["row_number"] for r in data["rows"]}):
        raise WorkspaceError(422, "Explicit canonical company selection is required for every row")
    specs = {}
    now = datetime.now(UTC)
    for row in data["rows"]:
        if row["row_number"] not in context.bindings:
            continue
        identity, attrs, coordinate, metadata = observation(
            principal, document_id, row["row_number"]
        )
        evidence, record = UUID(attrs["evidence_id"]), UUID(attrs["source_record_id"])
        related_id = context.bindings[row["row_number"]]
        create = related_id is None
        if create:
            matches = [
                c
                for c in data["companies"]
                if c["attributes"].get("registration_code") == row["reported_code"]
            ]
            if matches:
                raise WorkspaceError(409, "A company has this identifier; select it explicitly")
            related_id = canonical_id(
                principal.scope.tenant_id, "LegalEntity", "reported-code:" + row["reported_code"]
            )
        items = [
            (
                evidence,
                "SourceEvidence",
                metadata["source_sha256"],
                "Retained corporate disclosure",
                {"sha256": metadata["source_sha256"], "source_system": "RETAINED_DOCUMENT"},
                "SOURCE_BOUND",
            ),
            (
                record,
                "SourceRecord",
                metadata["source_sha256"] + ":" + coordinate,
                coordinate,
                {"evidence_id": str(evidence), "coordinate": coordinate},
                "SOURCE_BOUND",
            ),
            (
                identity,
                "SourceCorporateObservation",
                str(identity),
                row["reported_name"],
                attrs,
                "SOURCE_BOUND",
            ),
            (
                uuid5(identity, "identity-binding"),
                "CorporateDisclosureBinding",
                str(identity),
                f"{context.reporting_year}: {row['reported_name']}",
                {
                    "observation_id": str(identity),
                    "reporter_id": str(context.reporter_id),
                    "related_entity_id": str(related_id),
                    "reporter_code": context.reporter_code,
                    "reporting_year": context.reporting_year,
                    "source_url": f"https://reportal.ge/ka/Reports/OrgReportsByYear?q={context.reporter_code}&year={context.reporting_year}",
                    "relationship_basis": "REPORTED_GROUP_DISCLOSURE",
                    "rationale": context.rationale,
                },
                "USER_ASSERTED",
            ),
        ]
        if create:
            items.insert(
                2,
                (
                    related_id,
                    "LegalEntity",
                    "reported-code:" + row["reported_code"],
                    row["reported_name"],
                    {"registration_code": row["reported_code"], "evidence_id": str(evidence)},
                    "SOURCE_BOUND",
                ),
            )
        for identifier, kind, key, name, attributes, evidence_class in items:
            prior = None
            try:
                prior = resources.get_resource(principal, identifier)["resource"]
                if prior["object_type"] != kind:
                    raise WorkspaceError(
                        409, "Corporate source identity conflicts with existing type"
                    )
                if prior["attributes"] == attributes:
                    continue
                if kind != "CorporateDisclosureBinding":
                    raise WorkspaceError(
                        409, "Retained corporate source observation cannot be overwritten"
                    )
            except WorkspaceError as exc:
                if exc.status != 404:
                    raise
            specs[identifier] = ResourceMutation(
                resource_id=identifier,
                object_type=kind,
                identity_key=key,
                display_name=name[:200],
                attributes=attributes,
                valid_from=now,
                expected_version_id=prior["version_id"] if prior else None,
                evidence_class=evidence_class,
            )
    if not specs:
        raise WorkspaceError(409, "This disclosure and its identity bindings are already published")
    return resources.propose(
        principal,
        ResourceProposal(
            title="Bind retained corporate disclosure to canonical companies",
            rationale=context.rationale,
            access_entity=principal.scope.legal_entity_id,
            mutations=list(specs.values()),
        ),
    )
