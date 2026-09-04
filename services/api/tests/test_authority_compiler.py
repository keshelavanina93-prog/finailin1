from collections.abc import Callable
from typing import Any

from finai_api.domain.authority import CompileHydrationRequest, EpistemicState
from finai_api.services.authority_compiler import AuthorityCompiler


def test_compiler_separates_evidence_states(
    request_payload: Callable[..., dict[str, Any]],
) -> None:
    request = CompileHydrationRequest.model_validate(request_payload())

    receipt = AuthorityCompiler().compile(request)
    by_field = {item.field: item for item in receipt.fields}

    assert by_field["account_code"].state is EpistemicState.OBSERVED
    assert by_field["account_code"].authoritative is True
    assert by_field["net_balance"].state is EpistemicState.DERIVED
    assert by_field["net_balance"].rule_id == "finance.tb.net-balance"
    assert by_field["customer_invoice_id"].state is EpistemicState.UNAVAILABLE
    assert by_field["account_semantic_class"].state is EpistemicState.INFERRED
    assert by_field["account_semantic_class"].authoritative is False
    assert receipt.promotion_state == "CANDIDATE_ONLY"


def test_derivation_fails_closed_when_dependency_is_missing(
    request_payload: Callable[..., dict[str, Any]],
) -> None:
    request = CompileHydrationRequest.model_validate(request_payload(include_credit=False))

    receipt = AuthorityCompiler().compile(request)
    net_balance = next(item for item in receipt.fields if item.field == "net_balance")

    assert net_balance.state is EpistemicState.UNAVAILABLE
    assert net_balance.authoritative is False
    assert "credit" in net_balance.rationale


def test_receipt_is_deterministic(request_payload: Callable[..., dict[str, Any]]) -> None:
    request = CompileHydrationRequest.model_validate(request_payload())
    compiler = AuthorityCompiler()

    first = compiler.compile(request)
    second = compiler.compile(request)

    assert first == second
    assert first.receipt_id.startswith("cr_")
