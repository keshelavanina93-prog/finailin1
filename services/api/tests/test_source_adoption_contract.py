"""Synthetic compatibility boundaries, not authentic later-source acceptance."""

from datetime import date
from uuid import uuid4

import pytest
from pydantic import ValidationError

from finai_api.domain.source_adoption import (
    AccountingMeaning,
    PinnedResource,
    SourceAdoptionSelection,
    SourceFamilySelection,
    SourceSnapshot,
    require_compatible_adoption,
)


def pin():
    return PinnedResource(resource_id=uuid4(), version_id=uuid4(), content_hash="a" * 64)


@pytest.fixture
def baseline():
    return SourceSnapshot(
        binding=pin(), scope=pin(), evidence=pin(), company=pin(), chart=pin(),
        company_alias=pin(), period=pin(),
        period_starts_on=date(2025, 1, 1), period_ends_on=date(2025, 1, 31),
        observed_from=date(2025, 1, 1), observed_through=date(2025, 1, 31),
        source_sha256="1" * 64, schema_sha256="a" * 64,
        document_id="synthetic-first-snapshot", worksheet="Base",
        source_profile="seg_expense_base", date_basis="OBSERVED_MOVEMENT_DATE_EXTENT",
        source_rows=596, missing_amount_count=1, missing_amount_coordinates=["Base!S288"],
        meaning=AccountingMeaning(
            ledger=pin(), book=pin(), currency=pin(), functional_currency=pin(),
            account_mapping=pin(), dimension_mapping=pin(), currency_role="FUNCTIONAL",
            currency_policy="SOURCE_AMOUNT_ONLY", granularity="SOURCE_ROW",
            deepest_valid_drill="SOURCE_CELL", amount_field="source_amount",
            amount_semantics="DEBIT_CREDIT", vat_treatment="AS_POSTED",
            supplementary_amount_field="annotated_amount",
            supplementary_amount_role="NON_AUTHORITATIVE_SOURCE_OBSERVATION",
        ),
    )


def later(baseline):
    return baseline.model_copy(update={
        "binding": pin(), "scope": pin(), "evidence": pin(), "period": pin(),
        "source_sha256": "2" * 64, "document_id": "synthetic-later-snapshot",
        "period_starts_on": date(2025, 2, 1), "period_ends_on": date(2025, 2, 28),
        "observed_from": date(2025, 2, 3), "observed_through": date(2025, 2, 28),
        "missing_amount_count": 0, "missing_amount_coordinates": [],
    })


def test_later_period_reuses_company_and_meaning_without_rewriting_original(baseline):
    original = baseline.model_dump(mode="json")
    successor = later(baseline)
    require_compatible_adoption(baseline, baseline, successor, "DISJOINT_PERIOD_ADDITION")
    assert successor.company.resource_id == baseline.company.resource_id
    assert successor.meaning.account_mapping == baseline.meaning.account_mapping
    assert successor.period.resource_id != baseline.period.resource_id
    assert baseline.model_dump(mode="json") == original
    assert baseline.missing_amount_coordinates == ["Base!S288"]


def test_replacement_cannot_cycle_back_to_original_snapshot(baseline):
    revised = baseline.model_copy(update={
        "binding": pin(), "scope": pin(), "evidence": pin(), "source_sha256": "3" * 64,
    })
    with pytest.raises(ValueError, match="original family snapshot"):
        require_compatible_adoption(
            baseline, revised, baseline, "REPLACES_PREDECESSOR_SNAPSHOT"
        )


@pytest.mark.parametrize("field,value", [
    ("schema_sha256", "b" * 64), ("source_profile", "1c_journal"),
    ("worksheet", "Different source roles"), ("date_basis", "EXPLICIT_REPORT_PERIOD"),
    ("company", None), ("chart", None),
])
def test_same_layout_or_filename_cannot_override_identity_or_schema(baseline, field, value):
    candidate = later(baseline).model_copy(update={field: pin() if value is None else value})
    with pytest.raises(ValueError, match=r"canonical company|schema"):
        require_compatible_adoption(baseline, baseline, candidate, "DISJOINT_PERIOD_ADDITION")


@pytest.mark.parametrize("field,value", [
    ("amount_field", "annotated_amount"), ("amount_semantics", "SIGNED_MOVEMENT"),
    ("vat_treatment", None), ("currency_role", "TRANSACTION"),
    ("account_mapping", None), ("dimension_mapping", None), ("currency", None),
    ("book", None), ("ledger", None),
])
def test_changed_meaning_or_mapping_requires_new_reviewed_family(baseline, field, value):
    meaning = baseline.meaning.model_copy(update={
        field: pin() if value is None and field not in {"vat_treatment"} else value
    })
    with pytest.raises(ValueError, match="accounting meaning"):
        require_compatible_adoption(
            baseline, baseline, later(baseline).model_copy(update={"meaning": meaning}),
            "DISJOINT_PERIOD_ADDITION",
        )


def test_overlapping_snapshot_requires_explicit_replacement_and_preserves_original(baseline):
    replacement = baseline.model_copy(update={
        "binding": pin(), "scope": pin(), "evidence": pin(), "source_sha256": "3" * 64,
        "document_id": "synthetic-corrected-snapshot",
    })
    with pytest.raises(ValueError, match="disjoint"):
        require_compatible_adoption(baseline, baseline, replacement, "DISJOINT_PERIOD_ADDITION")
    require_compatible_adoption(baseline, baseline, replacement, "REPLACES_PREDECESSOR_SNAPSHOT")
    with pytest.raises(ValueError, match="exact same reviewed period"):
        require_compatible_adoption(
            baseline, baseline, later(baseline), "REPLACES_PREDECESSOR_SNAPSHOT"
        )
    with pytest.raises(ValueError, match="distinct immutable"):
        require_compatible_adoption(baseline, baseline, baseline, "REPLACES_PREDECESSOR_SNAPSHOT")


def test_dates_and_missing_amount_counts_are_not_claims_of_completeness(baseline):
    value = baseline.model_dump(mode="python")
    with pytest.raises(ValidationError, match="own reviewed period"):
        SourceSnapshot.model_validate({**value, "observed_through": date(2025, 2, 1)})
    with pytest.raises(ValidationError, match="missing-amount count"):
        SourceSnapshot.model_validate({**value, "missing_amount_count": 0})
    with pytest.raises(ValidationError):
        SourceSnapshot.model_validate({**value, "coverage_state": "COMPLETE_LEDGER"})


def test_requests_take_exact_references_not_client_asserted_compatibility(baseline):
    reference = baseline.binding.model_dump(exclude={"content_hash"})
    family = dict(family_key="statutory-postings", source_system="1C", display_name="Source family",
                  baseline_binding=reference, rationale="Reviewed source register and book")
    SourceFamilySelection.model_validate(family)
    with pytest.raises(ValidationError):
        SourceFamilySelection.model_validate({**family, "rationale": " " * 20})
    with pytest.raises(ValidationError):
        SourceFamilySelection.model_validate({**family, "schema_sha256": "a" * 64})
    with pytest.raises(ValidationError):
        SourceAdoptionSelection.model_validate({
            "family": reference, "predecessor_binding": reference, "successor_binding": reference,
            "rationale": "Same filename is not compatibility", "compatible": True,
        })
