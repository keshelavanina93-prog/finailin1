"""Exact balance and full-bundle mutation safeguards; synthetic amounts only."""

from contextlib import nullcontext
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from finai_api.domain.journal_balance import balanced_amounts
from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.services.journal_balance import validate_bundle
from finai_api.services.workspace import WorkspaceError


@pytest.mark.parametrize(
    "granularity,profile",
    [("PERIOD_ACCOUNT", "1c_journal"), ("SOURCE_ROW", "1c_tb"), ("SOURCE_ROW", "seg_expense_base")],
)
def test_source_summaries_cannot_be_promoted_to_journals(granularity, profile):
    from test_accounting_promotion import item, journal_fixture

    from finai_api.services.accounting_promotion import validate_journal

    nodes, entry, _, binding = journal_fixture()
    binding["attributes"]["granularity"] = granularity
    nodes[binding["attributes"]["scope_id"]]["attributes"]["source_profile"] = profile
    with pytest.raises(WorkspaceError, match="source-row journal evidence"):
        validate_journal(item("JournalEntry", entry), lambda identity, *_: nodes[identity])


def bundle():
    journal, debit, credit, binding, currency = [uuid4() for _ in range(5)]
    common = {"valid_from": datetime(2026, 1, 1, tzinfo=UTC)}
    entry = ResourceMutation(
        resource_id=journal,
        object_type="JournalEntry",
        identity_key="test:entry",
        display_name="SYNTHETIC entry",
        attributes={
            "accounting_binding_id": str(binding),
            "definition": {"contract": "balanced-journal/1", "line_ids": [str(debit), str(credit)]},
        },
        **common,
    )
    lines = [
        ResourceMutation(
            resource_id=identity,
            object_type="JournalLine",
            identity_key="test:" + side,
            display_name="SYNTHETIC " + side,
            attributes={
                "journal_id": str(journal),
                "accounting_binding_id": str(binding),
                "side": side,
                "amount": {"amount": "0.10", "currency_id": str(currency)},
            },
            **common,
        )
        for identity, side in [(debit, "DEBIT"), (credit, "CREDIT")]
    ]
    return ResourceProposal(
        title="Synthetic journal bundle",
        rationale="Check exact journal contract",
        access_entity="synthetic",
        mutations=[entry, *lines],
    )


def validate(proposal, old=()):
    cursor = SimpleNamespace(execute=lambda *_: SimpleNamespace(fetchall=lambda: old))
    conn = SimpleNamespace(cursor=lambda **_: nullcontext(cursor))
    return validate_bundle(
        conn, SimpleNamespace(scope=SimpleNamespace(tenant_id=uuid4())), proposal
    )


def test_balance_is_exact_and_does_not_round_small_difference():
    proposal = bundle()
    assert validate(proposal)[0]["debit"] == "0.10"
    proposal.mutations[2].attributes["amount"]["amount"] = "0.100001"
    with pytest.raises(WorkspaceError, match="balance exactly"):
        validate(proposal)


@pytest.mark.parametrize(
    "value", ["0", "-1", "NaN", "Infinity", "1e3", 1.0, "0.0000001", "100000000000000000000"]
)
def test_invalid_amounts_never_enter_balance(value):
    with pytest.raises(ValueError):
        balanced_amounts([{"side": "DEBIT", "amount": {"amount": value}}])


@pytest.mark.parametrize(
    "change", ["missing", "extra", "side", "currency", "time", "revoke", "binding"]
)
def test_bundle_cannot_be_partially_changed(change):
    proposal = bundle()
    if change == "missing":
        proposal = proposal.model_copy(update={"mutations": proposal.mutations[1:]})
    elif change == "extra":
        proposal.mutations[0].attributes["definition"]["line_ids"].append(str(uuid4()))
    elif change == "side":
        proposal.mutations[1].attributes["side"] = "CREDIT"
    elif change == "currency":
        proposal.mutations[1].attributes["amount"]["currency_id"] = str(uuid4())
    elif change == "binding":
        proposal.mutations[1].attributes["accounting_binding_id"] = str(uuid4())
    else:
        field, value = (
            ("valid_from", datetime.now(UTC) + timedelta(days=30))
            if change == "time"
            else ("authority_state", "REVOKED")
        )
        proposal.mutations[1] = proposal.mutations[1].model_copy(update={field: value})
    with pytest.raises(WorkspaceError):
        validate(proposal)


def test_existing_future_editing_head_and_reparenting_cannot_be_omitted():
    proposal = bundle()
    line = proposal.mutations[1]
    version = uuid4()
    old = {
        "resource_id": line.resource_id,
        "version_id": version,
        "object_type": "JournalLine",
        "attributes": deepcopy(line.attributes),
        "valid_from": datetime.now(UTC) + timedelta(days=30),
    }
    with pytest.raises(WorkspaceError, match="editing head"):
        validate(proposal, [old])
    proposal.mutations[1] = line.model_copy(update={"expected_version_id": version})
    assert validate(proposal, [old])[0]["status"] == "BALANCED"
    old["attributes"]["journal_id"] = str(uuid4())
    with pytest.raises(WorkspaceError, match="reparented"):
        validate(proposal, [old])


def test_balanced_publication_does_not_inherit_callers_exponent_limits():
    from decimal import Inexact, localcontext

    from finai_api.domain.journal_balance import balanced_amounts

    lines = [{"side": side, "amount": {"amount": "1731.97"}} for side in ("DEBIT", "CREDIT")]
    with localcontext() as caller:
        caller.prec = 2
        caller.Emax = 2
        caller.traps[Inexact] = True
        assert balanced_amounts(lines) == {"debit": "1731.97", "credit": "1731.97"}
        assert caller.prec == 2 and caller.Emax == 2
