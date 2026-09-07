# ruff: noqa: F811
"""Native storage/pin/usage checks with an explicit parser-result fixture, not parser proof."""

from datetime import UTC, datetime

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_definition_history import DB, item, retained  # noqa: F401

from finai_api.domain.function_execution import FunctionInvocation
from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.services import (
    function_execution,
    function_invocations,
    source_documents,
    transformation_runs,
    worksheet_function,
)
from finai_api.services.workspace import WorkspaceError


@DB
def test_retained_worksheet_pin_provenance_and_actual_source_row_budget(retained, monkeypatch):
    reader, publish = retained
    reader = reader.model_copy(update={"permissions": (*reader.permissions, "read", "ingest")})
    before_document = datetime.now(UTC)
    source = source_documents.retain_document(
        reader,
        "SYNTHETIC parser fixture.xls",
        b"Synthetic retained bytes; parser output mocked explicitly",
    )
    before_evidence = datetime.now(UTC)
    evidence = item("SourceEvidence", {"sha256": source["sha256"], "source_system": "SYNTHETIC"})
    publish(evidence)
    manifest = function_execution.manifest("source.retained-xls-worksheet/v1")
    specification = {
        key: manifest[key]
        for key in ("implementation_id", "determinism", "code_sha256", "dependency_sha256")
    }
    specification.update(
        document_id=source["document_id"],
        source_sha256=source["sha256"],
        sheet="Sheet1",
        first_row=0,
        row_count=2,
    )
    function = item(
        "FunctionDefinition",
        {"evidence_id": str(evidence.resource_id), "definition": specification},
    )
    row = publish(function)[0]
    now = datetime.now(UTC)
    request = FunctionInvocation(
        function=VersionReference(resource_id=row["resource_id"], version_id=row["version_id"]),
        valid_at=now,
        known_at=now,
        limit=2,
    )
    monkeypatch.setattr(
        worksheet_function,
        "preview",
        lambda *_: {
            "sha256": source["sha256"],
            "rows": [
                {"row": 1, "cells": [{"coordinate": "Sheet1!A1", "type": "text", "value": "001"}]},
                {"row": 2, "cells": [{"coordinate": "Sheet1!A2", "type": "number", "value": 12}]},
            ],
            "offset": 0,
            "row_count": 2,
            "column_count": 1,
            "date_mode": 0,
            "next_offset": None,
        },
    )
    for cutoff in (before_document, before_evidence):
        with pytest.raises(WorkspaceError):
            function_execution.plan(reader, request.model_copy(update={"known_at": cutoff}))
    result = function_invocations.invoke(reader, request)
    assert result["status"] == "SUCCEEDED"
    assert result["output"]["objects"] == []
    assert result["output"]["source_rows"][0]["cells"][0]["value"] == "001"
    usage = transformation_runs.measured_usage(reader, result["output"]["run_id"])
    assert usage["returned_rows"] == 2 and usage["derived_evaluations"] == 0
    assert usage["published_result_bytes"] > 0
    assert function_invocations.invoke(reader, request) == result
    with function_invocations._database(reader) as cursor:
        intent = cursor.execute(
            "SELECT * FROM function_invocations WHERE tenant_id=%s AND request_id=%s",
            (reader.scope.tenant_id, request.request_id),
        ).fetchone()
    for change in ({"sha256": "0" * 64}, {"first_row": 99}):
        forged = {
            **intent["plan"],
            "source_document": {**intent["plan"]["source_document"], **change},
        }
        with (
            pytest.raises(psycopg.errors.RaiseException, match="source or window"),
            function_invocations._database(reader) as cursor,
        ):
            cursor.execute(
                "INSERT INTO function_invocations "
                "(tenant_id,request_id,exact_scope,actor_id,request_hash,request,plan,plan_hash) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    reader.scope.tenant_id,
                    request.request_id,
                    Jsonb(intent["exact_scope"]),
                    reader.actor_id,
                    intent["request_hash"],
                    Jsonb(intent["request"]),
                    Jsonb(forged),
                    intent["plan_hash"],
                ),
            )
