"""Synthetic definition certification through real publication, lifecycle and SQL guards."""

from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from test_certification import attributes, ref
from test_definition_history import DB

from finai_api.domain.authority import ExactScope
from finai_api.domain.certification import CertificationEvaluationRequest
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resource_lifecycle import (
    ConsumptionRequest,
    LifecycleRequest,
    LifecycleReview,
)
from finai_api.domain.resources import ResourceMutation, ResourceProposal, ResourceReview
from finai_api.domain.review import Principal
from finai_api.services import certification, resources
from finai_api.services import resource_lifecycle as lifecycle
from finai_api.services.workspace import WorkspaceError


@DB
def test_exact_certified_consumption_and_policy_withdrawal():
    tenant = UUID("805d8a32-d12b-4268-a236-b0b16e59da9f")
    entity = "synthetic-certified-" + uuid4().hex
    author = Principal(
        actor_id="synthetic-certification-author",
        display_name="Synthetic verifier",
        scope=ExactScope(
            tenant_id=tenant, legal_entity_id=entity, period="2026-08", currency="GEL"
        ),
        permissions=("ontology_read", "ontology_propose", "ontology_review", "ontology_admin"),
    )
    reviewer = author.model_copy(update={"actor_id": "synthetic-certification-reviewer"})

    def publish(*mutations):
        proposal = ResourceProposal(
            title="Synthetic certified consumption definitions",
            rationale="Exercise exact conformance requirements without financial certification",
            access_entity="__TENANT__",
            mutations=list(mutations),
        )
        resources.propose(author, proposal)
        resources.review(
            reviewer,
            proposal.proposal_id,
            ResourceReview(
                decision="APPROVED", rationale="Independent synthetic contract publication"
            ),
        )
        return [resources.get_resource(author, item.resource_id)["resource"] for item in mutations]

    def mutation(kind, attrs, scope=entity, **extra):
        return ResourceMutation(
            object_type=kind,
            identity_key="synthetic:" + uuid4().hex,
            display_name="SYNTHETIC " + kind,
            attributes=attrs,
            access_entity=scope,
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            **extra,
        )

    subject = mutation("ObjectSetDefinition", {"definition": {"object_type": "LegalEntity"}})
    policy = mutation(
        "CertificationContract",
        attributes(schema=canonical_id(tenant, "SchemaDefinition", "ObjectSetDefinition")),
    )
    subject_row, policy_row = publish(subject, policy)
    requirements = {str(subject.resource_id): ref(policy_row).model_dump(mode="json")}
    kind = "CertifiedConsumer" + uuid4().hex[:12]
    schema = mutation(
        "SchemaDefinition",
        {
            "additional_fields": False,
            "fields": {
                "minimum_authority_state": {
                    "field_id": str(uuid4()),
                    "kind": "identifier",
                    "required": True,
                    "semantic_id": str(canonical_id(tenant, "SemanticContract", "Identifier")),
                },
                "certification_requirements": {
                    "field_id": str(uuid4()),
                    "kind": "definition",
                    "required": True,
                    "semantic_id": str(
                        canonical_id(tenant, "SemanticContract", "OntologyDefinition")
                    ),
                },
            },
        },
        scope="__PLATFORM__",
    ).model_copy(update={"identity_key": kind})
    consumer = mutation(
        kind, {"minimum_authority_state": "CERTIFIED", "certification_requirements": requirements}
    )
    schema_row, consumer_row = publish(schema, consumer)
    events = {}

    def transition(resource, state, **extra):
        reference = ref(resource)
        request = LifecycleRequest(
            subject=reference,
            expected_event_id=events.get(reference.version_id),
            target_state=state,
            epistemic_state="DERIVED",
            business_state="PROVISIONAL",
            availability_state="AVAILABLE",
            reason="Synthetic explicit authority decision",
            **extra,
        )
        lifecycle.request_transition(author, request)
        lifecycle.review_transition(
            reviewer,
            request.request_id,
            LifecycleReview(decision="APPROVED", reason="Independent synthetic authority review"),
        )
        events[reference.version_id] = lifecycle.history(author, reference)["events"][-1][
            "event_id"
        ]

    for resource in (subject_row, policy_row, schema_row):
        for state in lifecycle.ORDER:
            transition(resource, state)
    request = ConsumptionRequest(
        consumer=ref(consumer_row),
        inputs=[ref(row) for row in (subject_row, policy_row, schema_row)],
    )
    with pytest.raises(WorkspaceError, match="required authority"):
        lifecycle.consume(author, request)
    receipt = certification.evaluate(
        author, CertificationEvaluationRequest(subject=ref(subject_row), contract=ref(policy_row))
    )
    transition(
        subject_row,
        "CERTIFIED",
        certification_receipt_id=receipt["receipt_id"],
        certification_contract=ref(policy_row),
    )
    result = lifecycle.consume(author, request)
    assert result["contract_version"] == "guarded-consumption/3"
    assert result["minimum_state"] == "CERTIFIED"
    assert sum(bool(item.get("authority_control")) for item in result["inputs"]) == 2
    assert lifecycle.consume(author, request) == result
    assert lifecycle.consumption_status(author, request.request_id)["status"] == "RECHECK_REQUIRED"
    history = lifecycle.consumption_receipt(author, request.request_id)

    forged = deepcopy(history["proof"])
    forged_id = uuid4()
    forged["consumption_id"] = str(forged_id)
    material = next(
        item
        for item in forged["inputs"]
        if item["subject"] == ref(subject_row).model_dump(mode="json")
    )
    material["authority_control"] = True
    material.pop("certification")
    with pytest.raises(psycopg.Error), resources.resource_connection(author) as conn:
        conn.execute(
            "INSERT INTO guarded_consumption_receipts "
            "SELECT tenant_id,%s,consumer_resource_id,consumer_version_id,access_entity,actor_id,"
            "request_hash,%s,%s,recorded_at FROM guarded_consumption_receipts "
            "WHERE tenant_id=%s AND consumption_id=%s",
            (
                forged_id,
                lifecycle._proof_hash(forged),
                Jsonb(forged),
                tenant,
                request.request_id,
            ),
        )

    ordinary = mutation(
        kind,
        {"minimum_authority_state": "AUTHORITATIVE", "certification_requirements": requirements},
    )
    ordinary_row = publish(ordinary)[0]
    ordinary_request = request.model_copy(
        update={"request_id": uuid4(), "consumer": ref(ordinary_row)}
    )
    lifecycle.consume(author, ordinary_request)
    publish(
        policy.model_copy(
            update={
                "expected_version_id": UUID(policy_row["version_id"]),
                "authority_state": "REVOKED",
            }
        )
    )
    for consumption in (request, ordinary_request):
        with pytest.raises(WorkspaceError):
            lifecycle.consume(author, consumption.model_copy(update={"request_id": uuid4()}))
        assert lifecycle.consumption_status(author, consumption.request_id)["status"] == "BLOCKED"
    assert lifecycle.consumption_receipt(author, request.request_id) == history
    with (
        resources.resource_connection(author) as conn,
        conn.cursor(row_factory=dict_row) as cursor,
        pytest.raises(WorkspaceError),
    ):
        certification.receipt_for_current_use(
            cursor, author, UUID(receipt["receipt_id"]), ref(subject_row)
        )
