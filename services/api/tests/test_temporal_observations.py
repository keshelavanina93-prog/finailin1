"""Temporal extent retains complete bounded source witnesses without period authority."""

# ruff: noqa:F811
from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from test_definition_history import DB, item, retained  # noqa:F401

from finai_api.domain.function_execution import (
    FunctionImplementation,
    FunctionInvocation,
    RetainedResultInput,
)
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceProposal, ResourceReview
from finai_api.services import function_execution, function_invocations, resources
from finai_api.services.temporal_observations import extent_observations, normalize
from finai_api.services.workspace import WorkspaceError


def temporal_case(kind="datetime", attrs=None):
    pin = {"resource_id": str(uuid4()), "version_id": str(uuid4()), "content_hash": "a" * 64}
    schema = {
        "object_type": "SchemaDefinition",
        "identity_key": "TestObservation",
        "attributes": {"fields": {"when": {"kind": kind, "required": False}}},
    }
    objects = [
        {
            "resource_id": str(uuid4()),
            "version_id": str(uuid4()),
            "content_hash": "b" * 64,
            "object_type": "TestObservation",
            "schema_version_id": pin["version_id"],
            "attributes": value,
        }
        for value in (attrs or [])
    ]
    return (
        {
            "query": {"offset": 0, "limit": 200},
            "next_offset": None,
            "total": len(objects),
            "objects": objects,
        },
        {"schema": pin, "field": "when", "kind": kind},
        schema,
    )


def test_exact_bounds_ties_missing_null_and_legacy():
    page, config, schema = temporal_case(
        attrs=[
            {},
            {"when": None},
            {"when": "2026-01-01T04:00:00+04:00"},
            {"when": "2026-01-01T00:00:00.000000Z"},
            {"when": "2026-01-01T00:00:00.000001Z"},
        ]
    )
    result = extent_observations(page, config, schema)
    assert (
        result["object_count"],
        result["value_count"],
        result["missing_count"],
        result["null_count"],
    ) == (5, 3, 1, 1)
    assert result["earliest"]["normalized_value"] == "2026-01-01T00:00:00.000000Z"
    assert len(result["earliest"]["witnesses"]) == 2
    assert result["latest"]["normalized_value"] == "2026-01-01T00:00:00.000001Z"
    assert result["earliest"]["witnesses"] == sorted(
        result["earliest"]["witnesses"], key=lambda x: (x["resource_id"], x["version_id"])
    )
    for attrs in [[], [{}, {"when": None}]]:
        empty = extent_observations(*temporal_case(attrs=attrs))
        assert (
            empty["state"] == "NO_VALUES" and empty["earliest"] is None and empty["latest"] is None
        )
    manifest = function_execution.manifest()
    spec = FunctionImplementation(
        **{
            k: manifest[k]
            for k in ("implementation_id", "determinism", "code_sha256", "dependency_sha256")
        }
    )
    assert "temporal_extent" not in spec.model_dump()
    assert normalize("2024-02-29", "date") == "2024-02-29"


@pytest.mark.parametrize(
    "kind,value",
    [
        ("date", "20260201"),
        ("date", "2026-02-29"),
        ("datetime", "2026-01-01T00:00:00"),
        ("datetime", "2026-01-01T00:00:00.1234567Z"),
        ("datetime", "2026-01-01T00:00:00+16:00"),
        ("datetime", "0001-01-01T00:00:00+01:00"),
        ("datetime", True),
    ],
)
def test_invalid_temporal_values(kind, value):
    with pytest.raises(WorkspaceError):
        normalize(value, kind)


def test_incomplete_required_and_wrong_schema_refused():
    page, config, schema = temporal_case("date", [{"when": "2026-01-01"}])
    for update in [{"total": 2}, {"next_offset": 1}, {"query": {"offset": 1, "limit": 200}}]:
        with pytest.raises(WorkspaceError, match="complete bounded"):
            extent_observations({**page, **update}, config, schema)
    bad = deepcopy(page)
    bad["objects"][0]["schema_version_id"] = str(uuid4())
    with pytest.raises(WorkspaceError, match="schema differs"):
        extent_observations(bad, config, schema)
    page, config, schema = temporal_case("date", [{}])
    schema["attributes"]["fields"]["when"]["required"] = True
    with pytest.raises(WorkspaceError, match="required"):
        extent_observations(page, config, schema)


def native_temporal_case(retained):
    reader, publish = retained
    author = reader.model_copy(
        update={
            "permissions": (
                "ontology_read",
                "ontology_admin",
                "ontology_propose",
                "ontology_review",
            )
        }
    )
    kind = "TemporalFixture" + uuid4().hex[:10]
    schema = item(
        "SchemaDefinition",
        {
            "additional_fields": False,
            "fields": {
                "day": {
                    "field_id": str(uuid4()),
                    "kind": "date",
                    "required": False,
                    "semantic_id": str(
                        canonical_id(reader.scope.tenant_id, "SemanticContract", "Date")
                    ),
                }
            },
        },
    ).model_copy(update={"identity_key": kind})
    proposal = ResourceProposal(
        title="Synthetic temporal schema",
        rationale="Isolated temporal observation acceptance",
        access_entity="__PLATFORM__",
        mutations=[schema],
    )
    resources.propose(author, proposal)
    resources.review(
        author.model_copy(update={"actor_id": "synthetic-temporal-checker"}),
        proposal.proposal_id,
        ResourceReview(
            decision="APPROVED", rationale="Independent synthetic temporal schema review"
        ),
    )
    rows = [
        item(kind, attrs)
        for attrs in [{"day": "2025-11-01"}, {"day": "2025-11-07"}, {"day": "2025-11-01"}, {}]
    ]
    query = item(
        "ObjectSetDefinition",
        {
            "definition": {
                "object_type": kind,
                "resource_ids": [str(row.resource_id) for row in rows],
            }
        },
    )
    publish(*rows, query)
    manifest = function_execution.manifest()
    base = {
        k: manifest[k]
        for k in ("implementation_id", "determinism", "code_sha256", "dependency_sha256")
    }
    source = item(
        "FunctionDefinition", {"object_set_id": str(query.resource_id), "definition": base}
    )
    downstream = item(
        "FunctionDefinition",
        {
            "object_set_id": str(query.resource_id),
            "definition": {
                **base,
                "temporal_extent": {"schema_id": str(schema.resource_id), "field": "day"},
            },
        },
    )
    source_row, downstream_row = publish(source, downstream)
    now = datetime.now(UTC)
    request = FunctionInvocation(
        function={k: source_row[k] for k in ("resource_id", "version_id")},
        valid_at=now,
        known_at=now,
        limit=10,
    )
    receipt = function_invocations.invoke(reader, request)
    assert receipt["status"] == "SUCCEEDED", receipt
    bound = request.model_copy(
        update={
            "request_id": uuid4(),
            "function": request.function.model_validate(
                {k: downstream_row[k] for k in ("resource_id", "version_id")}
            ),
            "input_result": RetainedResultInput(invocation_id=request.request_id),
        }
    )
    bound = FunctionInvocation.model_validate(bound.model_dump())
    return reader, receipt, bound


@DB
def test_native_retained_temporal_extent_and_replay(retained, monkeypatch):
    reader, source, request = native_temporal_case(retained)
    monkeypatch.setattr(
        function_execution.ontology_definitions,
        "run_set",
        lambda *a, **kw: pytest.fail("retained input must not requery"),
    )
    result = function_invocations.invoke(reader, request)
    assert result["status"] == "SUCCEEDED", result
    extent = result["output"]["temporal_extent"]
    assert (extent["object_count"], extent["value_count"], extent["missing_count"]) == (4, 3, 1)
    assert (
        extent["earliest"]["normalized_value"] == "2025-11-01"
        and len(extent["earliest"]["witnesses"]) == 2
    )
    assert extent["latest"]["normalized_value"] == "2025-11-07"
    assert result["output"]["objects"] == source["output"]["objects"]
    assert result["output"]["input_result"]["receipt_hash"] == source["receipt_hash"]
    assert function_invocations.invoke(reader, request) == result
    # Terminal SQL authority recomputes both boundary values and the full tie set.
    import psycopg
    from psycopg.types.json import Jsonb

    from finai_api.services import fact_runs

    for field, value in [("normalized_value", "2025-10-31"), ("witnesses", [])]:
        forged_output = deepcopy(result["output"])
        forged_output.pop("run_id")
        forged_output["temporal_extent"]["earliest"][field] = value
        forged = fact_runs.retain_run(reader, forged_output, runtime="shared-functions/1")
        receipt = {key: value for key, value in result["receipt"].items() if key != "proof_hash"}
        receipt["run_id"] = forged["run_id"]
        with (
            pytest.raises(psycopg.errors.RaiseException, match="Temporal"),
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


@DB
def test_native_datetime_normalization_matches_python(retained):
    import psycopg

    reader, _ = retained
    values = [
        "2026-01-01T04:00:00+04:00",
        "2026-01-01T00:00:00.000000Z",
        "2026-01-01T00:00:00.000001Z",
        "2026-01-01T00:00:00-15:59",
    ]
    with resources.resource_connection(reader) as conn:
        actual = [
            conn.execute(
                "SELECT g8_temporal_observation_value(%s,%s)", (value, "datetime")
            ).fetchone()[0]
            for value in values
        ]
    assert actual == [normalize(value, "datetime") for value in values]
    assert actual[0] == actual[1] and actual[1] < actual[2]
    for invalid in [
        "2026-01-01T00:00:00+00:99",
        "2026-01-01T00:00:00.1234567Z",
        "0001-01-01T00:00:00+01:00",
    ]:
        with pytest.raises(WorkspaceError):
            normalize(invalid, "datetime")
        with (
            pytest.raises(psycopg.errors.RaiseException),
            resources.resource_connection(reader) as conn,
        ):
            conn.execute("SELECT g8_temporal_observation_value(%s,%s)", (invalid, "datetime"))
