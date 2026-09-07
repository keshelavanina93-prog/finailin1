"""Protect retained wire evidence when narrowing the executable API contract."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from finai_api.domain.ontology_query_wire import (
    DefinedObjectSetResponse,
    ObjectSetResponse,
)

EVIDENCE = Path(__file__).resolve().parents[3] / "docs/development/evidence"


@pytest.mark.parametrize("root", ["interface", "type-group"])
def test_retained_query_payload_keeps_original_provenance(root):
    retained = json.loads((EVIDENCE / f"nin6-{root}-query-runtime.json").read_text("utf-8"))
    payload = retained["query"]
    payload["objects"][0]["additional_provenance"] = {"coordinate": "retained-original"}
    response = ObjectSetResponse.model_validate(payload)
    assert response.model_dump(mode="json", by_alias=True, exclude_unset=True) == payload
    defined = {
        **payload,
        "definition_id": retained["prepared"]["object_set"]["resource_id"],
        "definition_version_id": retained["prepared"]["object_set"]["version_id"],
    }
    assert DefinedObjectSetResponse.model_validate(defined).definition_version_id
    del defined["definition_version_id"]
    with pytest.raises(ValidationError):
        DefinedObjectSetResponse.model_validate(defined)
    payload["objects"][0]["version_id"] = "not-an-exact-version"
    with pytest.raises(ValidationError):
        ObjectSetResponse.model_validate(payload)
