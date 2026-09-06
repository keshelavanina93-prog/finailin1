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
        for key in [
            "scope",
            "company",
            "chart",
            "ledger",
            "book",
            "period",
            "calendar",
            "currency",
            "mapping",
        ]
    }

    def node(**attrs):
        return {"attributes": attrs, "evidence_class": "USER_ASSERTED", "object_type": "Currency"}

    nodes = {
        ids["scope"]: node(
            legal_entity_id=ids["company"],
            chart_id=ids["chart"],
            observed_from="2025-11-01",
            observed_through="2025-11-30",
            source_profile="1c_journal",
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
        ids["mapping"]: {**node(), "object_type": "MappingVersion"},
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
            "contract_version": "2",
            "functional_currency_id": ids["currency"],
            "currency_policy": "SOURCE_AMOUNT_ONLY",
            "account_mapping_id": ids["mapping"],
            "dimension_mapping_id": ids["mapping"],
            "granularity": "SOURCE_ROW",
            "deepest_valid_drill": "SOURCE_ROW",
            "amount_field": "amount",
            "amount_semantics": "SIGNED_MOVEMENT",
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
    attrs = {
        key: value
        for key, value in attrs.items()
        if key in {"scope_id", "source_use", "rationale", "contract_version"}
    }
    validate_context(
        None, item.model_copy(update={"attributes": attrs}), lambda identity, *_: nodes[identity]
    )


@pytest.mark.parametrize(
    "field",
    [
        "contract_version",
        "functional_currency_id",
        "account_mapping_id",
        "dimension_mapping_id",
        "amount_field",
        "amount_semantics",
        "granularity",
        "deepest_valid_drill",
        "currency_policy",
    ],
)
def test_incomplete_interpretation_cannot_activate(field):
    item, nodes, _ = context()
    del item.attributes[field]
    with pytest.raises(WorkspaceError):
        validate_context(None, item, lambda identity, *_: nodes[identity])


def test_unresolved_context_is_reviewable_but_cannot_activate():
    item, nodes, _ = context()
    attrs = {
        "scope_id": item.attributes["scope_id"],
        "source_use": "REVIEW_CANDIDATE",
        "contract_version": "2",
        "rationale": "Preserve the unresolved source interpretation",
        "unresolved_reason": "Ledger and source amount currency are not established",
    }
    validate_context(
        None, item.model_copy(update={"attributes": attrs}), lambda identity, *_: nodes[identity]
    )
    attrs["source_use"] = "ACCOUNTING_INPUT"
    with pytest.raises(WorkspaceError):
        validate_context(
            None,
            item.model_copy(update={"attributes": attrs}),
            lambda identity, *_: nodes[identity],
        )


def test_tb_cannot_claim_transaction_drill():
    item, nodes, ids = context()
    nodes[ids["scope"]]["attributes"]["source_profile"] = "1c_tb"
    with pytest.raises(WorkspaceError):
        validate_context(None, item, lambda identity, *_: nodes[identity])
