from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest

from finai_api.config import get_settings


@pytest.fixture(autouse=True)
def configured_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    monkeypatch.setenv(
        "FINAI_ACCESS_TOKENS",
        json.dumps(
            {
                "test-token": {
                    "tenant_id": "805d8a32-d12b-4268-a236-b0b16e59da9f",
                    "legal_entity_id": "entity-ge-001",
                    "period": "2026-08",
                    "currency": "GEL",
                }
            }
        ),
    )
    get_settings.cache_clear()


@pytest.fixture
def request_payload() -> Callable[..., dict[str, Any]]:
    def factory(*, include_credit: bool = True) -> dict[str, Any]:
        observed_fields = [
            {"name": "account_code", "source_path": "sheet:TB!A:A"},
            {"name": "debit", "source_path": "sheet:TB!C:C"},
        ]
        if include_credit:
            observed_fields.append({"name": "credit", "source_path": "sheet:TB!D:D"})

        return {
            "authority_contract": {
                "contract_id": str(UUID("3ce1ec32-4532-47df-9244-1c5174ac2170")),
                "contract_version": 1,
                "source_kind": "TRIAL_BALANCE",
                "scope": {
                    "tenant_id": str(UUID("805d8a32-d12b-4268-a236-b0b16e59da9f")),
                    "legal_entity_id": "entity-ge-001",
                    "period": "2026-08",
                    "currency": "GEL",
                },
                "evidence": [
                    {
                        "evidence_id": "ev_tb_2026_08",
                        "content_sha256": "a" * 64,
                        "locator": "object://evidence/tb-2026-08.xlsx",
                    }
                ],
                "observed_fields": observed_fields,
            },
            "requested_fields": [
                {"name": "account_code"},
                {"name": "net_balance"},
                {"name": "customer_invoice_id"},
                {"name": "account_semantic_class", "inference_candidate": True},
            ],
            "derivation_rules": [
                {
                    "output_field": "net_balance",
                    "rule_id": "finance.tb.net-balance",
                    "rule_version": 1,
                    "depends_on": ["debit", "credit"],
                }
            ],
        }

    return factory
