"""Adapter boundaries, without inventing canonical IDs for retained source rows."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from finai_api.domain.function_execution import FunctionDefinition, FunctionInvocation
from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.services import function_execution, worksheet_function
from finai_api.services.workspace import WorkspaceError


def definition():
    manifest = function_execution.manifest("source.retained-xls-worksheet/v1")
    return FunctionDefinition.model_validate(
        {
            "evidence_id": str(uuid4()),
            "definition": {
                **{
                    key: manifest[key]
                    for key in (
                        "implementation_id",
                        "determinism",
                        "code_sha256",
                        "dependency_sha256",
                    )
                },
                "document_id": "doc_" + "a" * 64,
                "source_sha256": "b" * 64,
                "sheet": "Observed",
                "first_row": 7,
                "row_count": 4,
            },
        }
    )


def request(offset=0, limit=2):
    return FunctionInvocation(
        function=VersionReference(resource_id=uuid4(), version_id=uuid4()),
        valid_at=datetime.now(UTC),
        known_at=datetime.now(UTC),
        offset=offset,
        limit=limit,
    )


def test_worksheet_manifest_and_typed_input_reject_cross_adapter_parameters():
    spec = definition()
    manifest = function_execution.manifest(spec.definition.implementation_id)
    assert manifest["maximum_rows"] == 50 and manifest["maximum_columns"] == 256
    assert manifest["maximum_properties"] == 0 and manifest["capabilities"]["write"] is False
    with pytest.raises(ValidationError):
        FunctionDefinition.model_validate({**spec.model_dump(), "object_set_id": uuid4()})
    with pytest.raises(ValidationError):
        FunctionDefinition.model_validate({**spec.model_dump(), "evidence_id": None})
    with pytest.raises(WorkspaceError, match="not installed"):
        function_execution.manifest("untrusted-user-code")


def test_reviewed_worksheet_window_denies_crossing_before_source_read():
    with pytest.raises(WorkspaceError, match="reviewed worksheet window"):
        worksheet_function.source_plan(None, request(3, 2), definition(), {})


def test_worksheet_result_preserves_typed_cells_and_relative_paging(monkeypatch):
    cells = [
        {"coordinate": "Observed!A8", "type": 1, "value": "001"},
        {"coordinate": "Observed!B8", "type": 2, "value": 0.0},
        {"coordinate": "Observed!C8", "type": 0, "value": ""},
    ]
    source = {
        "document_id": "doc_" + "a" * 64,
        "sha256": "b" * 64,
        "sheet": "Observed",
        "first_row": 7,
        "row_count": 4,
    }

    def preview(p, document, sheet, offset, limit):
        assert (document, sheet, offset, limit) == (source["document_id"], "Observed", 7, 2)
        return {
            "sha256": source["sha256"],
            "rows": [{"row": 8, "cells": cells}],
            "offset": 7,
            "row_count": 20,
            "column_count": 3,
            "date_mode": 0,
            "next_offset": 9,
        }

    monkeypatch.setattr(worksheet_function, "preview", preview)
    plan = {
        "source_document": source,
        "function": {},
        "implementation": {},
        "plan_hash": "hash",
        "static_dependencies": [],
    }
    result = worksheet_function.execute(None, request(), plan)
    assert result["source_rows"] == [{"row": 8, "cells": cells}]
    assert result["objects"] == result["derived_values"] == []
    assert result["next_offset"] == 2 and result["source_document"] == source
    assert result["current_use_authorized"] is False
