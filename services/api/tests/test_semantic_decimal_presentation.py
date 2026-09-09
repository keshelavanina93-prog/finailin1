"""Display contracts preserve retained amounts and require reviewed currency context."""

from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_semantic_entity_movements import case  # noqa: F401

from finai_api.domain.function_execution import PostedMovementsImplementation
from finai_api.domain.semantic_analysis import FieldDefinition
from finai_api.services import semantic_analysis
from finai_api.services.semantic_analysis_support import digest, pin
from finai_api.services.workspace import WorkspaceError


def declaration():
    return dict(
        implementation_id="accounting.retained-posted-movements/v1",
        determinism="DETERMINISTIC_FOR_PINNED_INPUTS",
        code_sha256="a" * 64,
        dependency_sha256="b" * 64,
        document_id="ir_" + "c" * 64,
        source_sha256="c" * 64,
        sheet="Ledger",
        max_source_rows=1000,
    )


def test_unchanged_declaration_omits_optional_fields_and_preserves_hash():
    original = declaration()
    current = PostedMovementsImplementation(**original).model_dump(mode="json")
    assert current == original
    assert digest(current) == digest(original)
    reviewed = {**original, "entity_movement_review": True}
    assert PostedMovementsImplementation(**reviewed).model_dump(mode="json") == reviewed
    for digits in (0, 2, 6):
        result = PostedMovementsImplementation(**reviewed, movement_display_fraction_digits=digits)
        assert result.model_dump()["movement_display_fraction_digits"] == digits
    with pytest.raises(ValidationError, match="requires entity movement review"):
        PostedMovementsImplementation(**original, movement_display_fraction_digits=0)
    for digits in (-1, 7, True, 2.5, "2"):
        with pytest.raises(ValidationError):
            PostedMovementsImplementation(**reviewed, movement_display_fraction_digits=digits)


def test_decimal_presentation_requires_exact_currency_context():
    currency = dict(resource_id=uuid4(), version_id=uuid4(), content_hash="d" * 64)
    base = dict(
        key="movement",
        label="Movement",
        kind="decimal",
        role="ATTRIBUTE",
        definition=currency,
        unit="GEL",
        unit_reference=currency,
    )
    old = FieldDefinition(**base).model_dump(mode="json")
    assert "presentation" not in old
    presentation = dict(format="FIXED_DECIMAL", fraction_digits=2, currency=currency)
    field = FieldDefinition(**base, presentation=presentation)
    assert field.aggregation == "NONE" and field.role == "ATTRIBUTE"
    for patch in (
        {"kind": "integer"},
        {"role": "DIMENSION"},
        {"unit": None},
        {"unit": " "},
        {"unit_reference": None},
        {"unit_reference": {**currency, "version_id": uuid4()}},
    ):
        with pytest.raises(ValidationError, match="exact currency context"):
            FieldDefinition(**{**base, **patch}, presentation=presentation)
    for patch in (
        {"format": "PERCENT"},
        {"fraction_digits": True},
        {"fraction_digits": 7},
        {"scale": 100},
        {"currency": {**currency, "content_hash": "e" * 64}},
    ):
        with pytest.raises(ValidationError):
            FieldDefinition(**base, presentation={**presentation, **patch})


@pytest.mark.usefixtures("case")
def test_only_exact_reviewed_function_opt_in_changes_movement_display(request):
    history, request = request.getfixturevalue("case")
    before = semantic_analysis.project(None, request)
    retained = deepcopy(history)
    old_descriptor = before.descriptor.model_dump(mode="json")
    assert all("presentation" not in field for field in old_descriptor["fields"])
    _, plan, resolver = semantic_analysis.load(None, request.invocation_id)
    function = resolver.version(plan["function"])
    previous_function = deepcopy(function)
    previous_plan = deepcopy(plan)
    function["attributes"]["definition"]["movement_display_fraction_digits"] = 2
    function["version_id"] = str(uuid4())
    function["content_hash"] = digest(function["attributes"])
    plan["function"] = pin(function).model_dump(mode="json")
    after = semantic_analysis.project(None, request)
    assert after.descriptor_sha256 != before.descriptor_sha256
    assert after.descriptor.function.version_id != before.descriptor.function.version_id
    assert after.descriptor.contract == "semantic-analysis/2"
    assert after.descriptor.measure is None and after.descriptor.visual == "NONE"
    code_field = next(field for field in after.descriptor.fields if field.key == "account_code")
    assert code_field.presentation is None
    for field in (field for field in after.descriptor.fields if field.kind == "decimal"):
        assert field.presentation.fraction_digits == 2
        assert field.presentation.currency == field.unit_reference
        assert field.role == "ATTRIBUTE" and field.aggregation == "NONE"
    assert [row.values for row in after.rows] == [row.values for row in before.rows]
    assert history == retained
    with pytest.raises(WorkspaceError):
        semantic_analysis.project(
            None, request.model_copy(update={"descriptor_sha256": before.descriptor_sha256})
        )
    function.clear()
    function.update(previous_function)
    plan.clear()
    plan.update(previous_plan)
    restored = semantic_analysis.project(None, request)
    assert restored.descriptor_sha256 == before.descriptor_sha256
    assert restored.descriptor.model_dump(mode="json") == old_descriptor
