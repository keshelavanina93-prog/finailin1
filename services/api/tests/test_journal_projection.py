"""Journal-only projection cannot expose unmatched or missing source movements."""
# ruff: noqa: F811

import pytest
from test_semantic_entity_movements import case  # noqa: F401

from finai_api.domain.semantic_analysis import FieldDefinition, Value
from finai_api.services import semantic_analysis
from finai_api.services.journal_projection import build_projection
from finai_api.services.semantic_analysis_movements import build
from finai_api.services.workspace import WorkspaceError


def test_accepted_subset_exact_cells_and_stale_selection(case):
    history, request = case
    source = semantic_analysis.project(None, request)
    source = source.model_copy(
        update={
            "descriptor": source.descriptor.model_copy(
                update={
                    "fields": [
                        *source.descriptor.fields,
                        FieldDefinition(
                            key="account_code",
                            label="Account code",
                            kind="identifier",
                            role="ATTRIBUTE",
                            definition=source.descriptor.function,
                        ),
                    ]
                }
            ),
            "rows": [
                r.model_copy(
                    update={"values": {**r.values, "account_code": Value(value="synthetic-code")}}
                )
                for r in source.rows
            ],
        }
    )
    _, plan, resolver = semantic_analysis.load(None, request.invocation_id)
    _, _, contributors = build(history, plan, resolver, request.company_id)
    movement = history["output"]["entity_movement_review"]["movements"][0]
    receipt = {
        "movement_trial_balance": [movement],
        "accepted": [{}],
        "missing_coordinates": ["Base!S3", "Base!S4"],
        "excluded_rows": [{"coordinate": "Base!S288"}],
        "rejected": [{"reason": "Retained test journal is outside the exact source"}],
        "status": "PARTIAL",
        "snapshot_at": "2026-09-08T00:00:00Z",
        "receipt_hash": "a" * 64,
    }
    result = build_projection(source, receipt, contributors, request)
    assert len(result.rows) == 1
    assert result.rows[0].values["account_code"].value == "synthetic-code"
    assert result.rows[0].values["debit_movement"].value == movement["debit"]
    coverage = {item.label: item.value for item in result.descriptor.coverage}
    assert coverage["Source rows without an accepted journal"] == "2"
    assert coverage["Source rows excluded from matching"] == "1"
    assert coverage["Journal candidates not matched"] == "1"
    assert "Partial source coverage" in coverage["Source reconciliation"]
    assert result.descriptor.excluded_evidence == source.descriptor.excluded_evidence
    selected = request.model_copy(
        update={"selected_row": result.rows[0].key, "descriptor_sha256": result.descriptor_sha256}
    )
    exact = build_projection(source, receipt, contributors, selected)
    assert exact.selection.contributor.coordinate == "Base!S2"
    assert exact.selection.contributor.cells
    with pytest.raises(WorkspaceError, match="changed"):
        build_projection(source, {**receipt, "receipt_hash": "b" * 64}, contributors, selected)
    with pytest.raises(WorkspaceError, match="coverage"):
        build_projection(source, receipt, {key: [] for key in contributors}, request)
    empty = build_projection(
        source, {**receipt, "movement_trial_balance": None, "accepted": []}, contributors, request
    )
    assert empty.rows == [] and empty.total_rows == 0
