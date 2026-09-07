"""Synthetic retained HTML: recognition and reviewed bindings are separate authorities."""

from copy import deepcopy
from hashlib import sha256
from html import escape
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from finai_api.services import corporate_disclosures as corporate
from finai_api.services import licence_notices as licence
from finai_api.services import resources
from finai_api.services.workspace import WorkspaceError


def table(identifier, rows):
    return (
        f'<div id="{identifier}"><div><table>'
        + "".join(
            "<tr>" + "".join(f"<td>{escape(cell)}</td>" for cell in row) + "</tr>" for row in rows
        )
        + "</table></div></div>"
    )


def corporate_rows():
    return [
        [
            "მშობელი/შვილობილი საწარმო",
            "საფირმო სახელწოდება",
            "საიდენტიფიკაციო ნომერი",
            "Country",
            "%",
            "Former",
        ],
        ["შვილობილი საწარმო", "SYNTHETIC A & B", "001234567", "GE", "25,50", "YES"],
        ["მშობელი საწარმო", "SYNTHETIC Parent", "009876543", "GE", "", ""],
    ]


def licence_rows():
    return [
        ["", "", "", "", "საქმიანობის სახე", "სახელმწიფო რეგისტრაციის მონაცემები", ""],
        [
            "",
            "SYNTHETIC Holder",
            "№ 00125",
            "29.02.2024",
            "ბუნებრივი გაზის განაწილება",
            "საიდენტიფიკაციო კოდი: 001234567",
            "",
        ],
        ["", "", "", "", "", "", ""],
        ["", "", "", "", "", "გაიცა უვადოდ", ""],
    ]


def content(kind, rows=None):
    if kind == "corporate":
        return table("reports-group", corporate_rows() if rows is None else rows).encode()
    return (
        '<body class="page-document-view-999001">'
        + table("maindoc", licence_rows() if rows is None else rows)
        + "</body>"
    ).encode()


class Card:
    def __init__(self, node):
        self.node = node
        self.__dict__.update(node)

    def model_dump(self, **_):
        return deepcopy(self.node)


def node(kind, attrs, *, evidence="SOURCE_BOUND", identity=None):
    return {
        "resource_id": str(identity or uuid4()),
        "version_id": str(uuid4()),
        "object_type": kind,
        "attributes": attrs,
        "evidence_class": evidence,
    }


@pytest.fixture
def boundary(monkeypatch):
    principal = SimpleNamespace(
        scope=SimpleNamespace(tenant_id=uuid4(), legal_entity_id="synthetic")
    )
    retained = {"corporate": content("corporate"), "licence": content("licence")}
    nodes = {}

    def document(_principal, identity):
        raw = retained[identity]
        return {"source_sha256": sha256(raw).hexdigest()}, raw

    def get(_principal, identity):
        if str(identity) not in nodes:
            raise WorkspaceError(404, "Synthetic resource unavailable")
        return {"resource": deepcopy(nodes[str(identity)])}

    def listing(_principal, kind, _search, offset, *_):
        return [Card(deepcopy(n)) for n in nodes.values() if n["object_type"] == kind][
            offset : offset + 100
        ]

    monkeypatch.setattr(corporate, "document_bytes", document)
    monkeypatch.setattr(licence, "document_bytes", document)
    monkeypatch.setattr(resources, "get_resource", get)
    monkeypatch.setattr(resources, "list_resources", listing)
    monkeypatch.setattr(resources, "propose", lambda _principal, proposal: proposal)
    return principal, nodes, retained


def retain_proposal(nodes, proposal):
    for mutation in proposal.mutations:
        nodes[str(mutation.resource_id)] = node(
            mutation.object_type,
            deepcopy(mutation.attributes),
            evidence=mutation.evidence_class,
            identity=mutation.resource_id,
        )


def context(reporter, related=None, **changes):
    return corporate.DisclosureContext(
        reporter_id=reporter,
        reporting_year=2024,
        reporter_code="008888888",
        rationale="Reviewed synthetic disclosure identity",
        bindings={1: related},
        **changes,
    )


def test_recognized_disclosures_preserve_former_marker_and_unknown_parent_percentage():
    rows = corporate.parse(content("corporate"))
    assert rows[0]["reported_code"] == "001234567"
    assert rows[0]["reported_name"] == "SYNTHETIC A & B"
    assert rows[0]["reported_percent"] == "25.50"
    assert rows[0]["former_indicator"] == "YES"
    assert rows[1]["reported_role"] == "PARENT"
    assert rows[1]["reported_percent"] is None


@pytest.mark.parametrize(
    "case,message",
    [
        ("utf8", "UTF-8"),
        ("oversize", "2 MB"),
        ("duplicate-table", "Recognized"),
        ("many-rows", "50 company"),
        ("width", "Unrecognized"),
        ("role", "Unrecognized"),
        ("name", "name and identifier"),
        ("code", "name and identifier"),
    ],
)
def test_disclosure_parse_refuses_ambiguous_source(case, message):
    rows = corporate_rows()
    if case == "width":
        rows[1].pop()
    if case == "role":
        rows[1][0] = "Unknown"
    if case == "name":
        rows[1][1] = ""
    if case == "code":
        rows[1][2] = ""
    if case == "many-rows":
        rows = [rows[0]] + [rows[1]] * 51
    raw = content("corporate", rows)
    if case == "utf8":
        raw = b"\xff"
    if case == "oversize":
        raw = b"x" * 2_000_001
    if case == "duplicate-table":
        raw += raw
    with pytest.raises(WorkspaceError, match=message):
        corporate.parse(raw)


def test_corporate_proposal_preserves_row_identity_and_requires_review(boundary):
    principal, nodes, _ = boundary
    reporter = node("LegalEntity", {"registration_code": "008888888"})
    nodes[reporter["resource_id"]] = reporter
    proposal = corporate.propose(principal, "corporate", context(UUID(reporter["resource_id"])))
    assert {m.object_type for m in proposal.mutations} == {
        "SourceEvidence",
        "SourceRecord",
        "LegalEntity",
        "SourceCorporateObservation",
        "CorporateDisclosureBinding",
    }
    assert proposal.access_entity == "synthetic"
    items = {m.object_type: m for m in proposal.mutations}
    assert items["SourceRecord"].attributes["coordinate"] == "reports-group/row:1"
    assert items["LegalEntity"].attributes["registration_code"] == "001234567"
    binding = items["CorporateDisclosureBinding"]
    assert binding.evidence_class == "USER_ASSERTED"
    assert binding.attributes["relationship_basis"] == "REPORTED_GROUP_DISCLOSURE"
    retain_proposal(nodes, proposal)
    for kind in ("SourceCorporateObservation", "CorporateDisclosureBinding"):
        corporate.validate(principal, items[kind], lambda key, *_: nodes[key])
    assert corporate.inspect(principal, "corporate")["rows"][0]["binding"]["resource_id"] == str(
        binding.resource_id
    )
    existing = context(UUID(reporter["resource_id"]), items["LegalEntity"].resource_id)
    with pytest.raises(WorkspaceError, match="already published"):
        corporate.propose(principal, "corporate", existing)
    changed = existing.model_copy(
        update={"rationale": "Reviewed corrected synthetic relationship context"}
    )
    revision = corporate.propose(principal, "corporate", changed)
    assert len(revision.mutations) == 1
    assert revision.mutations[0].expected_version_id == UUID(
        nodes[str(binding.resource_id)]["version_id"]
    )


def test_disclosure_selection_cannot_create_duplicate_company_or_guess_row(boundary):
    principal, nodes, _ = boundary
    existing = node("LegalEntity", {"registration_code": "001234567"})
    nodes[existing["resource_id"]] = existing
    with pytest.raises(WorkspaceError, match="select it explicitly"):
        corporate.propose(principal, "corporate", context(uuid4()))
    invalid = context(uuid4()).model_copy(update={"bindings": {99: None}})
    with pytest.raises(WorkspaceError, match="Explicit canonical"):
        corporate.propose(principal, "corporate", invalid)
    with pytest.raises(WorkspaceError, match="outside"):
        corporate.observation(principal, "corporate", 0)


@pytest.mark.parametrize("change", ["identity", "source-row", "value", "authority"])
def test_corporate_observation_rejects_source_forgery(boundary, change):
    principal, nodes, _ = boundary
    proposal = corporate.propose(principal, "corporate", context(uuid4()))
    retain_proposal(nodes, proposal)
    item = next(m for m in proposal.mutations if m.object_type == "SourceCorporateObservation")
    if change == "identity":
        item = item.model_copy(update={"resource_id": uuid4()})
    if change == "source-row":
        item.attributes["observation"]["row_number"] = True
    if change == "value":
        item.attributes["observation"]["reported_percent"] = "100"
    if change == "authority":
        item = item.model_copy(update={"evidence_class": "USER_ASSERTED"})
    with pytest.raises(WorkspaceError, match="source row"):
        corporate.validate(principal, item, lambda key, *_: nodes[key])


def test_issuance_recognition_never_establishes_current_licence_status():
    notice = licence.parse(content("licence"))
    assert notice["licence_number"] == "00125"
    assert notice["company_code"] == "001234567"
    assert notice["issued_on"] == "2024-02-29"
    assert notice["stated_term"] == "INDEFINITE"
    assert notice["current_status"] == "NOT_ESTABLISHED"
    rows = licence_rows()
    rows[3][5] = "გაიცა"
    assert licence.parse(content("licence", rows))["stated_term"] == "NOT_STATED"


@pytest.mark.parametrize(
    "case,message",
    [
        ("utf8", "UTF-8"),
        ("oversize", "2 MB"),
        ("missing-id", "Recognized"),
        ("width", "Recognized"),
        ("headers", "headers"),
        ("number", "identity/activity/date"),
        ("code", "identity/activity/date"),
        ("activity", "identity/activity/date"),
        ("date", "Invalid licence issuance date"),
        ("revoked", "unambiguous issuance"),
        ("extra-note", "unambiguous issuance"),
    ],
)
def test_licence_recognition_refuses_ambiguous_or_revoked_notice(case, message):
    rows = licence_rows()
    if case == "width":
        rows[2].pop()
    if case == "headers":
        rows[0][4] = "Unknown"
    if case == "number":
        rows[1][2] = "unknown"
    if case == "code":
        rows[1][5] = "001234567"
    if case == "activity":
        rows[1][4] = "Unknown"
    if case == "date":
        rows[1][3] = "31.02.2024"
    if case == "revoked":
        rows[3][5] += " გაუქმდა"
    if case == "extra-note":
        rows[3][6] = "additional legal condition"
    raw = content("licence", rows)
    if case == "utf8":
        raw = b"\xff"
    if case == "oversize":
        raw = b"x" * 2_000_001
    if case == "missing-id":
        raw = raw.replace(b"page-document-view-", b"other-")
    with pytest.raises(WorkspaceError, match=message):
        licence.parse(raw)


def test_licence_proposal_pins_company_and_reuses_accepted_identity(boundary):
    principal, nodes, _ = boundary
    company = node("LegalEntity", {"registration_code": "001234567"})
    nodes[company["resource_id"]] = company
    selection = licence.NoticeSelection(
        company_id=company["resource_id"], rationale="Reviewed synthetic issuance notice"
    )
    proposal = licence.propose(principal, "licence", selection)
    items = {m.object_type: m for m in proposal.mutations}
    assert items["SourceRecord"].attributes["coordinate"] == "maindoc/licence-table"
    binding = items["LicenceNoticeBinding"]
    assert proposal.source_versions[binding.resource_id][selection.company_id] == UUID(
        company["version_id"]
    )
    assert binding.attributes["basis"] == "ISSUANCE_NOTICE_ONLY"
    assert binding.evidence_class == "USER_ASSERTED"
    retain_proposal(nodes, proposal)
    for kind in ("SourceLicenceNotice", "LicenceNoticeBinding"):
        licence.validate(principal, items[kind], lambda key, *_: nodes[key])
    with pytest.raises(WorkspaceError, match="already published"):
        licence.prepare(principal, "licence", selection)
    # Another accepted evidence pin cannot be replaced merely by preparing this notice again.
    licence_id = str(items["Licence"].resource_id)
    nodes[licence_id]["attributes"]["evidence_id"] = str(uuid4())
    corrected = selection.model_copy(
        update={"rationale": "Second reviewed synthetic binding rationale"}
    )
    revision = licence.prepare(principal, "licence", corrected)
    assert [m.object_type for m in revision.mutations] == ["LicenceNoticeBinding"]
    assert revision.source_versions[binding.resource_id][UUID(licence_id)] == UUID(
        nodes[licence_id]["version_id"]
    )
    assert licence.inspect(principal, "licence")["binding"]["resource_id"] == str(
        binding.resource_id
    )


def test_licence_requires_exact_evidenced_registration_binding(boundary):
    principal, nodes, _ = boundary
    company = node("LegalEntity", {})
    nodes[company["resource_id"]] = company
    selection = licence.NoticeSelection(
        company_id=company["resource_id"], rationale="Reviewed synthetic issuance identity"
    )
    with pytest.raises(WorkspaceError, match="registration identity"):
        licence.prepare(principal, "licence", selection)
    identity = node(
        "CorporateDisclosureBinding",
        {"reporter_id": company["resource_id"], "reporter_code": "001234567"},
    )
    nodes[identity["resource_id"]] = identity
    proposal = licence.prepare(principal, "licence", selection)
    binding = next(m for m in proposal.mutations if m.object_type == "LicenceNoticeBinding")
    assert binding.attributes["identity_binding_id"] == identity["resource_id"]
    assert proposal.source_versions[binding.resource_id][UUID(identity["resource_id"])] == UUID(
        identity["version_id"]
    )
    retain_proposal(nodes, proposal)
    licence.validate(principal, binding, lambda key, *_: nodes[key])


@pytest.mark.parametrize("kind", ["corporate", "licence"])
@pytest.mark.parametrize("conflict", ["type", "retained-attributes"])
def test_preparation_cannot_overwrite_retained_source(boundary, kind, conflict):
    principal, nodes, _ = boundary
    company = node("LegalEntity", {"registration_code": "001234567"})
    nodes[company["resource_id"]] = company
    if kind == "corporate":
        selected = context(uuid4(), UUID(company["resource_id"]))

        def prepare():
            return corporate.propose(principal, kind, selected)
    else:
        selected = licence.NoticeSelection(
            company_id=company["resource_id"], rationale="Reviewed synthetic identity evidence"
        )

        def prepare():
            return licence.prepare(principal, kind, selected)

    proposal = prepare()
    source = next(m for m in proposal.mutations if m.object_type == "SourceRecord")
    prior = node("SourceRecord", deepcopy(source.attributes), identity=source.resource_id)
    if conflict == "type":
        prior["object_type"] = "LegalEntity"
    else:
        prior["attributes"]["coordinate"] = "other-source-row"
    nodes[str(source.resource_id)] = prior
    with pytest.raises(WorkspaceError, match=r"conflicts|overwritten"):
        prepare()


@pytest.mark.parametrize(
    "case,message",
    [
        ("source-authority", "retained corporate"),
        ("source-type", "retained corporate"),
        ("template-company", "non-template"),
        ("context", "context"),
        ("source-url", "identity and basis"),
        ("basis", "identity and basis"),
        ("authority", "identity and basis"),
        ("identity", "identity and basis"),
        ("registration", "registration conflicts"),
    ],
)
def test_corporate_binding_cannot_promote_unverified_relationship(boundary, case, message):
    principal, nodes, _ = boundary
    reporter = node("LegalEntity", {"registration_code": "008888888"})
    nodes[reporter["resource_id"]] = reporter
    proposal = corporate.propose(principal, "corporate", context(UUID(reporter["resource_id"])))
    retain_proposal(nodes, proposal)
    item = next(m for m in proposal.mutations if m.object_type == "CorporateDisclosureBinding")
    if case == "source-authority":
        nodes[item.attributes["observation_id"]]["evidence_class"] = "USER_ASSERTED"
    if case == "source-type":
        nodes[item.attributes["observation_id"]]["object_type"] = "SourceRecord"
    if case == "template-company":
        nodes[reporter["resource_id"]]["evidence_class"] = "REFERENCE_TEMPLATE"
    if case == "context":
        item.attributes["reporting_year"] = 1800
    if case == "source-url":
        item.attributes["source_url"] = "https://example.invalid/other"
    if case == "basis":
        item.attributes["relationship_basis"] = "CERTIFIED_OWNERSHIP"
    if case == "authority":
        item = item.model_copy(update={"evidence_class": "SOURCE_BOUND"})
    if case == "identity":
        item = item.model_copy(update={"resource_id": uuid4()})
    if case == "registration":
        nodes[reporter["resource_id"]]["attributes"]["registration_code"] = "999999999"
    with pytest.raises(WorkspaceError, match=message):
        corporate.validate(principal, item, lambda key, *_: nodes[key])


@pytest.mark.parametrize(
    "case", ["source-value", "source-coordinate", "template", "jurisdiction", "holder-code"]
)
def test_licence_binding_preserves_issuance_source_and_legal_entity(boundary, case):
    principal, nodes, _ = boundary
    company = node("LegalEntity", {"registration_code": "001234567"})
    nodes[company["resource_id"]] = company
    proposal = licence.prepare(
        principal,
        "licence",
        licence.NoticeSelection(
            company_id=company["resource_id"], rationale="Reviewed synthetic issuance source"
        ),
    )
    retain_proposal(nodes, proposal)
    items = {m.object_type: m for m in proposal.mutations}
    if case.startswith("source-"):
        item = items["SourceLicenceNotice"]
        if case == "source-value":
            item.attributes["notice"]["current_status"] = "ACTIVE"
        else:
            nodes[item.attributes["source_record_id"]]["attributes"]["coordinate"] = "another-table"
    else:
        item = items["LicenceNoticeBinding"]
        if case == "template":
            nodes[company["resource_id"]]["evidence_class"] = "REFERENCE_TEMPLATE"
        if case == "jurisdiction":
            nodes[item.attributes["licence_id"]]["attributes"]["jurisdiction"] = "US"
        if case == "holder-code":
            nodes[company["resource_id"]]["attributes"]["registration_code"] = "999999999"
    with pytest.raises(WorkspaceError, match=r"reproduce|conflicts"):
        licence.validate(principal, item, lambda key, *_: nodes[key])


@pytest.mark.parametrize("adapter", [corporate, licence], ids=["corporate", "licence"])
def test_inspection_filters_templates_and_does_not_hide_authority_store_errors(
    boundary, monkeypatch, adapter
):
    principal, nodes, _ = boundary
    real = node("LegalEntity", {})
    template = node("LegalEntity", {}, evidence="REFERENCE_TEMPLATE")
    nodes.update({real["resource_id"]: real, template["resource_id"]: template})
    document_id = "corporate" if adapter is corporate else "licence"
    assert [c["resource_id"] for c in adapter.inspect(principal, document_id)["companies"]] == [
        real["resource_id"]
    ]

    def unavailable(*_):
        raise WorkspaceError(503, "Synthetic authority store unavailable")

    monkeypatch.setattr(resources, "get_resource", unavailable)
    with pytest.raises(WorkspaceError, match="authority store unavailable"):
        adapter.inspect(principal, document_id)
    monkeypatch.setattr(resources, "list_resources", lambda *_: [Card(real)] * 100)
    with pytest.raises(WorkspaceError, match="inventory exceeds"):
        adapter.inspect(principal, document_id)
