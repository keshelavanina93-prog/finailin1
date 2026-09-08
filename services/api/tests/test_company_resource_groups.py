"""Descriptor groups reuse exact ontology semantics, never UI category names."""

# ruff: noqa: F811
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_company_condition import case, link, node  # noqa: F401
from test_company_home import resource, uid

from finai_api.api.company_condition_routes import router
from finai_api.security import authenticated_principal
from finai_api.services import company_condition as service
from finai_api.services import company_resource_groups as groups


def definition(kind="MeterReading"):
    schema = resource(kind, "SchemaDefinition", {"fields": {}})
    group = resource("Readings", "ObjectTypeGroup", {"definition": {"types": [kind]}})
    group["dependencies"] = [{**schema, "relation": "DEFINITION_TYPE:" + kind}]
    rows = {row["resource_id"]: row for row in [group, schema]}
    return group, schema, lambda identity, version: rows.get(str(identity))


@pytest.mark.parametrize("kind", ["MeterReading", "SafetyInspection"])
def test_unknown_type_group_is_resolved_and_only_connected_members_count(case, monkeypatch, kind):
    group, _schema, load = definition(kind)
    resolved = groups.resolve_definitions([group], load)
    member = node(case, "Exact connected member", kind)
    member = member.model_copy(update={"schema_version_id": uid(kind + ":version")})
    case["nodes"][-1] = member
    node(case, "Unconnected", kind)
    link(case, case["company"], member)
    monkeypatch.setattr(groups, "definitions", lambda *_: resolved)
    monkeypatch.setattr(service, "connection_snapshot", lambda *_: (case["nodes"], case["pins"]))
    result = service.describe(case["principal"], case["company"].resource_id, contract_version=2)
    actual = result.resource_groups[0]
    assert result.contract == "g8-company-condition/2"
    assert actual.resources == [member] and actual.count == 1
    assert actual.key == group["resource_id"] and actual.definition.version_id == uid(
        "Readings:version"
    )
    assert actual.definition_pins[1].version_id == uid(kind + ":version")
    assert actual.valid_at.isoformat() == case["snapshot"]["valid_at"]
    assert not result.current_use_authorized and not result.business_effect_authorized
    assert "assets" not in result.model_dump()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[authenticated_principal] = lambda: case["principal"]
    client = TestClient(app)
    response = client.get(
        f"/v1/ontology/company-condition?company_id={case['company'].resource_id}&contract_version=2"
    )
    assert response.status_code == 200 and response.json()["resource_groups"][0]["count"] == 1
    assert (
        client.get(
            f"/v1/ontology/company-condition?company_id={case['company'].resource_id}&contract_version=3"
        ).status_code
        == 422
    )


def test_missing_schema_pin_is_unavailable_not_empty():
    group, _, load = definition()
    group["dependencies"] = []
    result = groups.project(
        groups.resolve_definitions([group], load),
        [],
        datetime.now().astimezone(),
        datetime.now().astimezone(),
    )[0]
    assert result.state == "UNAVAILABLE" and result.count is None


def test_domain_pack_cannot_invent_group_membership():
    pack = resource("Gas semantics", "DomainPack", {"code": "GAS", "version": "1"})
    result = groups.project(
        groups.resolve_definitions([pack], lambda *_: None),
        [],
        datetime.now().astimezone(),
        datetime.now().astimezone(),
    )[0]
    assert result.state == "UNAVAILABLE" and result.count is None
    assert "DomainPack" in result.reason


def test_schema_changed_member_refuses_count(case):
    group, _, load = definition()
    member = node(case, "Reading", "MeterReading")
    link(case, case["company"], member)
    connections = service.connected(case["company"], case["nodes"], case["pins"], {"MeterReading"})
    result = groups.project(
        groups.resolve_definitions([group], load),
        connections,
        datetime.now().astimezone(),
        datetime.now().astimezone(),
    )[0]
    assert result.state == "UNAVAILABLE" and result.count is None and result.resources == []


@pytest.mark.parametrize(
    "failure",
    ["empty", "missing_self", "wrong_version", "wrong_hash", "duplicate_self", "over_bound"],
)
def test_response_contract_requires_bounded_exact_self_pin(failure):
    from pydantic import ValidationError

    from finai_api.domain.company_condition import CompanyOperatingResourceGroup

    group, _, load = definition()
    now = datetime.now().astimezone()
    payload = groups.project(groups.resolve_definitions([group], load), [], now, now)[
        0
    ].model_dump()
    pins = payload["definition_pins"]
    if failure == "empty":
        payload["definition_pins"] = []
    elif failure == "missing_self":
        payload["definition_pins"] = pins[1:]
    elif failure == "wrong_version":
        pins[0]["version_id"] = uid("other version")
    elif failure == "wrong_hash":
        pins[0]["content_hash"] = "b" * 64
    elif failure == "duplicate_self":
        pins.append(dict(pins[0]))
    else:
        payload["definition_pins"] = [pins[0]] + [pins[1]] * 201
    with pytest.raises(ValidationError):
        CompanyOperatingResourceGroup.model_validate(payload)
