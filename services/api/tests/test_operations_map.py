"""Spatial authority acceptance with isolated, explicitly synthetic resources."""

import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from finai_api.domain.authority import ExactScope
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceMutation, ResourceProposal, ResourceReview
from finai_api.domain.review import Principal
from finai_api.domain.spatial import validate_geometry
from finai_api.services import operations_map as maps
from finai_api.services import resources
from finai_api.services.spatial_import import SpatialImportRequest, import_proposal
from finai_api.services.workspace import WorkspaceError


@pytest.mark.parametrize(
    "geometry",
    [
        {"type": "Point", "coordinates": [181, 42]},
        {"type": "Point", "coordinates": [True, 42]},
        {"type": "Point", "coordinates": [float("nan"), 42]},
        {"type": "LineString", "coordinates": [[44, 42]]},
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1]]]},
        {"type": "Point", "coordinates": [44, 42], "crs": "unknown"},
    ],
)
def test_reject_invalid_geometry(geometry):
    with pytest.raises(ValueError):
        validate_geometry(geometry)


def test_bbox_invalid_and_dateline_explicit():
    for bbox in ("nan,0,45,42", "180,0,-180,42", "0,0,181,42", "1,2,3"):
        with pytest.raises(WorkspaceError) as exc:
            maps.bbox_value(bbox)
        assert exc.value.status == 422


@pytest.fixture
def actors():
    if os.environ.get("G8_BINDING_DB_TEST") != "1":
        pytest.skip("Opt-in PostgreSQL spatial acceptance")
    actor = Principal(
        actor_id="synthetic-spatial-proposer",
        display_name="SYNTHETIC spatial",
        scope=ExactScope(
            tenant_id=UUID("805d8a32-d12b-4268-a236-b0b16e59da9f"),
            legal_entity_id="synthetic-spatial-" + uuid4().hex,
            period="2026-08",
            currency="GEL",
        ),
        permissions=("ontology_read", "ontology_propose", "ontology_review"),
    )
    return actor, actor.model_copy(update={"actor_id": "synthetic-spatial-reviewer"})


def accepted(actors, mutations):
    proposer, reviewer = actors
    proposal = ResourceProposal(
        title="SYNTHETIC spatial acceptance",
        rationale="Isolated controlled map contract, not authentic company data",
        access_entity=proposer.scope.legal_entity_id,
        mutations=mutations,
    )
    resources.propose(proposer, proposal)
    resources.review(
        reviewer,
        proposal.proposal_id,
        ResourceReview(decision="APPROVED", rationale="Independent synthetic spatial review"),
    )
    return proposal


def node(kind, attributes, **updates):
    return ResourceMutation(
        object_type=kind,
        identity_key="synthetic:spatial:" + uuid4().hex,
        display_name="SYNTHETIC " + kind,
        attributes=attributes,
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        evidence_class="REFERENCE_TEMPLATE",
        **updates,
    )


def test_import_pending_approval_scope_bbox_history_and_coordinates(actors):
    proposer, reviewer = actors
    company = node("LegalEntity", {})
    accepted(actors, [company])
    request = SpatialImportRequest(
        company_id=company.resource_id,
        title="SYNTHETIC map source",
        rationale="Controlled user supplied map, not authentic evidence",
        valid_from=datetime(2026, 1, 2, tzinfo=UTC),
        geojson={
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [44, 42]},
                    "properties": {"name": "SYNTHETIC station", "code": "001"},
                }
            ],
        },
    )
    detail = import_proposal(proposer, request)
    assert maps.map_view(proposer, company_id=company.resource_id)["counts"]["assets"] == 0
    resources.review(
        reviewer,
        detail.proposal.proposal_id,
        ResourceReview(decision="APPROVED", rationale="Independent controlled import review"),
    )
    original_time = datetime.now(UTC)
    original = maps.map_view(proposer, company_id=company.resource_id)
    assert original["features"][0]["geometry"]["coordinates"] == [44, 42]
    assert original["features"][0]["properties"]["resource"]["evidence_class"] == "USER_ASSERTED"
    assert maps.map_view(proposer, bbox="0,0,20,20")["counts"]["outside_bounds"] == 1
    hidden = proposer.model_copy(
        update={
            "scope": proposer.scope.model_copy(
                update={"legal_entity_id": "unrelated-" + uuid4().hex}
            )
        }
    )
    assert maps.map_view(hidden)["counts"]["assets"] == 0
    with pytest.raises(WorkspaceError):
        maps.map_view(hidden, company_id=company.resource_id)
    other_tenant = proposer.model_copy(
        update={"scope": proposer.scope.model_copy(update={"tenant_id": uuid4()})}
    )
    assert maps.map_view(other_tenant)["features"] == []
    location = detail.proposal.mutations[1]
    previous = original["features"][0]["properties"]["resource"]
    accepted(
        actors,
        [
            location.model_copy(
                update={
                    "expected_version_id": UUID(previous["version_id"]),
                    "attributes": {
                        **location.attributes,
                        "geometry": {"type": "Point", "coordinates": [45, 43]},
                    },
                }
            )
        ],
    )
    assert maps.map_view(proposer)["features"][0]["geometry"]["coordinates"] == [45, 43]
    assert maps.map_view(proposer, known_at=original_time)["features"][0]["geometry"][
        "coordinates"
    ] == [44, 42]
    assert maps.map_view(proposer, valid_at=datetime(2025, 1, 1, tzinfo=UTC))["features"] == []
    with pytest.raises(WorkspaceError):
        maps.map_view(proposer, valid_at=datetime(2026, 1, 1))


def test_explicit_directed_connections_depth_and_company(actors):
    proposer, _ = actors
    company = node("LegalEntity", {})
    other_company = node("LegalEntity", {})
    accepted(actors, [company, other_company])
    zone = node("PressureZone", {"code": "P1", "legal_entity_id": str(company.resource_id)})
    customer = node(
        "CustomerConnection", {"code": "C1", "legal_entity_id": str(company.resource_id)}
    )
    nearby = node(
        "CustomerConnection",
        {
            "code": "C2",
            "legal_entity_id": str(other_company.resource_id),
            "geometry": {"type": "Point", "coordinates": [44, 42]},
        },
    )
    accepted(actors, [zone, customer, nearby])
    relation = node(
        "Relationship",
        {
            "relation_id": str(canonical_id(proposer.scope.tenant_id, "LinkType", "SUPPLIES")),
            "source_id": str(zone.resource_id),
            "target_id": str(customer.resource_id),
        },
    )
    accepted(actors, [relation])
    result = maps.connections(proposer, zone.resource_id, company_id=company.resource_id)
    assert {r["resource_id"] for r in result["resources"]} == {
        str(zone.resource_id),
        str(customer.resource_id),
    }
    assert result["edges"][0]["relation"] == "SUPPLIES"
    assert len(maps.connections(proposer, customer.resource_id)["resources"]) == 1
    assert maps.map_view(proposer, company_id=company.resource_id)["counts"]["assets"] == 2
    with pytest.raises(WorkspaceError):
        maps.connections(proposer, zone.resource_id, depth=6)


def test_authentication_permission_and_route_validation():
    from fastapi.testclient import TestClient

    from finai_api.main import app

    client = TestClient(app)
    assert client.get("/v1/operations/map").status_code == 401
    # The default test grant has no ontology_read capability.
    assert (
        client.get("/v1/operations/map", headers={"Authorization": "Bearer test-token"}).status_code
        == 403
    )


def test_bounded_snapshot_and_visible_feature_truncation(actors, monkeypatch):
    proposer, _ = actors
    location = node("Location", {"code": "L1", "latitude": "42", "longitude": "44"})
    accepted(actors, [location])
    real = resources.list_resources(proposer, "Location", "", 0)[0]
    rows = [
        real.model_copy(update={"resource_id": uuid4(), "display_name": f"SYNTHETIC {i}"})
        for i in range(101)
    ]
    monkeypatch.setattr(maps, "SCAN_LIMIT", 100)
    monkeypatch.setattr(
        resources,
        "list_resources",
        lambda principal, kind, search, offset, valid, known: rows[offset : offset + 100],
    )
    result = maps.map_view(proposer, limit=3)
    assert len(result["features"]) == 3
    assert result["counts"]["mapped_in_bounds"] == 100
    assert result["completeness"]["snapshot_bounded"] is True
    assert result["completeness"]["features_truncated"] is True


def test_depth_bound_not_claimed_complete(actors):
    proposer, _ = actors
    source = node("DeliveryPoint", {"code": "D"})
    zone = node("PressureZone", {"code": "Z"})
    customer = node("CustomerConnection", {"code": "C"})
    accepted(actors, [source, zone, customer])
    edges = [
        node(
            "Relationship",
            {
                "relation_id": str(canonical_id(proposer.scope.tenant_id, "LinkType", kind)),
                "source_id": str(a.resource_id),
                "target_id": str(b.resource_id),
            },
        )
        for kind, a, b in [("FEEDS", source, zone), ("SUPPLIES", zone, customer)]
    ]
    accepted(actors, edges)
    short = maps.connections(proposer, source.resource_id, depth=1)
    assert len(short["resources"]) == 2
    assert short["completeness"]["depth_bounded"] is True
    complete = maps.connections(proposer, source.resource_id, depth=2)
    assert len(complete["resources"]) == 3
    assert complete["completeness"]["depth_bounded"] is False
