"""Grouped observation counts consume verified complete materializations."""

# ruff: noqa:F811
import json
from copy import deepcopy
from pathlib import Path
from time import perf_counter
from traceback import extract_tb
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_definition_history import DB, item, retained  # noqa:F401
from test_object_set_materialization import materialization_case

from finai_api.domain.function_execution import (
    FunctionImplementation,
    FunctionInvocation,
    RetainedResultInput,
)
from finai_api.services import (
    fact_runs,
    function_execution,
    function_invocations,
    object_set_materialization,
    resources,
)
from finai_api.services.grouped_observations import count_observations
from finai_api.services.workspace import WorkspaceError


def invoke_with_failure_diagnostic(principal, request, monkeypatch):
    """Keep swallowed execution failures observable without source values or secrets."""
    failures = []

    def observe(stage, operation):
        def wrapped(*args, **kwargs):
            started = perf_counter()
            try:
                return operation(*args, **kwargs)
            except Exception as exc:
                failures.append(
                    {
                        "stage": stage,
                        "elapsed_seconds": round(perf_counter() - started, 3),
                        "exception": type(exc).__name__,
                        "sqlstate": getattr(exc, "sqlstate", None),
                        "cause": type(exc.__cause__).__name__ if exc.__cause__ else None,
                        "cause_sqlstate": getattr(exc.__cause__, "sqlstate", None),
                        "frames": [
                            f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}"
                            for frame in extract_tb(exc.__traceback__)
                        ],
                    }
                )
                raise

        return wrapped

    with monkeypatch.context() as diagnostic:
        diagnostic.setattr(
            function_execution, "execute_plan", observe("execute", function_execution.execute_plan)
        )
        diagnostic.setattr(fact_runs, "retain_run", observe("retain", fact_runs.retain_run))
        result = function_invocations.invoke(principal, request)
    if result["status"] != "SUCCEEDED":
        pytest.fail(
            json.dumps(
                {
                    "status": result["status"],
                    "failure_code": result["receipt"].get("failure_code"),
                    "failures": failures,
                },
                sort_keys=True,
            ),
            pytrace=False,
        )
    return result


def test_materialized_counts_partition_and_legacy_refusal():
    schema_pin = {"resource_id": str(uuid4()), "version_id": str(uuid4()), "content_hash": "a" * 64}
    schema = {
        "object_type": "SchemaDefinition",
        "identity_key": "TestObservation",
        "attributes": {"fields": {"key": {"kind": "text", "required": False}}},
    }
    objects = [
        {
            "resource_id": str(uuid4()),
            "version_id": str(uuid4()),
            "content_hash": "b" * 64,
            "object_type": "TestObservation",
            "schema_version_id": schema_pin["version_id"],
            "attributes": {}
            if index == 0
            else {"key": None}
            if index == 1
            else {"key": "A" if index % 2 else "B"},
        }
        for index in range(205)
    ]
    page = {
        "objects": objects,
        "query": {"offset": 0, "limit": 200},
        "total": 205,
        "next_offset": None,
        "materialization": {},
    }
    config = {"schema": schema_pin, "fields": ["key"]}
    with pytest.raises(WorkspaceError, match="complete bounded"):
        count_observations(page, config, schema)
    result = count_observations(page, config, schema, materialized=True)
    assert result["coverage"] == "COMPLETE_BOUNDED_MATERIALIZATION"
    assert sum(group["count"] for group in result["groups"]) == 205
    assert {key["state"] for group in result["groups"] for key in group["key"]} == {
        "VALUE",
        "MISSING",
        "NULL",
    }
    assert {pin["version_id"] for group in result["groups"] for pin in group["contributors"]} == {
        obj["version_id"] for obj in objects
    }
    for partial in [
        {"next_offset": 200},
        {"total": 206},
        {"objects": [*objects, objects[0]], "total": 206},
    ]:
        with pytest.raises(WorkspaceError):
            count_observations({**page, **partial}, config, schema, materialized=True)


def test_reviewed_group_and_temporal_combination_preserves_calculation_refusal():
    manifest = function_execution.manifest()
    base = {
        key: manifest[key]
        for key in ("implementation_id", "determinism", "code_sha256", "dependency_sha256")
    }
    config = {
        **base,
        "materialization": {"max_objects": 300, "max_pages": 2},
        "group_count": {"schema_id": uuid4(), "fields": ["day"]},
        "temporal_extent": {"schema_id": uuid4(), "field": "day"},
    }
    assert FunctionImplementation(**config).group_count is not None
    with pytest.raises(ValueError):
        FunctionImplementation(**config, derived_property_ids=[uuid4()])


@DB
def test_native_materialized_group_counts_replay_and_sql_forgery(retained, monkeypatch):
    reader, source_request, _, config, schema_version = materialization_case(retained)
    source = invoke_with_failure_diagnostic(reader, source_request, monkeypatch)
    with resources.resource_connection(reader) as conn:
        schema_id = conn.execute(
            "SELECT resource_id FROM resource_versions WHERE tenant_id=%s AND version_id=%s",
            (reader.scope.tenant_id, schema_version),
        ).fetchone()[0]
    manifest = function_execution.manifest()
    base = {
        key: manifest[key]
        for key in ("implementation_id", "determinism", "code_sha256", "dependency_sha256")
    }
    consumer = item(
        "FunctionDefinition",
        {
            "object_set_id": source["output"]["definition_id"],
            "definition": {
                **base,
                "materialization": config,
                "group_count": {"schema_id": str(schema_id), "fields": ["day"]},
                "temporal_extent": {"schema_id": str(schema_id), "field": "day"},
            },
        },
    )
    published = retained[1](consumer)[0]
    request = FunctionInvocation(
        function={key: published[key] for key in ("resource_id", "version_id")},
        valid_at=source_request.valid_at,
        known_at=source_request.known_at,
        limit=200,
        input_result=RetainedResultInput(invocation_id=source_request.request_id),
    )
    monkeypatch.setattr(
        object_set_materialization,
        "collect",
        lambda *a, **kw: pytest.fail("Retained grouping must not collect pages"),
    )
    monkeypatch.setattr(
        function_execution.ontology_definitions,
        "run_set",
        lambda *a, **kw: pytest.fail("Retained grouping must not rerun query"),
    )
    result = function_invocations.invoke(reader, request)
    assert result["status"] == "SUCCEEDED", result
    output = result["output"]
    counts = output["group_counts"]
    assert counts["coverage"] == "COMPLETE_BOUNDED_MATERIALIZATION"
    assert counts["object_count"] == 205 and sorted(
        group["count"] for group in counts["groups"]
    ) == [1, 1, 2, 201]
    assert (
        output["objects"] == source["output"]["objects"]
        and output["materialization"] == source["output"]["materialization"]
    )
    assert {pin["version_id"] for group in counts["groups"] for pin in group["contributors"]} == {
        obj["version_id"] for obj in output["objects"]
    }
    assert output["temporal_extent"]["object_count"] == 205
    assert function_invocations.invoke(reader, request) == result
    for alteration in ["count", "duplicate", "omitted", "incomplete_page"]:
        bad = deepcopy(output)
        bad.pop("run_id")
        group = bad["group_counts"]["groups"][0]
        if alteration == "count":
            group["count"] += 1
        elif alteration == "duplicate":
            group["contributors"].append(group["contributors"][0])
        elif alteration == "omitted":
            group["contributors"].pop()
        else:
            bad["materialization"]["pages"].pop()
        forged = fact_runs.retain_run(reader, bad, runtime="shared-functions/1")
        receipt = {key: value for key, value in result["receipt"].items() if key != "proof_hash"}
        receipt["run_id"] = forged["run_id"]
        refusal = (
            "Materialization exceeds its reviewed partition bounds"
            if alteration == "incomplete_page"
            else "Observation groups must partition the exact retained objects"
        )
        with (
            pytest.raises(psycopg.errors.RaiseException, match=refusal),
            function_invocations._database(reader) as conn,
        ):
            conn.execute(
                "INSERT INTO function_invocation_results "
                "(tenant_id,request_id,exact_scope,actor_id,status,run_id,payload,proof_hash) "
                "VALUES(%s,%s,%s,%s,'SUCCEEDED',%s,%s,%s)",
                (
                    reader.scope.tenant_id,
                    request.request_id,
                    Jsonb(reader.scope.model_dump(mode="json")),
                    reader.actor_id,
                    forged["run_id"],
                    Jsonb(receipt),
                    function_execution._digest(receipt),
                ),
            )
