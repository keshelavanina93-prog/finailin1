# ruff: noqa: F811
"""Bounded observation counts preserve exact contributor identities and scalar states."""

from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_definition_history import DB, item, retained  # noqa: F401

from finai_api.domain.function_execution import FunctionInvocation
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.services import fact_runs, function_execution, function_invocations
from finai_api.services.grouped_observations import count_observations
from finai_api.services.workspace import WorkspaceError


def test_group_states_partition_exact_objects_and_refuse_partial_pages():
    pin = {"resource_id": str(uuid4()), "version_id": str(uuid4()), "content_hash": "a" * 64}
    schema = {
        "object_type": "SchemaDefinition",
        "identity_key": "TestObservation",
        "attributes": {"fields": {"value": {"kind": "text", "required": False}}},
    }
    objects = [
        {
            "resource_id": str(uuid4()),
            "version_id": str(uuid4()),
            "content_hash": "b" * 64,
            "object_type": "TestObservation",
            "schema_version_id": pin["version_id"],
            "attributes": attrs,
        }
        for attrs in ({}, {"value": None}, {"value": ""}, {"value": "same"}, {"value": "same"})
    ]
    # Empty text violates the underlying canonical scalar contract.
    page = {
        "query": {"offset": 0, "limit": 10},
        "next_offset": None,
        "total": 5,
        "objects": objects,
    }
    with pytest.raises(WorkspaceError, match="violates"):
        count_observations(page, {"schema": pin, "fields": ["value"]}, schema)
    page.update(objects=[obj for obj in objects if obj["attributes"] != {"value": ""}], total=4)
    grouped = count_observations(page, {"schema": pin, "fields": ["value"]}, schema)
    assert grouped["object_count"] == 4
    assert sorted(group["count"] for group in grouped["groups"]) == [1, 1, 2]
    assert {group["key"][0]["state"] for group in grouped["groups"]} == {"MISSING", "NULL", "VALUE"}
    for incomplete in ({"next_offset": 10}, {"total": 5}, {"query": {"offset": 1, "limit": 10}}):
        with pytest.raises(WorkspaceError, match="complete bounded"):
            count_observations({**page, **incomplete}, {"schema": pin, "fields": ["value"]}, schema)


@DB
def test_native_grouped_function_receipt_and_incomplete_refusal(retained):
    reader, publish = retained
    parties = [
        item("Party", {"registration_code": code})
        for code in ("SYNTHETIC-A", "SYNTHETIC-A", "SYNTHETIC-B")
    ]
    query = item(
        "ObjectSetDefinition",
        {
            "definition": {
                "object_type": "Party",
                "resource_ids": [str(row.resource_id) for row in parties],
            }
        },
    )
    publish(*parties, query)
    manifest = function_execution.manifest()
    definition = {
        key: manifest[key]
        for key in ("implementation_id", "determinism", "code_sha256", "dependency_sha256")
    }
    definition["group_count"] = {
        "schema_id": str(canonical_id(reader.scope.tenant_id, "SchemaDefinition", "Party")),
        "fields": ["registration_code"],
    }
    function = item(
        "FunctionDefinition", {"object_set_id": str(query.resource_id), "definition": definition}
    )
    published = publish(function)[0]
    now = datetime.now(UTC)
    request = FunctionInvocation(
        function=VersionReference(
            resource_id=published["resource_id"], version_id=published["version_id"]
        ),
        valid_at=now,
        known_at=now,
        limit=10,
    )
    result = function_invocations.invoke(reader, request)
    assert result["status"] == "SUCCEEDED", result
    counts = result["output"]["group_counts"]
    assert counts["object_count"] == 3
    assert sorted(group["count"] for group in counts["groups"]) == [1, 2]
    assert {pin["version_id"] for group in counts["groups"] for pin in group["contributors"]} == {
        obj["version_id"] for obj in result["output"]["objects"]
    }
    assert function_invocations.invoke(reader, request) == result
    forged_output = deepcopy(result["output"])
    forged_output.pop("run_id")
    forged_output["group_counts"]["groups"][0]["count"] += 1
    forged = fact_runs.retain_run(reader, forged_output, runtime="shared-functions/1")
    receipt = {key: value for key, value in result["receipt"].items() if key != "proof_hash"}
    receipt["run_id"] = forged["run_id"]
    with (
        pytest.raises(psycopg.errors.RaiseException, match="partition"),
        function_invocations._database(reader) as c,
    ):
        c.execute(
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
    partial = function_invocations.invoke(
        reader, request.model_copy(update={"request_id": uuid4(), "limit": 1})
    )
    assert partial["status"] == "FAILED" and partial["output"] is None
