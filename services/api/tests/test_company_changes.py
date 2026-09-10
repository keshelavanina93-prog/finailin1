"""Company knowledge changes use exact retained context, never current work or inference."""

from copy import deepcopy
from datetime import datetime

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_company_home import resource, uid

from finai_api.api.company_changes_routes import router
from finai_api.domain.company_changes import CompanyChangesRequest, CompanyContextChange
from finai_api.domain.resources import CanonicalResource
from finai_api.domain.review import Principal
from finai_api.security import authenticated_principal
from finai_api.services import company_changes as service
from finai_api.services.workspace import WorkspaceError


@pytest.fixture
def case(monkeypatch):
    principal = Principal(
        actor_id="changes-reader",
        display_name="Company changes reader",
        scope={
            "tenant_id": uid("tenant"),
            "legal_entity_id": "entity-ge-001",
            "period": "2026-08",
            "currency": "GEL",
        },
        permissions=("read", "ontology_read"),
    )
    request = CompanyChangesRequest(
        company_id=uid("Company"),
        valid_at="2025-01-31T00:00:00.123456Z",
        known_at="2025-02-15T00:00:00.654321Z",
        compare_known_at="2025-02-01T00:00:00Z",
    )
    snapshots, connections, calls = {}, {}, []
    for cutoff in (request.compare_known_at, request.known_at):
        company = resource("Company", "LegalEntity")
        snapshots[cutoff] = {
            "context": {"company": company, "structural_resources": [company]},
            "workspaces": [],
            "source_companies": [],
            "reported_groups": [],
            "valid_at": request.valid_at.isoformat(),
            "known_at": cutoff.isoformat(),
        }
        connections[cutoff] = ([CanonicalResource.model_validate(company)], {})

    def resolve(actor, company_id, valid_at, known_at):
        assert actor == principal and company_id == request.company_id
        assert valid_at == request.valid_at
        calls.append(("context", valid_at, known_at))
        return snapshots[known_at]

    def connected_snapshot(actor, valid_at, known_at):
        assert actor == principal and valid_at == request.valid_at
        calls.append(("connections", valid_at, known_at))
        return connections[known_at]

    def forbidden(*args, **kwargs):
        raise AssertionError("Current work must not become historical changes")

    monkeypatch.setattr(service.company_context, "resolve", resolve)
    monkeypatch.setattr(service.company_condition, "connection_snapshot", connected_snapshot)
    monkeypatch.setattr(service.company_condition, "current_work", forbidden)
    monkeypatch.setattr(service.company_condition, "describe", forbidden)
    return dict(
        principal=principal,
        request=request,
        snapshots=snapshots,
        connections=connections,
        calls=calls,
    )


def contexts(case):
    req = case["request"]
    return case["snapshots"][req.compare_known_at], case["snapshots"][req.known_at]


def compare(case):
    return service.compare(case["principal"], case["request"])


def test_same_effective_time_two_exact_cutoffs_and_no_current_advisory_change(case):
    _, after = contexts(case)
    # Even canonical-looking objects in current advice or tenant-wide lists are excluded.
    after["context"]["accounting_sources"] = [
        {"binding_eligibility": {"current": resource("Unrelated live advice", "Ledger")}}
    ]
    after["source_companies"] = [resource("Other company", "LegalEntity")]
    after["reported_groups"] = [{"company": resource("Other member", "LegalEntity")}]
    result = compare(case)
    assert result.changes == [] and len(case["calls"]) == 4
    assert {call[1] for call in case["calls"]} == {case["request"].valid_at}
    assert [call[2] for call in case["calls"]] == [
        case["request"].compare_known_at,
        case["request"].compare_known_at,
        case["request"].known_at,
        case["request"].known_at,
    ]
    assert result.known_at.microsecond == 654321 and result.valid_at.microsecond == 123456
    assert result.authority == "RETAINED_COMPANY_CONTEXT_COMPARISON"
    assert not result.business_effect_authorized and not result.current_use_authorized


def test_exact_versions_and_json_typed_changed_fields_are_deterministic(case):
    before, after = contexts(case)
    old = resource(
        "Ledger",
        "Ledger",
        {"flag": True, "amount": "1.23000000000000001", "a/b~x": "old", "absent": None},
    )
    new = deepcopy(old)
    new.update(
        version_id=str(uid("Ledger revision")),
        content_hash="b" * 64,
        system_from="2025-02-10T00:00:00Z",
        display_name="Reviewed ledger",
    )
    new["attributes"].update(flag=1, **{"a/b~x": "new"})
    del new["attributes"]["absent"]
    removed, added = resource("Old alias", "Alias"), resource("New dimension", "CompanyDimension")
    before["context"]["structural_resources"] += [removed, old, deepcopy(old)]
    after["context"]["structural_resources"] += [added, new]
    result = compare(case)
    assert [str(c.resource_id) for c in result.changes] == sorted(
        [old["resource_id"], removed["resource_id"], added["resource_id"]]
    )
    by_id = {str(c.resource_id): c for c in result.changes}
    changed = by_id[old["resource_id"]]
    assert changed.kind == "CHANGED_VERSION"
    assert changed.changed_fields == [
        "/attributes/absent",
        "/attributes/a~1b~0x",
        "/attributes/flag",
        "/display_name",
    ]
    assert changed.after.attributes["amount"] == "1.23000000000000001"
    assert by_id[removed["resource_id"]].kind == "REMOVED_FROM_CONTEXT"
    assert by_id[removed["resource_id"]].after is None
    assert by_id[added["resource_id"]].before is None
    assert by_id[added["resource_id"]].changed_fields == []


def test_matching_workspace_and_exact_pinned_connection_membership_only(case):
    _, after = contexts(case)
    company = after["context"]["company"]
    configuration = resource(
        "Workspace", "CompanyWorkspace", {"company_id": company["resource_id"]}
    )
    pack = resource("Pack", "DomainPack")
    after["workspaces"] = [
        {"company": company, "configuration": configuration, "domain_pack": pack},
        {
            "company": resource("Unselected", "LegalEntity"),
            "configuration": resource("Unselected workspace", "CompanyWorkspace"),
        },
    ]
    asset, unrelated = (
        resource("Connected asset", "Facility"),
        resource("Unbound asset", "Facility"),
    )
    relation = resource("Operates", "LinkType")
    edge = resource(
        "Asset connection",
        "Relationship",
        {
            "source_id": company["resource_id"],
            "target_id": asset["resource_id"],
            "relation_id": relation["resource_id"],
        },
    )
    nodes, pins = case["connections"][case["request"].known_at]
    nodes.extend(CanonicalResource.model_validate(v) for v in (asset, unrelated, relation, edge))
    for field, target in (("source_id", company), ("target_id", asset), ("relation_id", relation)):
        pins[(edge["version_id"], field)] = target["version_id"]
    result = compare(case)
    assert {str(c.resource_id) for c in result.changes} == {
        item["resource_id"] for item in (configuration, pack, edge, relation, asset)
    }
    # A stale target pin removes context membership, never substitutes a nearby version.
    pins[(edge["version_id"], "target_id")] = str(uid("stale asset version"))
    assert {str(c.resource_id) for c in compare(case).changes} == {
        configuration["resource_id"],
        pack["resource_id"],
    }


@pytest.mark.parametrize(
    "change",
    [
        {"authority_state": "REVOKED"},
        {"evidence_class": "REFERENCE_TEMPLATE"},
    ],
)
def test_unapproved_context_is_not_reported_as_company_presence(case, change):
    _, after = contexts(case)
    after["context"]["structural_resources"].append({**resource("Unused", "Facility"), **change})
    assert compare(case).changes == []


@pytest.mark.parametrize(
    "change",
    [
        {"access_entity": "other-entity"},
        {"system_from": "2025-03-01T00:00:00Z"},
        {"valid_from": "2025-02-01T00:00:00Z"},
        {"valid_to": "2025-01-30T00:00:00Z"},
        {"system_from": "2025-01-01T00:00:00"},
        {"content_hash": "malformed"},
    ],
)
def test_scope_and_temporal_snapshot_drift_refuse(case, change):
    _, after = contexts(case)
    after["context"]["structural_resources"].append({**resource("Drift", "Ledger"), **change})
    with pytest.raises(WorkspaceError) as refusal:
        compare(case)
    assert refusal.value.status == 409


@pytest.mark.parametrize("cutoff", ["known_at", "compare_known_at"])
def test_company_must_exist_at_both_cutoffs_without_creation_claim(case, cutoff):
    case["snapshots"][getattr(case["request"], cutoff)]["context"] = None
    with pytest.raises(WorkspaceError) as refusal:
        compare(case)
    assert refusal.value.status == 404


@pytest.mark.parametrize(
    "fault", ["duplicate-version", "immutable-content", "object-type", "cutoff"]
)
def test_conflicting_versions_identity_and_cutoffs_fail_closed(case, fault):
    before, after = contexts(case)
    old = resource("Ambiguous", "Ledger")
    new = {**old, "version_id": str(uid("alternate")), "content_hash": "b" * 64}
    before["context"]["structural_resources"].append(old)
    after["context"]["structural_resources"].append(new)
    if fault == "duplicate-version":
        after["context"]["structural_resources"].append(old)
    elif fault == "immutable-content":
        new["version_id"] = old["version_id"]
    elif fault == "object-type":
        new["object_type"] = "Facility"
    else:
        after["known_at"] = before["known_at"]
    with pytest.raises(WorkspaceError) as refusal:
        compare(case)
    assert refusal.value.status == 409


def test_snapshot_and_result_bounds_refuse_without_truncation(case, monkeypatch):
    before, after = contexts(case)
    before["context"]["structural_resources"].append(resource("Removed", "Alias"))
    after["context"]["structural_resources"].append(resource("Added", "Alias"))
    monkeypatch.setattr(service, "RESOURCE_LIMIT", 1)
    with pytest.raises(WorkspaceError, match="resource bound"):
        compare(case)
    monkeypatch.setattr(service, "RESOURCE_LIMIT", 5000)
    monkeypatch.setattr(service, "RESPONSE_BYTES", 1)
    with pytest.raises(WorkspaceError, match="snapshot byte bound"):
        compare(case)
    # Each snapshot fits separately, but all before/after response rows may exceed the cap.
    request = case["request"]
    monkeypatch.setattr(service, "RESPONSE_BYTES", 8 * 1024 * 1024)
    _, old = service._snapshot(
        case["principal"], request.company_id, request.valid_at, request.compare_known_at
    )
    monkeypatch.setattr(
        service, "RESPONSE_BYTES", sum(len(n.model_dump_json().encode()) for n in old.values()) + 10
    )
    with pytest.raises(WorkspaceError, match="response byte bound"):
        compare(case)


def test_changes_require_permissions_and_strict_ordered_aware_request(case):
    for permission in ("read", "ontology_read"):
        principal = case["principal"].model_copy(update={"permissions": (permission,)})
        with pytest.raises(HTTPException) as refusal:
            service.compare(principal, case["request"])
        assert refusal.value.status_code == 403
    assert case["calls"] == []
    for change in (
        {"compare_known_at": case["request"].known_at},
        {"known_at": case["request"].compare_known_at},
        {"valid_at": "2025-01-31T00:00:00"},
        {"other_company_id": str(uid("foreign"))},
    ):
        with pytest.raises(ValidationError):
            CompanyChangesRequest.model_validate({**case["request"].model_dump(), **change})


def test_route_exposes_exact_read_contract_and_validation_errors(case):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[authenticated_principal] = lambda: case["principal"]
    with TestClient(app) as client:
        payload = case["request"].model_dump(mode="json")
        response = client.post("/v1/ontology/company-changes", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert body["company"]["resource_id"] == payload["company_id"]
        assert body["contract"] == "g8-company-changes/1" and body["changes"] == []
        assert datetime.fromisoformat(body["valid_at"]) == case["request"].valid_at
        invalid = {**payload, "compare_known_at": payload["known_at"]}
        assert client.post("/v1/ontology/company-changes", json=invalid).status_code == 422
        app.dependency_overrides[authenticated_principal] = lambda: (_ for _ in ()).throw(
            HTTPException(401, "No authenticated reader")
        )
        assert client.post("/v1/ontology/company-changes", json=payload).status_code == 401


@pytest.mark.parametrize("duplicate_in_snapshot", [False, True])
def test_one_exact_version_cannot_change_json_scalar_type(case, duplicate_in_snapshot):
    before, after = contexts(case)
    original = resource("Boolean contract", "Ledger", {"enabled": True})
    changed = {**original, "attributes": {"enabled": 1}}
    before["context"]["structural_resources"].append(original)
    after["context"]["structural_resources"].append(changed)
    if duplicate_in_snapshot:
        after["context"]["structural_resources"].append(original)
    with pytest.raises(WorkspaceError) as refusal:
        compare(case)
    assert refusal.value.status == 409


def test_response_sides_cannot_claim_a_different_resource_or_membership_mutation():
    node = resource("Node", "Facility")
    for changes in (
        {"after": resource("Other", "Facility")},
        {"changed_fields": ["/attributes/x"]},
        {"before": node},
        {"kind": "CHANGED_VERSION"},
    ):
        with pytest.raises(ValidationError):
            CompanyContextChange.model_validate(
                {
                    "resource_id": node["resource_id"],
                    "kind": "ADDED_TO_CONTEXT",
                    "before": None,
                    "after": node,
                    "changed_fields": [],
                    **changes,
                }
            )
