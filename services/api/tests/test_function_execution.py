# ruff: noqa: F811
"""Read-only shared Function execution on synthetic canonical observations."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from test_definition_history import DB, item, retained  # noqa: F401

from finai_api.domain.function_execution import FunctionInvocation
from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.services import function_execution as functions
from finai_api.services.workspace import WorkspaceError


def function_case(retained):
    reader, publish = retained
    company = item("LegalEntity", {})
    query = item(
        "ObjectSetDefinition",
        {"definition": {"object_type": "LegalEntity", "resource_ids": [str(company.resource_id)]}},
    )
    publish(company, query)
    executable = functions.manifest()
    spec = {
        key: executable[key]
        for key in ("implementation_id", "determinism", "code_sha256", "dependency_sha256")
    }
    function = item(
        "FunctionDefinition", {"object_set_id": str(query.resource_id), "definition": spec}
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
    return reader, request, company, query, function


@DB
def test_exact_function_executes_existing_query_without_material_authority_grant(retained):
    reader, request, company, _, _ = function_case(retained)
    plan = functions.plan(reader, request)
    first = functions.execute_plan(reader, plan)
    assert first == functions.execute_plan(reader, plan)
    assert len(first["objects"]) == 1
    assert first["objects"][0]["resource_id"] == str(company.resource_id)
    assert first["used_versions"][0]["material_state"] == "UNESTABLISHED"
    assert first["mode"] == "EVIDENCE_ANALYSIS_ONLY"
    assert first["coverage"] == "QUERY_PAGE_ONLY"
    assert first["business_effect_authorized"] is False
    assert first["current_use_authorized"] is False
    with pytest.raises(WorkspaceError, match="integrity"):
        functions.execute_plan(reader, {**plan, "object_set": {"resource_id": str(UUID(int=1))}})


def test_function_validator_refuses_uninstalled_implementation_before_dependency_binding():
    executable = functions.manifest()
    spec = {
        key: executable[key]
        for key in ("implementation_id", "determinism", "code_sha256", "dependency_sha256")
    }
    spec["code_sha256"] = "0" * 64
    mutation = item("FunctionDefinition", {"object_set_id": str(UUID(int=1)), "definition": spec})

    def target(*args):
        raise AssertionError("Invalid implementation must not bind canonical dependencies")

    with pytest.raises(WorkspaceError, match="installed executable"):
        functions.validate_function(mutation, target)


def test_manifest_refuses_disk_drift_without_advertising_unloaded_code(monkeypatch):
    startup = functions.manifest()
    changed = {**startup, "code_sha256": "0" * 64}
    monkeypatch.setattr(functions, "_disk_manifest", lambda: changed)
    with pytest.raises(WorkspaceError, match="restart the runtime") as error:
        functions.manifest()
    assert error.value.status == 503
    monkeypatch.setattr(functions, "_disk_manifest", lambda: startup)
    assert functions.manifest() == startup
