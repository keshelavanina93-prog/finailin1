from copy import deepcopy
from types import SimpleNamespace

import pytest

from finai_api.services.source_dimensions import validate_assignment
from finai_api.services.workspace import WorkspaceError


def test_assignment_rejects_cross_company_wrong_member_and_wrong_source_cell():
    nodes = {
        "observation": {
            "evidence_class": "SOURCE_BOUND",
            "attributes": {
                "legal_entity_id": "company-a",
                "source_row_key": "TR!3",
                "evidence_id": "source",
                "source_details": {"cells": {"Y": {"type": 1, "value": "Region A"}}},
            },
        },
        "context": {
            "attributes": {
                "legal_entity_id": "company-a",
                "dimension_id": "region",
                "source_column": "Y",
                "evidence_id": "source",
            }
        },
        "member": {"attributes": {"dimension_id": "region", "code": "Region A"}},
        "cell": {"attributes": {"coordinate": "TR!Y3", "evidence_id": "source"}},
    }
    item = SimpleNamespace(
        resource_id="assignment",
        evidence_class="SOURCE_BOUND",
        attributes={
            "observation_id": "observation",
            "company_dimension_id": "context",
            "member_id": "member",
            "source_record_id": "cell",
            "evidence_id": "source",
        },
    )
    validate_assignment(item, lambda identity, *_: nodes[identity])
    for identity, field, value in [
        ("context", "legal_entity_id", "company-b"),
        ("member", "dimension_id", "department"),
        ("member", "code", "Region B"),
        ("cell", "coordinate", "TR!Y4"),
        ("cell", "evidence_id", "another-source"),
    ]:
        changed = deepcopy(nodes)
        changed[identity]["attributes"][field] = value
        with pytest.raises(WorkspaceError, match="source cell, company and dimension"):
            validate_assignment(item, lambda identity, *_, selected=changed: selected[identity])
