"""Retained ontology execution selects definition and data in the same as-of context."""

import json
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from finai_api.domain.authority import ExactScope
from finai_api.domain.ontology_definitions import DefinitionWrite
from finai_api.domain.resources import ResourceMutation, ResourceProposal, ResourceReview
from finai_api.domain.review import Principal
from finai_api.services import ontology_definitions as definitions
from finai_api.services import resources
from finai_api.services.workspace import WorkspaceError

JAN = datetime(2026, 1, 1, tzinfo=UTC)
DB = pytest.mark.skipif(
    os.environ.get("G8_BINDING_DB_TEST") != "1", reason="Opt-in retained DB acceptance"
)


@pytest.fixture
def retained():
    operator = Principal(
        actor_id="synthetic-definition-history-proposer",
        display_name="Synthetic history proposer",
        scope=ExactScope(
            tenant_id=UUID("805d8a32-d12b-4268-a236-b0b16e59da9f"),
            legal_entity_id="synthetic-definition-history-" + uuid4().hex,
            period="2026-08",
            currency="GEL",
        ),
        permissions=("ontology_read", "ontology_admin", "ontology_propose", "ontology_review"),
    )
    reviewer = operator.model_copy(update={"actor_id": "synthetic-definition-history-reviewer"})
    reader = operator.model_copy(update={"permissions": ("ontology_read",)})

    def publish(*items):
        proposal = ResourceProposal(
            title="SYNTHETIC retained definition history acceptance",
            rationale="Non-authentic isolated bitemporal definition execution acceptance",
            access_entity=operator.scope.legal_entity_id,
            mutations=list(items),
        )
        resources.propose(operator, proposal)
        resources.review(
            reviewer,
            proposal.proposal_id,
            ResourceReview(
                decision="APPROVED",
                rationale="Retain synthetic temporal definition acceptance",
            ),
        )
        return [resources.get_resource(reader, item.resource_id)["resource"] for item in items]

    return reader, publish


def item(kind, attributes, **changes):
    return ResourceMutation(
        object_type=kind,
        identity_key="synthetic:" + uuid4().hex,
        display_name="SYNTHETIC " + kind,
        attributes=attributes,
        valid_from=JAN,
        evidence_class="REFERENCE_TEMPLATE",
        **changes,
    )


@DB
@pytest.mark.parametrize("kind", ["ObjectTypeGroup", "ObjectSetDefinition"])
def test_corrected_definition_replays_original_known_state_and_explicit_pin(
    retained, kind, monkeypatch
):
    reader, publish = retained
    company = item("LegalEntity", {})
    chart = item(
        "LocalChartOfAccounts", {"code": "SYNTHETIC", "legal_entity_id": str(company.resource_id)}
    )
    publish(company, chart)

    def attributes(object_type):
        spec = (
            {"types": [object_type]} if kind == "ObjectTypeGroup" else {"object_type": object_type}
        )
        return {"definition": spec}

    original = item(kind, attributes("LegalEntity"))
    first = publish(original)[0]
    first_known = datetime.fromisoformat(first["system_from"])
    corrected = original.model_copy(
        update={
            "expected_version_id": UUID(first["version_id"]),
            "attributes": attributes("LocalChartOfAccounts"),
        }
    )
    second = publish(corrected)[0]
    assert second["system_from"] > first["system_from"]
    at = datetime.now(UTC)
    selected = definitions.definition(
        reader, original.resource_id, valid_at=JAN, known_at=first_known
    )
    assert str(selected["version_id"]) == first["version_id"]
    assert (
        str(definitions.definition(reader, original.resource_id)["version_id"])
        == second["version_id"]
    )
    assert (
        str(definitions.definition(reader, original.resource_id, valid_at=JAN)["version_id"])
        == second["version_id"]
    )

    def run(known_at, version=None):
        if kind == "ObjectTypeGroup":
            return definitions.run_group(
                reader, original.resource_id, 0, 10, version, JAN, known_at
            )
        return definitions.run_set(reader, original.resource_id, version, 0, 10, JAN, known_at)

    historic = run(first_known)
    current = run(at)
    pinned = run(at, UUID(first["version_id"]))
    for result, expected_version, expected_object in (
        (historic, first["version_id"], company.resource_id),
        (current, second["version_id"], chart.resource_id),
        (pinned, first["version_id"], company.resource_id),
    ):
        assert str(result["definition_version_id"]) == expected_version
        assert [obj["resource_id"] for obj in result["objects"]] == [str(expected_object)]
        assert result["query"]["valid_at"] == JAN.isoformat().replace("+00:00", "Z")

    from fastapi.testclient import TestClient

    from finai_api.config import get_settings
    from finai_api.main import app

    monkeypatch.setenv(
        "FINAI_ACCESS_TOKENS",
        json.dumps({"synthetic-history-token": reader.model_dump(mode="json")}),
    )
    get_settings.cache_clear()
    client = TestClient(app)
    headers = {"Authorization": "Bearer synthetic-history-token"}
    path = f"/v1/ontology/model/definitions/{original.resource_id}"
    params = {"valid_at": JAN.isoformat(), "known_at": first_known.isoformat()}
    response = client.get(path, params=params, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["version_id"] == first["version_id"]
    listing = client.get("/v1/ontology/model/definitions", params=params, headers=headers)
    assert listing.status_code == 200, listing.text
    assert any(row["version_id"] == first["version_id"] for row in listing.json())
    assert client.get(path, params=params).status_code == 401
    for route in (path, "/v1/ontology/model/definitions"):
        assert (
            client.get(
                route, params={"known_at": "2026-01-01T00:00:00"}, headers=headers
            ).status_code
            == 422
        )
    client.close()
    get_settings.cache_clear()

    other_company = reader.model_copy(
        update={
            "scope": reader.scope.model_copy(
                update={
                    "legal_entity_id": "synthetic-other-" + uuid4().hex,
                }
            )
        }
    )
    other_tenant = reader.model_copy(
        update={"scope": reader.scope.model_copy(update={"tenant_id": uuid4()})}
    )
    for unauthorized in (other_company, other_tenant):
        for version in (None, UUID(first["version_id"])):
            with pytest.raises(WorkspaceError) as exc:
                definitions.definition(
                    unauthorized, original.resource_id, version, valid_at=JAN, known_at=first_known
                )
            assert exc.value.status == 404


@DB
def test_future_effective_and_revoked_definitions_do_not_leak_into_asof_execution(retained):
    reader, publish = retained
    future = item("ObjectTypeGroup", {"definition": {"types": ["LegalEntity"]}}).model_copy(
        update={"valid_from": datetime.now(UTC) + timedelta(days=30)}
    )
    future_row = publish(future)[0]
    with pytest.raises(WorkspaceError) as exc:
        definitions.definition(reader, future.resource_id)
    assert exc.value.status == 404
    with pytest.raises(WorkspaceError) as exc:
        definitions.definition(reader, future.resource_id, valid_at=JAN)
    assert exc.value.status == 404
    # An explicit immutable version is a replay request, independent of the data's effective time.
    assert (
        str(
            definitions.definition(
                reader, future.resource_id, UUID(future_row["version_id"]), valid_at=JAN
            )["version_id"]
        )
        == future_row["version_id"]
    )
    original = item("ObjectTypeGroup", {"definition": {"types": ["LegalEntity"]}})
    first = publish(original)[0]
    revoked = original.model_copy(
        update={
            "expected_version_id": UUID(first["version_id"]),
            "authority_state": "REVOKED",
        }
    )
    publish(revoked)
    with pytest.raises(WorkspaceError) as exc:
        definitions.definition(reader, original.resource_id)
    assert exc.value.status == 404
    with pytest.raises(WorkspaceError) as exc:
        definitions.run_group(reader, original.resource_id, 0, 10, valid_at=JAN)
    assert exc.value.status == 404
    assert (
        str(
            definitions.definition(
                reader,
                original.resource_id,
                valid_at=JAN,
                known_at=datetime.fromisoformat(first["system_from"]),
            )["version_id"]
        )
        == first["version_id"]
    )


@DB
@pytest.mark.parametrize("kind", ["ObjectSetDefinition", "ObjectTypeGroup"])
def test_scheduled_successor_keeps_catalog_and_default_execution_on_current_version(retained, kind):
    reader, publish = retained
    company = item("LegalEntity", {})
    chart = item(
        "LocalChartOfAccounts", {"code": "SYNTHETIC", "legal_entity_id": str(company.resource_id)}
    )
    publish(company, chart)

    def attributes(object_type):
        return {"definition": (
            {"object_type": object_type} if kind == "ObjectSetDefinition"
            else {"types": [object_type]}
        )}

    original = item(kind, attributes("LegalEntity"))
    first = publish(original)[0]
    scheduled = original.model_copy(update={
        "expected_version_id": UUID(first["version_id"]),
        "valid_from": datetime.now(UTC) + timedelta(days=30),
        "attributes": attributes("LocalChartOfAccounts"),
    })
    future = publish(scheduled)[0]
    listed = next(row for row in definitions.definitions(reader)
                  if row["resource_id"] == original.resource_id)
    assert str(listed["version_id"]) == first["version_id"]

    def run(version=None):
        if kind == "ObjectSetDefinition":
            return definitions.run_set(reader, original.resource_id, version, 0, 10)
        return definitions.run_group(reader, original.resource_id, 0, 10, version)

    current = run()
    assert str(current["definition_version_id"]) == first["version_id"]
    assert [row["resource_id"] for row in current["objects"]] == [str(company.resource_id)]
    replay = run(UUID(future["version_id"]))
    assert str(replay["definition_version_id"]) == future["version_id"]
    assert [row["resource_id"] for row in replay["objects"]] == [str(chart.resource_id)]

    # A scheduled-only identity can still be edited. The execution resolver must
    # not be reused for editing, and CAS remains against the publication head.
    scheduled_only = item(kind, attributes("LegalEntity")).model_copy(update={
        "valid_from": datetime.now(UTC) + timedelta(days=30),
    })
    scheduled_only_head = publish(scheduled_only)[0]
    write = DefinitionWrite(
        resource_id=scheduled_only.resource_id,
        expected_version_id=UUID(scheduled_only_head["version_id"]),
        kind=kind, key=scheduled_only.identity_key, name="Edited scheduled synthetic definition",
        rationale="Editing remains independent of current effective execution",
        attributes=attributes("LegalEntity"),
    )
    prepared = definitions.prepare_definition(reader, write)
    assert prepared.mutations[0].expected_version_id == UUID(scheduled_only_head["version_id"])
    assert prepared.access_entity == reader.scope.legal_entity_id
    author = reader.model_copy(update={"permissions": (
        "ontology_read", "ontology_admin", "ontology_propose", "ontology_review",
    )})
    stale = write.model_copy(update={
        "resource_id": original.resource_id,
        "expected_version_id": UUID(first["version_id"]), "key": original.identity_key,
    })
    with pytest.raises(WorkspaceError, match="accepted version changed"):
        definitions.propose_definition(author, stale)


def test_naive_definition_times_rejected_before_database_access():
    for argument in ("valid_at", "known_at"):
        with pytest.raises(WorkspaceError, match="timezone") as exc:
            definitions.definition(None, uuid4(), **{argument: datetime(2026, 1, 1)})
        assert exc.value.status == 422
