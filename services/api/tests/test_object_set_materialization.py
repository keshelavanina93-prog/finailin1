"""Reviewed complete materialization retains page partitions without expanding public pages."""

# ruff: noqa:F811
from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_definition_history import DB, item, retained  # noqa:F401
from test_temporal_observations import native_temporal_case

from finai_api.domain.function_execution import (
    FunctionImplementation,
    FunctionInvocation,
    Materialization,
    RetainedResultInput,
)
from finai_api.services import function_execution, function_invocations
from finai_api.services.object_set_materialization import page_hash, validate
from finai_api.services.resources import resource_connection
from finai_api.services.workspace import WorkspaceError


@pytest.mark.parametrize(
    "config",
    [
        {"max_objects": True, "max_pages": 2},
        {"max_objects": 1001, "max_pages": 2},
        {"max_objects": 2, "max_pages": 11},
        {"max_objects": 0, "max_pages": 1},
    ],
)
def test_materialization_bounds(config):
    with pytest.raises(ValueError):
        Materialization(**config)


def test_legacy_and_excluded_calculations():
    manifest = function_execution.manifest()
    base = {
        k: manifest[k]
        for k in ("implementation_id", "determinism", "code_sha256", "dependency_sha256")
    }
    assert "materialization" not in FunctionImplementation(**base).model_dump()
    with pytest.raises(ValueError):
        FunctionImplementation(
            **base,
            materialization={"max_objects": 300, "max_pages": 2},
            derived_property_ids=[uuid4()],
        )
    with pytest.raises(ValueError):
        FunctionImplementation(
            **base,
            materialization={"max_objects": 300, "max_pages": 2},
            group_count={"schema_id": uuid4(), "fields": ["day"]},
        )


def materialization_case(retained):
    reader, initial, _ = native_temporal_case(retained)
    _, publish = retained
    kind = initial["output"]["objects"][0]["object_type"]
    rows = [item(kind, {"day": "2025-11-03"}) for _ in range(201)]
    for offset in range(0, len(rows), 100):
        publish(*rows[offset : offset + 100])
    selected = item("ObjectSetDefinition", {"definition": {"object_type": kind}})
    publish(selected)
    manifest = function_execution.manifest()
    base = {
        k: manifest[k]
        for k in ("implementation_id", "determinism", "code_sha256", "dependency_sha256")
    }
    config = {"max_objects": 300, "max_pages": 2}
    schema = initial["output"]["objects"][0]["schema_version_id"]
    # Exact schema resource is available from the retained source query's typed objects.
    with resource_connection(reader) as conn:
        schema_id = conn.execute(
            "SELECT resource_id FROM resource_versions WHERE tenant_id=%s AND version_id=%s",
            (reader.scope.tenant_id, schema),
        ).fetchone()[0]
    source = item(
        "FunctionDefinition",
        {
            "object_set_id": str(selected.resource_id),
            "definition": {**base, "materialization": config},
        },
    )
    downstream = item(
        "FunctionDefinition",
        {
            "object_set_id": str(selected.resource_id),
            "definition": {
                **base,
                "materialization": config,
                "temporal_extent": {"schema_id": str(schema_id), "field": "day"},
            },
        },
    )
    source_row, downstream_row = publish(source, downstream)
    now = datetime.now(UTC)
    request = FunctionInvocation(
        function={k: source_row[k] for k in ("resource_id", "version_id")},
        valid_at=now,
        known_at=now,
        limit=200,
    )
    return reader, request, downstream_row, config, schema


@DB
def test_native_materialization_partition_retained_extent_and_bounds(retained, monkeypatch):
    reader, request, downstream, config, _ = materialization_case(retained)
    source = function_invocations.invoke(reader, request)
    assert source["status"] == "SUCCEEDED", source
    output = source["output"]
    material = output["materialization"]
    assert output["total"] == len(output["objects"]) == 205
    assert [len(page["object_pins"]) for page in material["pages"]] == [200, 5]
    assert output["query"]["limit"] == 200 and output["next_offset"] is None
    assert material["page_count"] == 2 and material["object_count"] == 205
    compiled = function_execution.plan(reader, request)
    with resource_connection(reader) as conn:
        assert all(page_hash(page, conn) == page["page_hash"] for page in material["pages"])
        for mutation in ["duplicate", "context", "missing", "hash"]:
            bad = deepcopy(output)
            page = bad["materialization"]["pages"][1]
            if mutation == "duplicate":
                page["object_pins"][0] = bad["materialization"]["pages"][0]["object_pins"][0]
            if mutation == "context":
                page["query"]["search"] = "changed"
            if mutation == "missing":
                bad["materialization"]["pages"].pop()
            if mutation == "hash":
                page["page_hash"] = "0" * 64
            else:
                page["page_hash"] = page_hash(page, conn)
            with pytest.raises(WorkspaceError):
                validate(bad, config, material["object_set"], conn)
            with pytest.raises(psycopg.errors.RaiseException), conn.transaction():
                conn.execute(
                    "SELECT g8_validate_object_materialization(%s,%s,%s)",
                    (Jsonb(bad), Jsonb(compiled), reader.scope.tenant_id),
                )
    assert function_invocations.invoke(reader, request) == source
    too_many_pages = function_invocations.invoke(
        reader, request.model_copy(update={"request_id": uuid4(), "limit": 100})
    )
    assert too_many_pages["status"] == "FAILED" and too_many_pages["output"] is None
    bound = FunctionInvocation(
        function={k: downstream[k] for k in ("resource_id", "version_id")},
        valid_at=request.valid_at,
        known_at=request.known_at,
        limit=200,
        input_result=RetainedResultInput(invocation_id=request.request_id),
    )
    from finai_api.services import object_set_materialization

    monkeypatch.setattr(
        object_set_materialization,
        "collect",
        lambda *a, **kw: pytest.fail("Bound input must not collect pages again"),
    )
    result = function_invocations.invoke(reader, bound)
    assert result["status"] == "SUCCEEDED", result
    assert result["output"]["objects"] == output["objects"]
    assert result["output"]["materialization"] == material
    assert result["output"]["temporal_extent"]["object_count"] == 205
    assert result["output"]["temporal_extent"]["coverage"] == "COMPLETE_BOUNDED_MATERIALIZATION"
    assert result["output"]["temporal_extent"]["earliest"]["normalized_value"] == "2025-11-01"
    assert function_invocations.invoke(reader, bound) == result
