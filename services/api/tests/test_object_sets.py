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
    mixed = query_objects(
        principal,
        ObjectSetQuery(
            object_type="Customer",
            traversal=[
                Traversal(name="party_id"),
                Traversal(name="party_id", direction="incoming"),
            ],
        ),
    )
    assert mixed.total == 2  # incoming from an outgoing historical pin, not the new party head
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


@pytest.mark.skipif(os.environ.get("G8_BINDING_DB_TEST") != "1", reason="Local PostgreSQL opt-in")
def test_incoming_and_typed_links_select_temporal_candidate_before_authority_filter():
    from test_historical_graph import accept, node

    p = Principal(
        actor_id="synthetic-reverse-author",
        display_name="Synthetic reverse traversal",
        scope=ExactScope(
            tenant_id=UUID("805d8a32-d12b-4268-a236-b0b16e59da9f"),
            legal_entity_id="reverse-" + uuid4().hex,
            period="2026-09",
            currency="GEL",
        ),
        permissions=("ontology_read", "ontology_propose", "ontology_review"),
    )
    actors = p, p.model_copy(update={"actor_id": "independent-reverse-reviewer"})
    first, second = accept(actors, [node("Party", "first", {}), node("Party", "second", {})])
    customer_mutation = node("Customer", "moving customer", {"party_id": str(first.resource_id)})
    original = accept(actors, [customer_mutation])[0]

    def incoming(party, **times):
        return query_objects(
            p,
            ObjectSetQuery(
                object_type="Party",
                resource_ids=[party.resource_id],
                traversal=[Traversal(name="party_id", direction="incoming")],
                **times,
            ),
        )

    moved = accept(
        actors,
        [
            customer_mutation.model_copy(
                update={
                    "expected_version_id": original.version_id,
                    "attributes": {"party_id": str(second.resource_id)},
                    "valid_from": datetime(2026, 3, 1, tzinfo=UTC),
                }
            )
        ],
    )[0]
    assert incoming(first).total == 0
    assert incoming(second).objects[0]["version_id"] == str(moved.version_id)
    assert incoming(first, known_at=original.system_from).total == 1
    assert incoming(first, valid_at=datetime(2026, 2, 1, tzinfo=UTC)).total == 1
    assert incoming(second, valid_at=datetime(2026, 2, 1, tzinfo=UTC)).total == 0
    accept(
        actors,
        [
            customer_mutation.model_copy(
                update={
                    "expected_version_id": moved.version_id,
                    "attributes": {"party_id": str(second.resource_id)},
                    "authority_state": "REVOKED",
                }
            )
        ],
    )
    assert incoming(second).total == 0  # revoked correction must not resurrect approved predecessor
    assert incoming(second, known_at=moved.system_from).total == 1

    company, unit_a, unit_b = accept(
        actors,
        [
            node("LegalEntity", "company", {}),
            node("BusinessUnit", "unit A", {"code": "A"}),
            node("BusinessUnit", "unit B", {"code": "B"}),
        ],
    )
    relationship = node(
        "Relationship",
        "unit relationship",
        {
            "source_id": str(company.resource_id),
            "target_id": str(unit_a.resource_id),
            "relation_id": str(canonical_id(p.scope.tenant_id, "LinkType", "HAS_BUSINESS_UNIT")),
        },
    )
    old_link = accept(actors, [relationship])[0]
    new_link = accept(
        actors,
        [
            relationship.model_copy(
                update={
                    "expected_version_id": old_link.version_id,
                    "attributes": {**relationship.attributes, "target_id": str(unit_b.resource_id)},
                }
            )
        ],
    )[0]
    outgoing = ObjectSetQuery(
        object_type="LegalEntity",
        resource_ids=[company.resource_id],
        traversal=[Traversal(kind="link", name="HAS_BUSINESS_UNIT")],
    )
    assert query_objects(p, outgoing).objects[0]["resource_id"] == str(unit_b.resource_id)
    assert query_objects(p, outgoing.model_copy(update={"known_at": old_link.system_from})).objects[
        0
    ]["resource_id"] == str(unit_a.resource_id)
    reverse = ObjectSetQuery(
        object_type="BusinessUnit",
        resource_ids=[unit_a.resource_id],
        traversal=[Traversal(kind="link", name="HAS_BUSINESS_UNIT", direction="incoming")],
    )
    assert query_objects(p, reverse).total == 0
    assert (
        query_objects(p, reverse.model_copy(update={"known_at": old_link.system_from})).total == 1
    )
    accept(
        actors,
        [
            relationship.model_copy(
                update={
                    "expected_version_id": new_link.version_id,
                    "attributes": {**relationship.attributes, "target_id": str(unit_b.resource_id)},
                    "authority_state": "REVOKED",
                }
            )
        ],
    )
    assert query_objects(p, outgoing).total == 0
    denied = p.model_copy(update={"scope": p.scope.model_copy(update={"legal_entity_id": "other"})})
    assert query_objects(denied, outgoing).total == 0
