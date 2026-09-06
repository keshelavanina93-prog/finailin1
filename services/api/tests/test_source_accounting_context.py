"""Accounting context must follow the source, independently of a user's sign-in period."""

from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4, uuid5

import pytest

from finai_api.domain.resources import ResourceMutation
from finai_api.services.source_accounting_context import validate_context
from finai_api.services.workspace import WorkspaceError


def context():
    ids = {
        key: str(uuid4())
        for key in ["scope", "company", "chart", "ledger", "book", "period", "calendar", "currency"]
    }

    def node(**attrs):
        return {"attributes": attrs, "evidence_class": "USER_ASSERTED"}

    nodes = {
        ids["scope"]: node(
            legal_entity_id=ids["company"],
            chart_id=ids["chart"],
            observed_from="2025-11-01",
            observed_through="2025-11-30",
        ),
        ids["ledger"]: node(
            legal_entity_id=ids["company"],
            chart_id=ids["chart"],
            calendar_id=ids["calendar"],
            currency_id=ids["currency"],
        ),
        ids["book"]: node(ledger_id=ids["ledger"]),
        ids["period"]: node(
            calendar_id=ids["calendar"], starts_on="2025-11-01", ends_on="2025-11-30"
        ),
        ids["currency"]: node(code="GEL"),
    }
    nodes[ids["scope"]]["evidence_class"] = "SOURCE_BOUND"
    from uuid import UUID

    item = ResourceMutation(
        resource_id=uuid5(UUID(ids["scope"]), "accounting-binding"),
        object_type="SourceAccountingBinding",
        identity_key="test-context",
        display_name="Context",
        valid_from=datetime.now(UTC),
        attributes={
            "scope_id": ids["scope"],
            "source_use": "ACCOUNTING_INPUT",
            **{key + "_id": ids[key] for key in ["ledger", "book", "period", "currency"]},
            "currency_role": "FUNCTIONAL",
            "rationale": "Explicit accounting configuration",
        },
    )
    return item, nodes, ids


def test_context_does_not_read_sign_in_period_or_currency():
    item, nodes, _ = context()
    validate_context(None, item, lambda identity, *_: nodes[identity])


@pytest.mark.parametrize("change", ["company", "book", "period", "currency", "template"])
def test_reject_inconsistent_accounting_context(change):
    item, nodes, ids = context()
    if change == "company":
        nodes[ids["ledger"]]["attributes"]["legal_entity_id"] = str(uuid4())
    elif change == "book":
        nodes[ids["book"]]["attributes"]["ledger_id"] = str(uuid4())
    elif change == "period":
        nodes[ids["period"]]["attributes"]["ends_on"] = "2025-11-29"
    elif change == "currency":
        nodes[ids["ledger"]]["attributes"]["currency_id"] = str(uuid4())
    else:
        nodes[ids["currency"]]["evidence_class"] = "REFERENCE_TEMPLATE"
    with pytest.raises(WorkspaceError):
        validate_context(None, item, lambda identity, *_: nodes[identity])


def test_reference_cannot_be_an_accounting_input():
    item, nodes, _ = context()
    attrs = deepcopy(item.attributes)
    attrs["source_use"] = "STRUCTURAL_REFERENCE"
    with pytest.raises(WorkspaceError):
        validate_context(
            None,
            item.model_copy(update={"attributes": attrs}),
            lambda identity, *_: nodes[identity],
        )
    for key in ["ledger_id", "book_id", "period_id", "currency_id", "currency_role"]:
        del attrs[key]
    validate_context(
        None, item.model_copy(update={"attributes": attrs}), lambda identity, *_: nodes[identity]
    )
