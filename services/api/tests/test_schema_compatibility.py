from copy import deepcopy
from uuid import uuid4

import pytest

from finai_api.services.schema_compatibility import SchemaCompatibilityError, schema_compatibility


def shape() -> dict:
    return {
        "additional_fields": True,
        "fields": {
            "code": {
                "field_id": str(uuid4()),
                "semantic_id": str(uuid4()),
                "kind": "identifier",
                "required": True,
                "target_type": None,
                "deprecated": False,
            }
        },
    }


def test_field_read_policy_cannot_be_silently_weakened() -> None:
    before = shape()
    after = deepcopy(before)
    after["fields"]["code"]["read_permissions"] = ["restricted_read"]
    result = schema_compatibility("ProtectedValue", after, before)
    assert any(item["change"] == "READ_POLICY_CHANGED" for item in result["semantic_changes"])
    with pytest.raises(SchemaCompatibilityError, match="read-policy weakening"):
        schema_compatibility("ProtectedValue", before, after)
    after["fields"]["code"]["read_permissions"] = ["invented_permission"]
    with pytest.raises(SchemaCompatibilityError, match="Unsupported"):
        schema_compatibility("ProtectedValue", after)


def test_optional_addition_loosening_and_deprecation_have_stable_structured_diff() -> None:
    old = shape()
    new = deepcopy(old)
    new["fields"]["code"].update(required=False, deprecated=True)
    new["fields"]["  ქართული სახელი  "] = {
        **new["fields"]["code"],
        "field_id": str(uuid4()),
        "deprecated": False,
    }
    result = schema_compatibility("Vendor / წყარო shape", new, old)
    assert result == schema_compatibility("Vendor / წყარო shape", deepcopy(new), deepcopy(old))
    assert result["compatibility"] == "BACKWARD_COMPATIBLE"
    assert {row["change"] for row in result["semantic_changes"]} == {
        "FIELD_ADDED",
        "REQUIRED_LOOSENED",
        "DEPRECATED",
    }
    assert any(row["field_name"] == "  ქართული სახელი  " for row in result["semantic_changes"])
    assert old["fields"]["code"]["required"] is True


@pytest.mark.parametrize(
    "change",
    [
        "narrow_unknown",
        "remove_policy",
        "remove_field",
        "new_required",
        "tighten_required",
        "identity",
        "meaning",
        "kind",
        "target",
    ],
)
def test_breaking_changes_remain_blocked(change: str) -> None:
    old = shape()
    old["fields"]["code"]["required"] = False
    new = deepcopy(old)
    if change == "narrow_unknown":
        new["additional_fields"] = False
    elif change == "remove_policy":
        new.pop("additional_fields")
    elif change == "remove_field":
        new["fields"] = {"replacement": {**old["fields"]["code"], "field_id": str(uuid4())}}
    elif change == "new_required":
        new["fields"]["extra"] = {
            **old["fields"]["code"],
            "field_id": str(uuid4()),
            "required": True,
        }
    elif change == "tighten_required":
        new["fields"]["code"]["required"] = True
    elif change == "identity":
        new["fields"]["code"]["field_id"] = str(uuid4())
    elif change == "meaning":
        new["fields"]["code"]["semantic_id"] = str(uuid4())
    elif change == "kind":
        new["fields"]["code"]["kind"] = "text"
    else:
        old["fields"]["code"].update(kind="reference", target_type="LegalEntity")
        new["fields"]["code"].update(kind="reference", target_type="Party")
    with pytest.raises(SchemaCompatibilityError) as error:
        schema_compatibility("Source shape", new, old)
    assert error.value.status == 409


@pytest.mark.parametrize(
    "malformed",
    [
        "additional",
        "field_uuid",
        "semantic_uuid",
        "uuid_alias",
        "duplicate",
        "empty_name",
        "control_name",
        "long_name",
        "required",
        "kind",
    ],
)
def test_malformed_contracts_fail_as_422(malformed: str) -> None:
    new = shape()
    if malformed == "additional":
        new["additional_fields"] = "true"
    elif malformed == "field_uuid":
        new["fields"]["code"]["field_id"] = 7
    elif malformed == "semantic_uuid":
        new["fields"]["code"]["semantic_id"] = {"not": "a UUID"}
    elif malformed == "uuid_alias":
        new["fields"]["other"] = {
            **new["fields"]["code"],
            "field_id": new["fields"]["code"]["field_id"].replace("-", "").upper(),
        }
    elif malformed == "duplicate":
        new["fields"]["other"] = dict(new["fields"]["code"])
    elif malformed in ("empty_name", "control_name", "long_name"):
        field_name = {"empty_name": "  ", "control_name": "bad\nname", "long_name": "x" * 257}[
            malformed
        ]
        new["fields"] = {field_name: new["fields"]["code"]}
    elif malformed == "required":
        new["fields"]["code"]["required"] = 1
    else:
        new["fields"]["code"]["kind"] = []
    with pytest.raises(SchemaCompatibilityError) as error:
        schema_compatibility("Source shape", new)
    assert error.value.status == 422


def test_initial_and_widening_policy_are_explained() -> None:
    new = shape()
    assert schema_compatibility("Source shape", new)["compatibility"] == "INITIAL"
    old = deepcopy(new)
    old["additional_fields"] = False
    result = schema_compatibility("Source shape", new, old)
    assert result["semantic_changes"] == [
        {
            "field_id": None,
            "field_name": "additional_fields",
            "change": "ADDITIONAL_FIELDS_ENABLED",
            "before": False,
            "after": True,
        }
    ]
