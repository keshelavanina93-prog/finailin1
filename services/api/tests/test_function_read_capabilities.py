# ruff: noqa: F811
"""Shared Function evidence separates reading from maker execution capabilities."""

from uuid import uuid4

import pytest
from test_definition_history import DB, retained  # noqa: F401
from test_function_execution import function_case

from finai_api.services import fact_runs, function_invocations
from finai_api.services.workspace import WorkspaceError


@DB
def test_reviewer_reads_new_function_receipt_without_maker_operational_grants(retained):
    reader, request, _, _, _ = function_case(retained)
    maker = reader.model_copy(update={"permissions": ("read", "ontology_read", "ingest")})
    checker = reader.model_copy(
        update={
            "actor_id": "synthetic-function-checker",
            "permissions": ("read", "ontology_read", "review"),
        }
    )
    result = function_invocations.invoke(maker, request)
    assert result["status"] == "SUCCEEDED"
    assert result["output"]["read_permissions"] == ["ontology_read", "read"]
    assert result["output"]["read_permission_contract"] == "SHARED_FUNCTION_READ_CAPABILITIES_V1"
    assert function_invocations.history(checker, request.request_id) == result
    stranger = checker.model_copy(
        update={
            "scope": checker.scope.model_copy(
                update={"legal_entity_id": "synthetic-function-other-" + uuid4().hex}
            )
        }
    )
    with pytest.raises(WorkspaceError) as hidden:
        function_invocations.history(stranger, request.request_id)
    assert hidden.value.status == 404
    restricted = maker.model_copy(update={"permissions": (*maker.permissions, "restricted_read")})
    restricted_result = function_invocations.invoke(
        restricted, request.model_copy(update={"request_id": uuid4()})
    )
    assert "restricted_read" in restricted_result["output"]["read_permissions"]
    with pytest.raises(WorkspaceError) as restricted_hidden:
        fact_runs.read_run(checker, restricted_result["output"]["run_id"])
    assert restricted_hidden.value.status == 404
    # Other runtimes retain their historical all-origin-permissions contract.
    legacy = fact_runs.retain_run(maker, {"fixture": "SYNTHETIC permission retention"})
    assert "ingest" in legacy["read_permissions"]
    assert "read_permission_contract" not in legacy
    with pytest.raises(WorkspaceError):
        fact_runs.read_run(checker, legacy["run_id"])
