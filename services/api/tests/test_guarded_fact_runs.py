"""Real lifecycle/persistence/API acceptance; aggregation alone is a mocked synthetic result."""

import json
import os
from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from finai_api.config import get_settings
from finai_api.domain.authority import ExactScope
from finai_api.domain.object_sets import ObjectSetQuery, ObjectSetResult
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resource_lifecycle import LifecycleRequest, LifecycleReview, VersionReference
from finai_api.domain.resources import ResourceMutation, ResourceProposal, ResourceReview
from finai_api.domain.review import Principal
from finai_api.main import app
from finai_api.services import fact_runs, resources
from finai_api.services import resource_lifecycle as lifecycle
from finai_api.services.workspace import WorkspaceError


def test_actual_arithmetic_returns_the_contracts_exact_schema_and_fact_pins(monkeypatch):
    from finai_api.services import fact_aggregation as aggregation

    contract_id, contract_version, schema_id, pinned_schema = [uuid4() for _ in range(4)]
    query = ObjectSetQuery(object_type="SyntheticAmount")
    definition = {
        "resource_id": contract_id,
        "version_id": contract_version,
        "object_type": "FactContract",
        "attributes": {
            "definition": {
                "grain": ["period", "unit"],
                "measure": "amount",
                "aggregation": "flow_sum",
                "time_field": "period",
                "unit_field": "unit",
                "source_family": "SYNTHETIC",
                "source_family_field": "family",
                "authority_basis": "Synthetic unit arithmetic only",
            }
        },
        "dependencies": [
            {
                "relation": "FIELD:schema_id",
                "resource_id": schema_id,
                "version_id": pinned_schema,
                "identity_key": "SyntheticAmount",
            }
        ],
    }
    rows = [
        {
            "resource_id": str(uuid4()),
            "version_id": str(uuid4()),
            "object_type": "SyntheticAmount",
            "schema_version_id": str(pinned_schema),
            "evidence_class": "SOURCE_BOUND",
            "attributes": {
                "period": period,
                "unit": "GEL",
                "family": "SYNTHETIC",
                "amount": amount,
            },
        }
        for period, amount in (("2026-08-01", "0.1"), ("2026-08-02", "0.2"))
    ]
    # Reader stubs are explicitly synthetic; the Decimal calculation is the real implementation.
    lookups = []

    def read_definition(_principal, identity):
        lookups.append(identity)
        assert identity == contract_id  # No lookup of an unpinned latest schema is permitted.
        return definition

    monkeypatch.setattr(aggregation, "definition", read_definition)
    monkeypatch.setattr(
        aggregation,
        "query_objects",
        lambda *_: ObjectSetResult(
            query=query,
            total=2,
            counts_by_type={"SyntheticAmount": 2},
            objects=rows,
            next_offset=None,
        ),
    )
    result = aggregation.aggregate_facts(None, contract_id, query, [], None)
    assert lookups == [contract_id]
    assert result["contract_version_id"] == contract_version
    assert result["schema_id"] == schema_id
    assert result["schema_version_id"] == pinned_schema
    assert result["groups"] == [
        {
            "dimensions": {"unit": "GEL"},
            "value": "0.3",
            "inputs": [
                {"resource_id": row["resource_id"], "version_id": row["version_id"]} for row in rows
            ],
        }
    ]
    assert result["financial_certification"] is None
    rows[0]["schema_version_id"] = str(uuid4())
    with pytest.raises(WorkspaceError, match="pinned version"):
        aggregation.aggregate_facts(None, contract_id, query, [], None)


@pytest.mark.skipif(os.environ.get("G8_BINDING_DB_TEST") != "1", reason="Local PostgreSQL opt-in")
def test_guarded_aggregate_requires_all_consumer_pins_and_retains_proof_after_withdrawal(
    monkeypatch,
):
    from finai_api.services import guarded_fact_runs as guarded

    tenant = UUID("805d8a32-d12b-4268-a236-b0b16e59da9f")
    operator = Principal(
        actor_id="synthetic-guarded-fact-operator",
        display_name="Synthetic guarded fact operator",
        scope=ExactScope(
            tenant_id=tenant,
            legal_entity_id="synthetic-guarded-facts-" + uuid4().hex,
            period="2026-08",
            currency="GEL",
        ),
        permissions=("ontology_admin", "ontology_read", "ontology_propose", "ontology_review"),
    )
    reviewer = operator.model_copy(update={"actor_id": "synthetic-guarded-fact-reviewer"})

    def item(kind, attributes, key=None, platform=False):
        return ResourceMutation(
            object_type=kind,
            identity_key=key or "synthetic:" + uuid4().hex,
            display_name="SYNTHETIC guarded fact fixture",
            attributes=attributes,
            access_entity="__PLATFORM__" if platform else operator.scope.legal_entity_id,
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            evidence_class="REFERENCE_TEMPLATE",
        )

    def field(kind, semantic, target=None):
        return {
            "field_id": str(uuid4()),
            "semantic_id": str(canonical_id(tenant, "SemanticContract", semantic)),
            "kind": kind,
            "required": True,
            "target_type": target,
        }

    fact_kind = "GuardedFact" + uuid4().hex[:12]
    schema = item(
        "SchemaDefinition",
        {
            "additional_fields": False,
            "fields": {
                "period": field("date", "Date"),
                "unit": field("identifier", "Identifier"),
                "family": field("identifier", "Identifier"),
                "amount": field("decimal", "Amount"),
            },
        },
        fact_kind,
        True,
    )
    fact = item(
        fact_kind, {"period": "2026-08-01", "unit": "GEL", "family": "SYNTHETIC", "amount": "10"}
    )
    contract = item(
        "FactContract",
        {
            "schema_id": str(schema.resource_id),
            "definition": {
                "grain": ["period", "unit"],
                "measure": "amount",
                "aggregation": "flow_sum",
                "time_field": "period",
                "unit_field": "unit",
                "source_family": "SYNTHETIC",
                "source_family_field": "family",
                "authority_basis": "Synthetic mocked arithmetic acceptance only",
            },
        },
    )
    consumer_kind = "GuardedConsumer" + uuid4().hex[:12]
    consumer_schema = item(
        "SchemaDefinition",
        {
            "additional_fields": False,
            "fields": {
                "minimum_authority_state": field("identifier", "Identifier"),
                "contract_id": field("reference", "CanonicalReference", "FactContract"),
                "schema_id": field("reference", "CanonicalReference", "SchemaDefinition"),
                "fact_id": field("reference", "CanonicalReference", fact_kind),
            },
        },
        consumer_kind,
        True,
    )
    consumer = item(
        consumer_kind,
        {
            "minimum_authority_state": "PARSED",
            "contract_id": str(contract.resource_id),
            "schema_id": str(schema.resource_id),
            "fact_id": str(fact.resource_id),
        },
    )
    proposal = ResourceProposal(
        title="SYNTHETIC guarded calculation consumer",
        rationale="Publish synthetic pins to test lifecycle and retained calculation evidence",
        access_entity="__TENANT__",
        mutations=[schema, fact, contract, consumer_schema, consumer],
    )
    resources.propose(operator, proposal)
    resources.review(
        reviewer,
        proposal.proposal_id,
        ResourceReview(
            decision="APPROVED",
            rationale="Independent synthetic guarded calculation fixture acceptance",
        ),
    )

    def ref(resource):
        row = resources.get_resource(operator, resource.resource_id)["resource"]
        return VersionReference(resource_id=resource.resource_id, version_id=row["version_id"])

    consumer_ref, contract_ref, schema_ref, fact_ref = map(ref, (consumer, contract, schema, fact))
    with (
        resources.resource_connection(operator) as conn,
        conn.cursor(row_factory=dict_row) as cursor,
    ):
        pins = cursor.execute(
            "SELECT target_resource_id,target_version_id FROM resource_dependencies "
            "WHERE tenant_id=%s AND version_id=%s",
            (tenant, consumer_ref.version_id),
        ).fetchall()
    refs = [
        VersionReference(resource_id=pin["target_resource_id"], version_id=pin["target_version_id"])
        for pin in pins
    ]
    assert len(refs) == 4  # Includes the consumer schema, beyond the three computation inputs.
    refs.sort(key=lambda subject: subject.resource_id == consumer_schema.resource_id)
    query = ObjectSetQuery(object_type=fact_kind)
    # The actual engine must reject our persisted template fixture before mocking the calculation.
    with pytest.raises(WorkspaceError, match="Reference and user-asserted"):
        guarded.aggregate_facts(operator, contract_ref.resource_id, query, [], None)
    computed = {
        "contract_id": contract_ref.resource_id,
        "contract_version_id": contract_ref.version_id,
        "schema_id": schema_ref.resource_id,
        "schema_version_id": schema_ref.version_id,
        "query": query.model_dump(mode="json"),
        "aggregation": "flow_sum",
        "as_of": None,
        "groups": [
            {
                "value": "10",
                "dimensions": {"unit": "GEL"},
                "inputs": [fact_ref.model_dump(mode="json")],
            }
        ],
        "input_count": 1,
        "state": "DERIVED",
        "authority": "SOURCE_BOUND_ANALYSIS",
        "financial_certification": None,
    }
    monkeypatch.setattr(guarded, "aggregate_facts", lambda *_: deepcopy(computed))
    monkeypatch.setenv(
        "FINAI_ACCESS_TOKENS",
        json.dumps({"synthetic-guarded-token": operator.model_dump(mode="json")}),
    )
    get_settings.cache_clear()
    client = TestClient(app)
    path = f"/v1/ontology/model/facts/{contract.resource_id}/aggregate/guarded"
    headers = {"Authorization": "Bearer synthetic-guarded-token"}
    request = {
        "consumer": consumer_ref.model_dump(mode="json"),
        "query": query.model_dump(mode="json"),
        "group_by": [],
    }
    events = {}

    def advance(subject, state):
        draft = LifecycleRequest(
            subject=subject,
            expected_event_id=events.get(subject.version_id),
            target_state=state,
            epistemic_state="OBSERVED",
            business_state="PROVISIONAL",
            availability_state="AVAILABLE",
            reason="Synthetic guarded fact lifecycle acceptance",
        )
        lifecycle.request_transition(operator, draft)
        lifecycle.review_transition(
            reviewer,
            draft.request_id,
            LifecycleReview(
                decision="APPROVED",
                reason="Independent synthetic lifecycle acceptance",
            ),
        )
        events[subject.version_id] = lifecycle.history(operator, subject)["events"][-1]["event_id"]

    try:
        assert client.post(path, json=request).status_code == 401
        blocked = client.post(path, json=request, headers=headers)
        assert blocked.status_code == 409, blocked.text
        for subject in refs:
            advance(subject, "OBSERVED")
        # Caller OBSERVED cannot weaken accepted consumer PARSED minimum.
        blocked = client.post(path, json=request, headers=headers)
        assert blocked.status_code == 409, blocked.text
        for subject in refs[:-1]:
            advance(subject, "PARSED")
        # Even a direct pin outside this computation must satisfy the consumer minimum.
        blocked = client.post(path, json=request, headers=headers)
        assert blocked.status_code == 409, blocked.text
        advance(refs[-1], "PARSED")
        mismatched = deepcopy(computed)
        mismatched["groups"][0]["inputs"][0]["version_id"] = str(uuid4())
        monkeypatch.setattr(guarded, "aggregate_facts", lambda *_: deepcopy(mismatched))
        denied = client.post(path, json=request, headers=headers)
        assert denied.status_code == 409, denied.text
        monkeypatch.setattr(guarded, "aggregate_facts", lambda *_: deepcopy(computed))
        success = client.post(path, json=request, headers=headers)
        assert success.status_code == 200, success.text
        retained = success.json()
        assert retained["authority"] == "SOURCE_BOUND_ANALYSIS"
        assert retained["financial_certification"] is None
        assert retained["current_use_authorized"] is False
        assert retained["authority_check"]
        proof = retained["authority_check"]
        assert proof["minimum_state"] == "PARSED"
        assert {entry["subject"]["version_id"] for entry in proof["inputs"]} == {
            str(subject.version_id) for subject in refs
        }
        receipt = lifecycle.consumption_receipt(operator, UUID(proof["consumption_id"]))
        assert receipt["proof_hash"] == proof["proof_hash"]
        assert fact_runs.read_run(operator, retained["run_id"]) == retained
        advance(fact_ref, "REVOKED")
        refused = client.post(path, json=request, headers=headers)
        assert refused.status_code == 409, refused.text
        assert fact_runs.read_run(operator, retained["run_id"]) == retained
        assert (
            lifecycle.consumption_status(operator, UUID(proof["consumption_id"]))["status"]
            == "BLOCKED"
        )
        other = operator.model_copy(
            update={"scope": operator.scope.model_copy(update={"legal_entity_id": "other"})}
        )
        with pytest.raises(WorkspaceError):
            fact_runs.read_run(other, retained["run_id"])
    finally:
        client.close()
        get_settings.cache_clear()
