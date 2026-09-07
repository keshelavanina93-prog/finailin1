"""Build navigation uses retained identities and cannot enter source control handlers."""

import asyncio
import json
import os
from uuid import uuid4

import pytest

from finai_api.api import workflow_routes as routes
from finai_api.domain.authority import ExactScope
from finai_api.domain.review import Principal
from finai_api.services.operator_workbench import listing, summarize
from finai_api.services.workspace import WorkspaceError

_RETAINED_GRANTS = json.loads(os.environ.get("FINAI_ACCESS_TOKENS", "{}"))


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
def test_native_retained_build_listing_exact_title_and_permission_filter():
    grant = next(
        g
        for g in _RETAINED_GRANTS.values()
        if {"read", "ontology_read", "ingest"}.issubset(g["permissions"])
    )
    user = Principal.model_validate(grant)
    page = listing(user, None, True)
    builds = [row for row in page["items"] if row["family"] == "build"]
    assert builds, "This native acceptance requires retained transformation runs"
    assert all(row["title"] != "Retained transformation build" for row in builds)
    assert all(row["transformation"]["version_id"] and row["request_id"] for row in builds)
    restricted = user.model_copy(update={"permissions": ("read",)})
    assert not any(
        row["family"] in ("build", "ontology") for row in listing(restricted, None, True)["items"]
    )
