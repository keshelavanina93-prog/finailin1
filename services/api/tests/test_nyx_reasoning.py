from uuid import UUID, uuid4

from finai_api.domain.authority import ExactScope
from finai_api.domain.nyx_reasoning import ReasonRequest
from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.domain.review import Principal
from finai_api.services import nyx_reasoning


def principal() -> Principal:
    return Principal(
        actor_id="analyst",
        display_name="Analyst",
        scope=ExactScope(
            tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
            legal_entity_id="company-a",
            period="2025-01",
            currency="GEL",
        ),
        permissions=("read", "ontology_read"),
    )


def test_financial_claim_is_refused_with_exact_citation(monkeypatch):
    resource_id, version_id = uuid4(), uuid4()
    selected = {
        "resource_id": str(resource_id),
        "version_id": str(version_id),
        "display_name": "January source",
        "object_type": "SourceEvidence",
        "content_hash": "a" * 64,
        "evidence_class": "SOURCE_BOUND",
        "authority_state": "APPROVED",
    }
    monkeypatch.setattr(
        nyx_reasoning.resources,
        "get_resource",
        lambda _principal, _resource: {"versions": [selected]},
    )

    result = nyx_reasoning.reason(
        principal(),
        ReasonRequest(
            question="What is the revenue forecast?",
            selected=VersionReference(resource_id=resource_id, version_id=version_id),
        ),
    )

    assert result["contract"] == "nyx-reasoning/1"
    assert result["state"] == "REFUSED"
    assert result["refusal_code"] == "AUTHORITATIVE_FINANCIAL_FACT_REQUIRED"
    assert result["citations"][0]["reference"]["version_id"] == str(version_id)


def test_missing_selection_requires_exact_scope():
    result = nyx_reasoning.reason(principal(), ReasonRequest(question="Explain this"))
    assert result["state"] == "NEEDS_EXACT_SCOPE"
    assert result["refusal_code"] == "EXACT_RESOURCE_REQUIRED"
