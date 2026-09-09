from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from finai_api.domain.retained_reports import ReportComposition, SaveRetainedReport


def composition():
    return {
        "company_id": str(uuid4()),
        "valid_at": "2025-01-31T23:59:59.123456+04:00",
        "known_at": "2026-09-09T00:00:00.654321+04:00",
        "title": "Retained account review",
        "commentary": "Author observation, not financial certification",
        "sections": [
            {
                "section_id": str(uuid4()),
                "title": "Account movements",
                "invocation_id": str(uuid4()),
                "receipt_hash": "a" * 64,
                "descriptor_sha256": "b" * 64,
                "columns": ["account", "debit"],
                "filters": [{"field": "account", "state": "NULL", "value": None}],
                "group_by": None,
            }
        ],
    }


def test_report_request_preserves_exact_order_time_and_null_selection():
    report = ReportComposition.model_validate(composition())
    assert report.valid_at.microsecond == 123456
    assert report.known_at.microsecond == 654321
    assert report.sections[0].columns == ["account", "debit"]
    assert report.sections[0].filters[0].state == "NULL"
    assert report.sections[0].filters[0].value is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("rows", []),
        ("total", "731.97"),
        ("authority_state", "CERTIFIED"),
        ("current_use_authorized", True),
        ("amount", "1.00"),
    ],
)
def test_client_cannot_supply_values_or_promote_report_authority(field, value):
    request = composition()
    request["sections"][0][field] = value
    with pytest.raises(ValidationError):
        ReportComposition.model_validate(request)


def test_report_refuses_duplicate_sections_columns_filters_and_unpinned_revision():
    original = composition()
    variants = []
    request = deepcopy(original)
    request["sections"] *= 2
    variants.append(request)
    request = deepcopy(original)
    request["sections"][0]["columns"] *= 2
    variants.append(request)
    request = deepcopy(original)
    request["sections"][0]["filters"] *= 2
    variants.append(request)
    request = deepcopy(original)
    request["sections"][0]["descriptor_sha256"] = "latest"
    variants.append(request)
    request = deepcopy(original)
    request["known_at"] = "2026-09-09T00:00:00"
    variants.append(request)
    for request in variants:
        with pytest.raises(ValidationError):
            ReportComposition.model_validate(request)


def test_save_requires_preview_pin_and_explicit_revision_identity():
    request = {
        "request_id": str(uuid4()),
        "report_id": str(uuid4()),
        "expected_preview_sha256": "c" * 64,
        "composition": composition(),
    }
    saved = SaveRetainedReport.model_validate(request)
    assert saved.previous_proposal_id is None
    for missing in ("request_id", "report_id", "expected_preview_sha256"):
        invalid = {key: value for key, value in request.items() if key != missing}
        with pytest.raises(ValidationError):
            SaveRetainedReport.model_validate(invalid)
