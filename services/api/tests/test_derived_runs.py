from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from finai_api.domain.object_sets import ObjectSetQuery, ObjectSetResult
from finai_api.services import ontology_definitions as definitions
from finai_api.services.workspace import WorkspaceError


def test_query_pins_definition_before_source_read_and_preserves_missing(monkeypatch):
    identity, version, schema, schema_version, obj, obj_version = [uuid4() for _ in range(6)]
    old = {
        "resource_id": identity,
        "version_id": version,
        "object_type": "DerivedProperty",
        "attributes": {
            "definition": {
                "name": "net",
                "result_kind": "decimal",
                "expression": {
                    "op": "subtract",
                    "args": [{"op": "field", "field": "revenue"}, {"op": "field", "field": "cost"}],
                },
            }
        },
        "dependencies": [
            {
                "relation": "FIELD:schema_id",
                "resource_id": schema,
                "version_id": schema_version,
                "identity_key": "Balance",
            }
        ],
    }
    calls = []

    def resolve(principal, requested, pinned=None):
        calls.append(pinned)
        assert requested == identity
        if len(calls) > 1:
            assert pinned == version  # Never resolve a later definition after reading inputs.
        return old

    monkeypatch.setattr(definitions, "definition", resolve)
    query = ObjectSetQuery(object_type="Balance")
    objects = [
        {
            "resource_id": str(obj),
            "version_id": str(obj_version),
            "schema_version_id": str(schema_version),
            "object_type": "Balance",
            "attributes": {"revenue": "12.50"},
        }
    ]
    monkeypatch.setattr(
        definitions,
        "query_objects",
        lambda *_: ObjectSetResult(
            query=query, total=1, counts_by_type={"Balance": 1}, objects=objects, next_offset=None
        ),
    )
    result = definitions.derive_query(SimpleNamespace(), query, [identity], {})
    assert result["coverage"] == "QUERY_PAGE_ONLY"
    assert result["derived_values"][0]["status"] == "MISSING_INPUT"
    assert result["derived_values"][0]["value"] is None
    assert result["definition_versions"][0]["version_id"] == version
    with pytest.raises(WorkspaceError, match="every selected property"):
        definitions.derive_query(SimpleNamespace(), query, [identity], {uuid4(): version})
    with pytest.raises(WorkspaceError, match="explicit definition versions"):
        definitions.derive_query(
            SimpleNamespace(),
            query.model_copy(update={"known_at": datetime.now(UTC)}),
            [identity],
            {},
        )
