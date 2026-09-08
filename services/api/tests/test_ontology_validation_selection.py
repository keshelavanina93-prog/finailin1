"""Validation intent must reject ambiguous coverage before a plan can be retained."""

from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from finai_api.domain.ontology_validation import (
    ConstraintProfileDefinition,
    OntologyProfileDefinition,
    ValidationRunRequest,
)

FOCUS = "https://example.invalid/synthetic-validation/account"
SHAPE = "https://example.invalid/synthetic-validation/required-fields"
GRAPH = "https://example.invalid/synthetic-validation/retained-data"


def pin():
    return {"resource_id": str(uuid4()), "version_id": str(uuid4()), "content_hash": "a" * 64}


def constraint(selection):
    return {
        "ontology_profile": pin(),
        "shapes": {"release": pin(), "graph_iris": [GRAPH]},
        "selection": selection,
    }


@pytest.mark.parametrize(
    ("selection", "reason"),
    [
        (
            {"mode": "PROFILE_TARGETS", "focus_iris": [FOCUS]},
            "Profile target validation cannot silently narrow its coverage",
        ),
        (
            {"mode": "PROFILE_TARGETS", "shape_iris": [SHAPE]},
            "Profile target validation cannot silently narrow its coverage",
        ),
        (
            {"mode": "FILTER_TARGETS", "shape_iris": [SHAPE]},
            "Selected validation requires explicit focus nodes",
        ),
        (
            {"mode": "EXPLICIT_SHAPE_FOCUS", "shape_iris": [SHAPE]},
            "Selected validation requires explicit focus nodes",
        ),
        (
            {"mode": "EXPLICIT_SHAPE_FOCUS", "focus_iris": [FOCUS]},
            "Explicit shape/focus evaluation requires selected shapes",
        ),
    ],
)
def test_constraint_cannot_silently_switch_or_narrow_requested_coverage(selection, reason):
    submitted = constraint(selection)
    before = deepcopy(submitted)
    with pytest.raises(ValidationError) as refused:
        ConstraintProfileDefinition.model_validate(submitted)
    assert [(error["loc"], error["msg"]) for error in refused.value.errors()] == [
        (("selection",), "Value error, " + reason)
    ]
    assert submitted == before


@pytest.mark.parametrize("field", ["focus_iris", "shape_iris"])
def test_duplicate_selectors_are_refused_instead_of_deduplicated(field):
    selection = {
        "mode": "EXPLICIT_SHAPE_FOCUS",
        "focus_iris": [FOCUS],
        "shape_iris": [SHAPE],
    }
    selection[field] *= 2
    with pytest.raises(ValidationError) as refused:
        ConstraintProfileDefinition.model_validate(constraint(selection))
    assert [(error["loc"], error["msg"]) for error in refused.value.errors()] == [
        (("selection", field), "Value error, Validation selectors must be distinct")
    ]
    assert len(selection[field]) == 2


def test_run_cannot_repeat_a_graph_to_misrepresent_selected_dataset_coverage():
    submitted = {
        "request_id": str(uuid4()),
        "constraint_profile": pin(),
        "data": {"release": pin(), "graph_iris": [GRAPH, GRAPH]},
    }
    with pytest.raises(ValidationError) as refused:
        ValidationRunRequest.model_validate(submitted)
    assert [(error["loc"], error["msg"]) for error in refused.value.errors()] == [
        (("data", "graph_iris"), "Value error, Selected graphs must be distinct")
    ]


@pytest.mark.parametrize("competing_version", [False, True])
def test_profile_requires_one_unambiguous_pin_per_release(competing_version):
    first = pin()
    second = (
        {**first, "version_id": str(uuid4()), "content_hash": "b" * 64}
        if competing_version
        else first
    )
    with pytest.raises(ValidationError) as refused:
        OntologyProfileDefinition.model_validate(
            {
                "purpose": "Synthetic selected external vocabulary for explicit validation",
                "domain_pack": "synthetic.validation",
                "members": [
                    {"release": first, "graph_iris": [GRAPH]},
                    {"release": second, "graph_iris": [GRAPH + "/another"]},
                ],
            }
        )
    assert [error["msg"] for error in refused.value.errors()] == [
        "Value error, One profile cannot contain competing versions of one release"
    ]


def test_profile_cannot_pass_review_intent_requirement_using_padding():
    with pytest.raises(ValidationError) as refused:
        OntologyProfileDefinition.model_validate(
            {
                "purpose": "     vague     ",
                "domain_pack": "synthetic.validation",
                "members": [{"release": pin(), "graph_iris": [GRAPH]}],
            }
        )
    assert [(error["loc"], error["msg"]) for error in refused.value.errors()] == [
        (("purpose",), "Value error, An explicit substantive profile purpose is required")
    ]


@pytest.mark.parametrize(
    "selection",
    [
        {"mode": "PROFILE_TARGETS", "focus_iris": [], "shape_iris": []},
        {"mode": "FILTER_TARGETS", "focus_iris": [FOCUS], "shape_iris": []},
        {"mode": "EXPLICIT_SHAPE_FOCUS", "focus_iris": [FOCUS], "shape_iris": [SHAPE]},
    ],
)
def test_valid_intent_retains_exact_mode_pins_and_fail_closed_evaluation_policy(selection):
    submitted = constraint(selection)
    accepted = ConstraintProfileDefinition.model_validate(submitted).model_dump(mode="json")
    assert accepted["selection"] == selection
    assert accepted["ontology_profile"] == submitted["ontology_profile"]
    assert accepted["shapes"] == submitted["shapes"]
    assert accepted["empty_evaluation"] == "NOT_EVALUATED"
    assert accepted["unsupported_constructs"] == "REFUSE"
    assert accepted["inference"] == "NONE"
    assert accepted["business_effect_authorized"] is False
