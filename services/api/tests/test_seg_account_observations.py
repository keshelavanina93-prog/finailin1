from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_seg_expense_source import workbook

from finai_api.services import seg_account_observations as observations
from finai_api.services.workspace import WorkspaceError


def setup(monkeypatch, definitions=None):
    content = workbook()
    digest = sha256(content).hexdigest()
    monkeypatch.setattr(
        observations, "read_source", lambda *_: ({"source_sha256": digest}, content)
    )
    monkeypatch.setattr(
        observations.source_company_alias,
        "inspect",
        lambda *_: {"accepted": True, "source_sha256": digest},
    )
    monkeypatch.setattr(
        observations.resources, "list_resources", lambda *_args, **_kwargs: definitions or []
    )


def definition(code, evidence="SOURCE_BOUND", authority="APPROVED"):
    return SimpleNamespace(
        resource_id=uuid4(),
        version_id=uuid4(),
        display_name="Retained definition",
        evidence_class=evidence,
        authority_state=authority,
        attributes={"account_code": code, "source_name": "Original source name"},
    )


def test_literal_codes_side_coordinates_and_ambiguous_candidates(monkeypatch):
    setup(
        monkeypatch,
        [
            definition("0012.01"),
            definition("0012.01"),
            definition("12.01"),
            definition("3110", "REFERENCE_TEMPLATE"),
            definition("3110", authority="REVOKED"),
        ],
    )
    result = observations.inspect(None, "ir_synthetic", "Base", "seg_expense_base", uuid4())
    assert result["row_count"] == 1 and result["observed_code_count"] == 2
    debit, credit = result["rows"]
    assert debit["code"] == "0012.01"
    assert debit["debit_count"] == 1 and debit["credit_count"] == 0
    assert debit["coordinates"] == [{"coordinate": "Base!E2", "side": "DEBIT"}]
    assert len(debit["definitions"]) == 2 and debit["candidate_state"] == "AMBIGUOUS_CANDIDATES"
    assert credit["coordinates"] == [{"coordinate": "Base!L2", "side": "CREDIT"}]
    assert credit["definitions"] == []
    assert result["mapping_state"] == "CANDIDATE_REVIEW"
    assert result["accounting_use_authorized"] is False


def test_alias_is_required_even_when_labels_match(monkeypatch):
    setup(monkeypatch)
    monkeypatch.setattr(
        observations.source_company_alias, "inspect", lambda *_: {"accepted": False}
    )
    with pytest.raises(WorkspaceError, match="alias"):
        observations.inspect(None, "ir_synthetic", "Base", "seg_expense_base", uuid4())


def test_coordinate_truncation_is_explicit(monkeypatch):
    setup(monkeypatch)
    monkeypatch.setattr(observations, "MAX_COORDINATES_PER_CODE", 0)
    result = observations.inspect(None, "ir_synthetic", "Base", "seg_expense_base", uuid4())
    assert all(
        row["coordinates_truncated"] and row["coordinate_count"] == 1 for row in result["rows"]
    )


def test_definition_inventory_overflow_refuses_partial_candidates(monkeypatch):
    setup(monkeypatch, [definition("0012.01"), definition("3110")])
    monkeypatch.setattr(observations, "MAX_DEFINITIONS", 1)
    with pytest.raises(WorkspaceError, match="inventory bound"):
        observations.inspect(None, "ir_synthetic", "Base", "seg_expense_base", uuid4())
