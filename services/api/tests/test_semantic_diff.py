"""Review displays cannot hide authority/time changes or confuse absence with null."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

from finai_api.domain.resources import ResourceMutation
from finai_api.services.semantic_diff import semantic_diff


def test_review_diff_preserves_meaning_types_and_effective_time() -> None:
    item = ResourceMutation(
        object_type="SemanticContract",
        identity_key="example",
        display_name="Meaning",
        attributes={"kind": "identifier", "optional": None, "ordered": [True, 2]},
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
    )
    base = {**item.model_dump(), "version_id": uuid4(), "access_entity": "__PLATFORM__"}
    change = item.model_copy(
        update={
            "display_name": "Revised meaning",
            "authority_state": "REVOKED",
            "valid_to": datetime(2026, 9, 1, tzinfo=UTC),
            "attributes": {"kind": "identifier", "added": None, "ordered": [1, 2], "a/b~c": 0},
        }
    )
    diff = semantic_diff(base, change, "__PLATFORM__")
    rows = {row["path"]: row for row in diff["changes"]}
    assert diff["base_version_id"] == str(base["version_id"])
    assert rows["/attributes/optional"]["operation"] == "REMOVE"
    assert rows["/attributes/optional"]["before"] == {"present": True, "value": None}
    assert rows["/attributes/optional"]["after"] == {"present": False}
    assert rows["/attributes/added"]["operation"] == "ADD"
    assert rows["/attributes/added"]["after"] == {"present": True, "value": None}
    assert rows["/attributes/ordered"]["before"]["value"] == [True, 2]
    assert rows["/attributes/ordered"]["after"]["value"] == [1, 2]
    assert "/attributes/a~1b~0c" in rows
    assert rows["/authority_state"]["category"] == "AUTHORITY_AND_EVIDENCE"
    assert rows["/valid_to"]["category"] == "EFFECTIVE_TIME"
    same_instant = item.model_copy(
        update={
            "valid_from": datetime(2026, 1, 1, 4, tzinfo=timezone(timedelta(hours=4))),
        }
    )
    assert semantic_diff(base, same_instant, "__PLATFORM__")["changes"] == []


def test_nested_semantics_and_new_resources_have_explicit_baselines() -> None:
    item = ResourceMutation(
        object_type="SchemaDefinition",
        identity_key="Example",
        display_name="Example schema",
        attributes={"fields": {"code": {"required": False}}},
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
    )
    created = semantic_diff(None, item, "__PLATFORM__")
    assert created["base_version_id"] is None
    assert all(row["operation"] == "ADD" for row in created["changes"])
    base = {**item.model_dump(), "version_id": uuid4(), "access_entity": "__PLATFORM__"}
    updated = item.model_copy(update={"attributes": {"fields": {"code": {"required": True}}}})
    changes = semantic_diff(base, updated, "__PLATFORM__")["changes"]
    assert len(changes) == 1
    assert changes[0]["path"] == "/attributes/fields/code/required"
    assert changes[0]["category"] == "SEMANTIC_CONTRACT"
