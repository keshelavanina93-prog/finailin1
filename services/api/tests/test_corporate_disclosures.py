"""Disclosure grain and identity guards; these are not ownership certification tests."""

from datetime import UTC, datetime
from uuid import uuid4, uuid5

import pytest

from finai_api.domain.resources import ResourceMutation
from finai_api.services.corporate_disclosures import parse, validate
from finai_api.services.workspace import WorkspaceError


def source(percent="", former=""):
    return (
        f'<div id="reports-group"><table><tr><th>მშობელი/შვილობილი საწარმო</th>'
        "<th>საფირმო სახელწოდება</th><th>საიდენტიფიკაციო ნომერი</th>"
        "<th>რეგისტრაციის ქვეყანა</th><th>წილი %</th><th>აღარ არის შვილობილი</th>"
        "</tr><tr><td>შვილობილი საწარმო</td><td>A &amp; B</td>"
        f"<td>001234567</td><td>საქართველო</td><td>{percent}</td>"
        f"<td>{former}</td></tr></table></div>"
    ).encode()


def test_preserves_unknown_percentage_leading_zero_and_former_marker():
    row = parse(source(former="YES"))[0]
    assert row["reported_percent"] is None
    assert row["reported_code"] == "001234567"
    assert row["reported_name"] == "A & B"
    assert row["former_indicator"] == "YES"
    assert parse(source("55,00"))[0]["reported_percent"] == "55.00"


@pytest.mark.parametrize("percent", ["NaN", "101", "-1", "unknown"])
def test_bad_percentages_are_not_silently_zero(percent):
    with pytest.raises(WorkspaceError):
        parse(source(percent))


def test_does_not_parse_unrelated_tables():
    with pytest.raises(WorkspaceError):
        parse(source().replace(b"reports-group", b"other-table"))


def test_binding_rejects_mismatched_company_code_and_self_parent():
    observation, reporter, related = uuid4(), uuid4(), uuid4()
    nodes = {
        str(observation): {
            "object_type": "SourceCorporateObservation",
            "evidence_class": "SOURCE_BOUND",
            "attributes": {"observation": {"reported_code": "001234567"}},
        },
        str(reporter): {
            "object_type": "LegalEntity",
            "evidence_class": "SOURCE_BOUND",
            "attributes": {},
        },
        str(related): {
            "object_type": "LegalEntity",
            "evidence_class": "SOURCE_BOUND",
            "attributes": {"registration_code": "001234567"},
        },
    }
    item = ResourceMutation(
        resource_id=uuid5(observation, "identity-binding"),
        object_type="CorporateDisclosureBinding",
        identity_key=str(observation),
        display_name="Disclosure",
        valid_from=datetime.now(UTC),
        attributes={
            "observation_id": str(observation),
            "reporter_id": str(reporter),
            "related_entity_id": str(related),
            "reporter_code": "987654321",
            "reporting_year": 2024,
            "rationale": "Source identity verified",
            "source_url": "https://reportal.ge/ka/Reports/OrgReportsByYear?q=987654321&year=2024",
            "relationship_basis": "REPORTED_GROUP_DISCLOSURE",
        },
    )
    validate(None, item, lambda key, *_: nodes[key])
    nodes[str(related)]["attributes"]["registration_code"] = "999999999"
    with pytest.raises(WorkspaceError, match="conflicts"):
        validate(None, item, lambda key, *_: nodes[key])
    attrs = {**item.attributes, "related_entity_id": str(reporter)}
    with pytest.raises(WorkspaceError, match="distinct"):
        validate(None, item.model_copy(update={"attributes": attrs}), lambda key, *_: nodes[key])
