import os
from datetime import UTC, datetime
from uuid import UUID, uuid4, uuid5

import pytest
from fastapi.testclient import TestClient

from finai_api.domain.authority import ExactScope
from finai_api.domain.object_sets import ObjectSetQuery, PropertyFilter, Traversal
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceMutation, ResourceProposal, ResourceReview
from finai_api.domain.review import Principal
from finai_api.main import app
from finai_api.security import authenticated_principal
from finai_api.services import resources
from finai_api.services.object_sets import query_objects


def test_filter_values_preserve_json_types():
    assert PropertyFilter(field="active", value=True).value is True
    assert type(PropertyFilter(field="count", value=7).value) is int
    assert PropertyFilter(field="code", value="007").value == "007"


@pytest.mark.skipif(os.environ.get("G8_BINDING_DB_TEST") != "1", reason="Local PostgreSQL opt-in")
def test_persistent_object_sets_paging_traversal_and_version_pins():
    tenant = UUID("805d8a32-d12b-4268-a236-b0b16e59da9f")
    principal = Principal(
        actor_id="synthetic-object-set-author",
        display_name="Synthetic ontology query",
        scope=ExactScope(
            tenant_id=tenant,
            legal_entity_id="sets-" + uuid4().hex,
            period="2026-08",
            currency="GEL",
        ),
        permissions=("ontology_read", "ontology_propose", "ontology_review"),
    )
    start = datetime(2026, 1, 1, tzinfo=UTC)

    def item(kind, name, attributes):
        return ResourceMutation(
            object_type=kind,
            identity_key=uuid4().hex,
            display_name=name,
            attributes=attributes,
            valid_from=start,
        )

    def accept(mutations):
        proposal = ResourceProposal(
            title="Synthetic Object Set runtime fixture",
            rationale="Verify canonical query and dependency behavior",
            access_entity=principal.scope.legal_entity_id,
            mutations=mutations,
        )
        resources.propose(principal, proposal)
        resources.review(
            principal.model_copy(update={"actor_id": "synthetic-set-reviewer"}),
            proposal.proposal_id,
            ResourceReview(decision="APPROVED", rationale="Reviewed synthetic query fixtures"),
        )
        return proposal

    company = item("LegalEntity", "Synthetic company", {})
    units = [
        item("BusinessUnit", f"Synthetic unit {i:03}", {"code": f"U{i:03}"}) for i in range(55)
    ]
    party = item("Party", "Original synthetic party", {"registration_code": "001"})
    customers = [
        item("Customer", f"Synthetic customer {i}", {"party_id": str(party.resource_id)})
        for i in range(2)
    ]
    relation = item(
        "Relationship",
        "Company unit",
        {
            "source_id": str(company.resource_id),
            "target_id": str(units[0].resource_id),
            "relation_id": str(canonical_id(tenant, "LinkType", "HAS_BUSINESS_UNIT")),
        },
    )
    proposal = accept([company, *units, party, *customers, relation])
    query = ObjectSetQuery(object_type="BusinessUnit", limit=10)
    first = query_objects(principal, query)
    assert first.total == 55 and first.counts_by_type == {"BusinessUnit": 55}
    assert len(first.objects) == 10 and first.next_offset == 10
    second = query_objects(principal, first.query.model_copy(update={"offset": 10}))
    assert {o["version_id"] for o in first.objects}.isdisjoint(
        o["version_id"] for o in second.objects
    )
    filtered = query_objects(
        principal,
        query.model_copy(update={"filters": [PropertyFilter(field="code", value="U054")]}),
    )
    assert filtered.total == 1 and filtered.objects[0]["attributes"]["code"] == "U054"
    assert query_objects(principal, query.model_copy(update={"resource_ids": []})).total == 0
    linked = query_objects(
        principal,
        ObjectSetQuery(
            object_type="LegalEntity", traversal=[Traversal(kind="link", name="HAS_BUSINESS_UNIT")]
        ),
    )
    assert linked.total == 1 and linked.objects[0]["resource_id"] == str(units[0].resource_id)
    reverse = query_objects(
        principal,
        ObjectSetQuery(
            object_type="BusinessUnit",
            traversal=[Traversal(kind="link", name="HAS_BUSINESS_UNIT", direction="incoming")],
        ),
    )
    assert reverse.total == 1 and reverse.objects[0]["resource_id"] == str(company.resource_id)
    before = query_objects(principal, ObjectSetQuery(object_type="Party"))
    original_version = uuid5(proposal.proposal_id, str(party.resource_id))
    accept(
        [
            party.model_copy(
                update={
                    "expected_version_id": original_version,
                    "display_name": "Updated synthetic party",
                }
            )
        ]
    )
    pinned = query_objects(
        principal, ObjectSetQuery(object_type="Customer", traversal=[Traversal(name="party_id")])
    )
    assert pinned.total == 1  # two customers converge on one exact version
    assert pinned.objects[0]["version_id"] == str(original_version)
    assert pinned.objects[0]["display_name"] == "Original synthetic party"
    assert query_objects(principal, before.query).objects[0]["version_id"] == str(original_version)
    incoming = query_objects(
        principal,
        ObjectSetQuery(
            object_type="Party",
            known_at=before.query.known_at,
            traversal=[Traversal(name="party_id", direction="incoming")],
        ),
    )
    assert incoming.total == 2
    other = principal.model_copy(
        update={"scope": principal.scope.model_copy(update={"tenant_id": uuid4()})}
    )
    assert query_objects(other, query).total == 0
    app.dependency_overrides[authenticated_principal] = lambda: principal
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/ontology/object-sets/query", json={"object_type": "BusinessUnit", "limit": 10}
            )
            assert response.status_code == 200 and response.json()["total"] == 55
            assert (
                client.post(
                    "/v1/ontology/object-sets/query",
                    json={"object_type": "BusinessUnit", "limit": 10000},
                ).status_code
                == 422
            )
    finally:
        app.dependency_overrides.pop(authenticated_principal, None)
