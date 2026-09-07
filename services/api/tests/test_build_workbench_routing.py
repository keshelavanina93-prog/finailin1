# ruff: noqa: F811
"""Build navigation uses retained identities and cannot enter source control handlers."""

import asyncio
import os
from uuid import uuid4

import pytest
from test_definition_history import item, retained  # noqa: F401
from test_function_execution import function_case

from finai_api.api import workflow_routes as routes
from finai_api.domain.authority import ExactScope
from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.domain.review import Principal
from finai_api.domain.transformation import TransformationRunRequest
from finai_api.services import transformation_runs
from finai_api.services.operator_workbench import listing, summarize
from finai_api.services.workspace import WorkspaceError


def principal():
    return Principal(
        actor_id="routing-fixture",
        display_name="Routing fixture",
        scope=ExactScope(
            tenant_id=uuid4(), legal_entity_id="fixture", period="2026-09", currency="GEL"
        ),
        permissions=("read", "ingest", "review"),
    )


def test_build_uses_retained_request_and_pin_without_company_inference():
    request_id = str(uuid4())
    pin = {"resource_id": str(uuid4()), "version_id": str(uuid4()), "content_hash": "a" * 64}
    payload = {
        "definition": {"version": "transformation-functions/1"},
        "compiled_plan": {
            "request": {"request_id": request_id},
            "transformation": pin,
            "exact_scope": {"legal_entity_id": "not-canonical-company"},
        },
        "report": {"company_label": "Not a binding"},
    }
    result = summarize("unrelated-prefix", payload, "now", "Exact retained title")
    assert result["family"] == "build" and result["request_id"] == request_id
    assert result["transformation"] == pin and result["title"] == "Exact retained title"
    assert result["company_id"] is None and result["company_binding"] == "UNBOUND"
    assert summarize("transformation:fake", {}, "now")["family"] == "unsupported"


@pytest.mark.parametrize(
    "version",
    ["transformation-functions/1", "ontology-action/1", "regulatory-source-monitor/1", "unknown/1"],
)
def test_foreign_family_rejected_before_runtime_event_or_signal(monkeypatch, version):
    monkeypatch.setattr(routes.records, "read", lambda *_: {"definition": {"version": version}})
    monkeypatch.setattr(routes.records, "event", lambda *_: pytest.fail("Unexpected event"))

    async def unavailable():
        pytest.fail("Unexpected runtime access")

    monkeypatch.setattr(routes, "client", unavailable)
    request = routes.Control(
        command="pause", reason="Explicit fixture reason", idempotency_key=uuid4()
    )
    with pytest.raises(WorkspaceError, match="only accepts report-source"):
        asyncio.run(routes.control("fixture", request, principal()))
    with pytest.raises(WorkspaceError, match="only accepts report-source"):
        asyncio.run(routes.read("fixture", principal()))


def test_source_reviewer_separation_still_precedes_runtime(monkeypatch):
    user = principal()
    monkeypatch.setattr(
        routes.records,
        "read",
        lambda *_: {
            "definition": {"version": "report-source-process/3"},
            "actor_id": user.actor_id,
        },
    )
    request = routes.Control(
        command="complete", reason="Explicit fixture reason", idempotency_key=uuid4()
    )
    with pytest.raises(WorkspaceError, match="different reviewer"):
        asyncio.run(routes.control("fixture", request, user))


@pytest.mark.parametrize(
    "version", ["report-source-process/1", "report-source-process/2", "report-source-process/3"]
)
def test_retained_source_versions_remain_supported(version):
    routes.require_source_family({"definition": {"version": version}})


@pytest.mark.skipif(os.environ.get("G8_BINDING_DB_TEST") != "1", reason="Native retained read")
def test_native_retained_build_listing_exact_title_and_permission_filter(retained):
    user, invocation, _, _, _ = function_case(retained)
    user = user.model_copy(update={"permissions": (*user.permissions, "read", "ingest")})
    _, publish = retained
    transformation = item(
        "TransformationDefinition",
        {
            "resource_budget": {
                "max_returned_rows": 50, "max_derived_evaluations": 400,
                "max_published_result_bytes": 16000000,
            },
            "definition": {
                "nodes": [{
                    "node_id": "observe", "function_id": str(invocation.function.resource_id),
                }],
                "outputs": [{"output_id": "observations", "node_id": "observe"}],
            },
        },
    )
    version = publish(transformation)[0]
    request = TransformationRunRequest(
        transformation=VersionReference(
            resource_id=version["resource_id"], version_id=version["version_id"],
        ),
        valid_at=invocation.valid_at, known_at=invocation.known_at,
    )
    workflow_id = transformation_runs.retain(user, request)
    page = listing(user, None, True)
    builds = [row for row in page["items"] if row["family"] == "build"]
    assert [row["workflow_id"] for row in builds] == [workflow_id]
    assert all(row["title"] != "Retained transformation build" for row in builds)
    assert all(row["transformation"]["version_id"] and row["request_id"] for row in builds)
    restricted = user.model_copy(update={"permissions": ("read",)})
    assert not any(
        row["family"] in ("build", "ontology") for row in listing(restricted, None, True)["items"]
    )
