from datetime import date

import pytest
from pydantic import ValidationError

from finai_api.domain.regulation import RegulatoryDefinition, assess_rule


def definition(**changes):
    return RegulatoryDefinition.model_validate(
        {
            "legal_status": "ENACTED",
            "source_version": "test-version",
            "source_version_complete": True,
            "provision": "test provision",
            "activity": "DISTRIBUTION",
            "effective_from": "2027-01-01",
            "effective_to": "2028-01-01",
            "minimum_customers": 50000,
            "obligation": "Test reporting obligation",
            "deadline": "2027-12-31",
            **changes,
        }
    )


@pytest.mark.parametrize(
    "day,state",
    [
        ("2026-12-31", "FUTURE_EFFECTIVE"),
        ("2027-01-01", "CURRENT_EFFECTIVE"),
        ("2028-01-01", "EXPIRED"),
    ],
)
def test_effective_window_boundaries(day, state):
    result = assess_rule(definition(), date.fromisoformat(day), "DISTRIBUTION", 50000)
    assert result["legal_state"] == state
    assert result["effective_obligation"] == (state == "CURRENT_EFFECTIVE")


@pytest.mark.parametrize(
    "changes,state",
    [
        ({"legal_status": "DRAFT"}, "DRAFT"),
        ({"legal_status": "POLICY_INTENT"}, "POLICY_INTENT"),
        ({"source_version_complete": False}, "SOURCE_VERSION_INCOMPLETE"),
    ],
)
def test_date_cannot_activate_non_authoritative_source(changes, state):
    result = assess_rule(definition(**changes), date(2027, 7, 1), "DISTRIBUTION", 60000)
    assert result["legal_state"] == state
    assert result["effective_obligation"] is False


def test_unknown_count_does_not_become_zero_or_applicable():
    at = date(2027, 7, 1)
    assert (
        assess_rule(definition(), at, "DISTRIBUTION", None)["applicability"] == "CONTEXT_REQUIRED"
    )
    assert assess_rule(definition(), at, "DISTRIBUTION", 49999)["applicability"] == "NOT_APPLICABLE"
    assert assess_rule(definition(), at, "TRANSMISSION", 60000)["applicability"] == "NOT_APPLICABLE"


def test_invalid_window_rejected():
    with pytest.raises(ValidationError):
        definition(effective_to="2026-01-01")


def test_rule_requires_same_evidence_as_pinned_act():
    from datetime import UTC, datetime
    from uuid import uuid4

    from finai_api.domain.resources import ResourceMutation
    from finai_api.services.ontology_definition_validation import validate_definition
    from finai_api.services.workspace import WorkspaceError

    item = ResourceMutation(
        object_type="RegulatoryRule",
        identity_key="test-rule",
        display_name="Test rule",
        valid_from=datetime.now(UTC),
        evidence_class="SOURCE_BOUND",
        attributes={
            "definition": definition().model_dump(mode="json"),
            "act_id": str(uuid4()),
            "evidence_id": str(uuid4()),
        },
    )

    def target(*args):
        return {"attributes": {"evidence_id": str(uuid4())}}

    with pytest.raises(WorkspaceError, match="evidence must match"):
        validate_definition(item, {}, {}, target)
