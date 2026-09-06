"""Arithmetic failure is local to a value; decimal output has bounded allocation."""

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from finai_api.domain.ontology_definitions import Expression
from finai_api.services import ontology_definitions as definitions


@pytest.mark.parametrize("text", ["1e4095", "-1e4094", "1e-4094", "-1e-4093", "0e999999"])
def test_fixed_decimal_boundary_preserves_exact_format(text):
    value = Decimal(text)
    assert definitions._bounded_decimal_text(value) == format(value, "f")


@pytest.mark.parametrize("text", ["1e4096", "-1e4095", "1e-4095", "-1e-4094", "0e-999999"])
def test_fixed_decimal_expansion_refused_before_formatting(text):
    with pytest.raises(ValueError, match="exceeds 4096 characters"):
        definitions._bounded_decimal_text(Decimal(text))


def test_decimal_range_failures_are_per_value_with_exact_pins(monkeypatch):
    identity, version, schema_version = uuid4(), uuid4(), uuid4()
    expression = {
        "op": "multiply",
        "args": [
            {"op": "field", "field": "amount"},
            {"op": "literal", "value": "1"},
        ],
    }
    definition = {
        "resource_id": identity,
        "version_id": version,
        "object_type": "DerivedProperty",
        "attributes": {
            "definition": {
                "name": "observed_amount",
                "result_kind": "decimal",
                "expression": expression,
            }
        },
        "dependencies": [
            {
                "relation": "FIELD:schema_id",
                "version_id": schema_version,
                "identity_key": "SourceObservation",
            }
        ],
    }

    def resolve(_principal, requested, pinned):
        assert (requested, pinned) == (identity, version)
        return definition

    monkeypatch.setattr(definitions, "definition", resolve)
    objects = [
        {
            "resource_id": str(uuid4()),
            "version_id": str(uuid4()),
            "schema_version_id": str(schema_version),
            "object_type": "SourceObservation",
            "attributes": {"amount": amount},
        }
        for amount in ("1e1000000", "1e999999", "1e-999999", "0", "17.25")
    ]
    rows = definitions.derived_values(SimpleNamespace(), objects, [identity], {identity: version})
    assert [row["status"] for row in rows] == [
        "UNAVAILABLE",
        "UNAVAILABLE",
        "UNAVAILABLE",
        "AVAILABLE",
        "AVAILABLE",
    ]
    assert rows[0]["reason"] == "Decimal arithmetic range failure: Overflow"
    assert "4096" in rows[1]["reason"] and "4096" in rows[2]["reason"]
    assert [row["value"] for row in rows[3:]] == ["0", "17.25"]
    for row, source in zip(rows, objects, strict=True):
        assert row["object_version_id"] == source["version_id"]
        assert row["definition_version_id"] == version


def test_coalesce_does_not_evaluate_unused_overflowing_fallback():
    expression = Expression.model_validate(
        {
            "op": "coalesce",
            "args": [
                {"op": "field", "field": "observed"},
                {
                    "op": "multiply",
                    "args": [
                        {"op": "literal", "value": "1e1000000"},
                        {"op": "literal", "value": "1"},
                    ],
                },
            ],
        }
    )
    assert definitions.evaluate_expression(expression, {"observed": "0"}) == "0"
