"""Unused fallback arithmetic cannot invalidate a retained scalar observation."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from finai_api.domain.ontology_definitions import Expression
from finai_api.services import ontology_definitions as definitions


def fallback_expression():
    return Expression.model_validate(
        {
            "op": "coalesce",
            "args": [
                {"op": "field", "field": "observed"},
                {
                    "op": "divide",
                    "args": [
                        {"op": "field", "field": "numerator"},
                        {"op": "field", "field": "denominator"},
                    ],
                },
            ],
        }
    )


@pytest.mark.parametrize("observed", ["17.25", "0", 0, "", False])
def test_coalesce_preserves_non_null_without_evaluating_unused_fallback(observed):
    # Evaluator null handling is independent of truthiness. Publication still
    # enforces its existing scalar kinds; this does not admit boolean schemas.
    actual = definitions.evaluate_expression(
        fallback_expression(), {"observed": observed, "numerator": "5", "denominator": "0"}
    )
    assert actual == observed
    assert type(actual) is type(observed)


@pytest.mark.parametrize(
    ("attributes", "status", "value", "reason"),
    [
        ({"observed": "17.25", "numerator": "5", "denominator": "0"}, "AVAILABLE", "17.25", None),
        ({"observed": "0", "numerator": "5", "denominator": "0"}, "AVAILABLE", "0", None),
        ({"observed": None, "numerator": "0.3", "denominator": "0.1"}, "AVAILABLE", "3", None),
        ({"numerator": "5", "denominator": "0"}, "UNAVAILABLE", None, "Division by zero"),
        ({"observed": None}, "MISSING_INPUT", None, None),
    ],
)
def test_derived_fallback_status_keeps_object_definition_and_schema_pins(
    monkeypatch, attributes, status, value, reason
):
    identity, version, schema, schema_version, obj, obj_version = [uuid4() for _ in range(6)]
    resource = {
        "resource_id": identity,
        "version_id": version,
        "object_type": "DerivedProperty",
        "attributes": {
            "definition": {
                "name": "observed_or_ratio",
                "result_kind": "decimal",
                "expression": fallback_expression().model_dump(),
            }
        },
        "dependencies": [
            {
                "relation": "FIELD:schema_id",
                "resource_id": schema,
                "version_id": schema_version,
                "identity_key": "SourceObservation",
            }
        ],
    }

    def resolve(principal, requested, pinned=None):
        assert requested == identity and pinned == version
        return resource

    monkeypatch.setattr(definitions, "definition", resolve)
    source = {
        "resource_id": str(obj),
        "version_id": str(obj_version),
        "schema_version_id": str(schema_version),
        "object_type": "SourceObservation",
        "attributes": attributes,
    }
    row = definitions.derived_values(
        SimpleNamespace(), [source], [identity], {identity: version}
    )[0]
    assert (row["status"], row["value"], row.get("reason")) == (status, value, reason)
    assert row["object_id"] == str(obj)
    assert row["object_version_id"] == str(obj_version)
    assert row["definition_id"] == identity
    assert row["definition_version_id"] == version
    assert row["epistemic_state"] == "DERIVED"

    source["schema_version_id"] = str(uuid4())
    incompatible = definitions.derived_values(
        SimpleNamespace(), [source], [identity], {identity: version}
    )[0]
    assert incompatible["status"] == "UNAVAILABLE"
    assert "schema differs" in incompatible["reason"]
