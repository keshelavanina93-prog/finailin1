"""Binding review never silently truncates a source page or changes legacy wire data."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from finai_api.domain.transformation import TransformationDefinition


def test_binding_review_is_explicit_and_requires_a_complete_source_node():
    original = {
        "definition": {
            "nodes": [{"node_id": "source", "function_id": str(uuid4())}],
            "outputs": [{"output_id": "evidence", "node_id": "source"}],
        },
        "resource_budget": {
            "max_returned_rows": 100,
            "max_derived_evaluations": 100,
            "max_published_result_bytes": 1000000,
        },
    }
    legacy = TransformationDefinition.model_validate(original).model_dump(mode="json")
    assert "binding_review" not in legacy
    gate = {
        "binding_id": str(uuid4()),
        "source_node_id": "source",
        "rationale": "Review the exact retained source mapping",
    }
    configured = TransformationDefinition.model_validate({**legacy, "binding_review": gate})
    assert configured.model_dump(mode="json") == {**legacy, "binding_review": gate}
    for bad in ({**gate, "source_node_id": "missing"}, {**gate, "rationale": " " * 12}):
        with pytest.raises(ValidationError):
            TransformationDefinition.model_validate({**legacy, "binding_review": bad})
    for page in ({"offset": 1}, {"limit": 101}):
        with pytest.raises(ValidationError):
            TransformationDefinition.model_validate(
                {
                    **legacy,
                    "binding_review": gate,
                    "definition": {
                        **legacy["definition"],
                        "nodes": [{**legacy["definition"]["nodes"][0], **page}],
                    },
                }
            )
