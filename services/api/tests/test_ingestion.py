from uuid import uuid4

import pytest

from finai_api.domain.authority import ExactScope
from finai_api.domain.ingest import IngestRequest
from finai_api.services.ingestion import SourceAuthorityDenied, compile_source


def source(csv_text: str, objects: tuple[str, ...] = ()) -> IngestRequest:
    return IngestRequest(
        scope=ExactScope(tenant_id=uuid4(), legal_entity_id="a", period="2026-08", currency="GEL"),
        filename="source.csv",
        csv_text=csv_text,
        requested_objects=objects,
    )


def test_deterministic_tb_keeps_identifiers_and_decimal_precision() -> None:
    request = source("account_code,debit,credit,notes\n001,0.1,0,asset\n002,0,0.1,capital\n")
    receipt = compile_source(request)
    assert receipt == compile_source(request)
    assert receipt.candidates[0].values["account_code"] == "001"
    assert receipt.candidates[1].values["net_balance"] == "0.1"
    assert receipt.reconciliation["status"] == "PASS"
    assert receipt.unused_fields == ("notes",)
    assert all(item.authority_state == "MAPPED_CANDIDATE" for item in receipt.candidates)


def test_unfamiliar_source_preserves_observations_without_inventing_semantics() -> None:
    receipt = compile_source(source("x_1,ქართული\n0007,სახელი\n"))
    assert receipt.source_class == "UNFAMILIAR_TABULAR"
    assert receipt.candidates[0].object_type == "SourceRecord"
    assert receipt.candidates[0].values["x_1"] == "0007"
    assert receipt.functions_executed == ()


def test_analytical_rows_preserve_grain_and_reject_duplicates() -> None:
    request = source("account_code,debit,credit,dimension:DEPT\n001,1,0,01\n001,0,1,02\n")
    receipt = compile_source(request)
    balances = [c for c in receipt.candidates if c.object_type == "PeriodBalance"]
    assert [c.values["dimension:DEPT"] for c in balances] == ["01", "02"]
    assert [c.source_row for c in balances] == [2, 3]
    assert not receipt.rejects and receipt.reconciliation["status"] == "PASS"
    duplicate = compile_source(
        request.model_copy(update={"csv_text": request.csv_text + "001,1,0,01\n"})
    )
    assert "duplicate account/dimension grain" in duplicate.rejects[0]


def test_bom_is_retained_in_source_hash_but_not_column_binding() -> None:
    from hashlib import sha256

    request = source("\ufeffaccount_code,debit,credit\r\n001,1,1\r\n")
    receipt = compile_source(request)
    assert receipt.source_class == "TRIAL_BALANCE"
    assert receipt.source_sha256 == sha256(request.csv_text.encode()).hexdigest()


@pytest.mark.parametrize("object_type", ["Invoice", "JournalDocument", "InventoryMovement"])
def test_tb_cannot_create_unsupported_objects(object_type: str) -> None:
    with pytest.raises(SourceAuthorityDenied):
        compile_source(source("account_code,debit,credit\n001,1,0\n", (object_type,)))


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-1", "1e100", "0.0000001", "abc"])
def test_bad_amounts_are_rejected(amount: str) -> None:
    receipt = compile_source(source(f"account_code,debit,credit\n001,{amount},0\n"))
    assert not receipt.candidates
    assert receipt.rejects
    assert receipt.reconciliation["status"] == "REVIEW_REQUIRED"


@pytest.mark.parametrize("csv_text", ["", "a,a\n1,2", ",b\n1,2"])
def test_invalid_headers_fail(csv_text: str) -> None:
    with pytest.raises(ValueError):
        compile_source(source(csv_text))


def test_ragged_rows_duplicates_and_imbalance_require_review() -> None:
    receipt = compile_source(source("account_code,debit,credit\n001,1,0\n001,0,1\n002,1\n"))
    assert len(receipt.rejects) == 2
    assert receipt.reconciliation["status"] == "REVIEW_REQUIRED"


def test_unknown_columns_and_empty_data_fail_closed() -> None:
    assert compile_source(source("x,y\n1,2,3\n")).rejects
    assert not compile_source(source("x,y\n")).candidates
    with pytest.raises(ValueError):
        compile_source(source(",".join(f"c{i}" for i in range(129)) + "\n"))
    with pytest.raises(ValueError):
        compile_source(source("x\n" + "1\n" * 10001))
