"""Licence identity review must not turn historical notices into current authority."""

from datetime import UTC, datetime
from uuid import uuid4, uuid5

import pytest

from finai_api.domain.resources import ResourceMutation
from finai_api.services.licence_notices import validate
from finai_api.services.workspace import WorkspaceError


def test_company_registration_binding_is_required_and_must_match():
    notice, company, licence, identity = [uuid4() for _ in range(4)]
    nodes = {
        str(notice): {
            "evidence_class": "SOURCE_BOUND",
            "attributes": {"notice": {"company_code": "208147637", "licence_number": "125"}},
        },
        str(company): {"evidence_class": "SOURCE_BOUND", "attributes": {}},
        str(licence): {
            "evidence_class": "SOURCE_BOUND",
            "attributes": {"identifier": "125", "jurisdiction": "GE"},
        },
        str(identity): {
            "attributes": {"reporter_id": str(company), "reporter_code": "208147637"},
        },
    }
    item = ResourceMutation(
        resource_id=uuid5(notice, "company-binding"),
        object_type="LicenceNoticeBinding",
        identity_key=str(notice),
        display_name="Historical issuance binding",
        attributes={
            "notice_id": str(notice),
            "company_id": str(company),
            "licence_id": str(licence),
            "basis": "ISSUANCE_NOTICE_ONLY",
            "rationale": "Reviewed original issuance evidence",
        },
        valid_from=datetime.now(UTC),
        evidence_class="USER_ASSERTED",
    )
    target = lambda key, *_: nodes[key]  # noqa: E731
    with pytest.raises(WorkspaceError, match="registration-code"):
        validate(None, item, target)
    item.attributes["identity_binding_id"] = str(identity)
    validate(None, item, target)
    nodes[str(identity)]["attributes"]["reporter_code"] = "202352514"
    with pytest.raises(WorkspaceError, match="conflicts"):
        validate(None, item, target)
    nodes[str(company)]["attributes"]["registration_code"] = "208147637"
    validate(None, item, target)
    item.attributes["basis"] = "CURRENT_AUTHORITY"
    with pytest.raises(WorkspaceError, match="conflicts"):
        validate(None, item, target)
