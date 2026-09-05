"""Native PostgreSQL acceptance of historical, version-pinned upstream lineage."""

import json
import os
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from finai_api.config import get_settings
from finai_api.domain.authority import ExactScope
from finai_api.domain.resources import (
    CanonicalResource,
    ResourceMutation,
    ResourceProposal,
    ResourceReview,
)
from finai_api.domain.review import Principal
from finai_api.main import app
from finai_api.services import historical_graph as history
from finai_api.services import resources
from finai_api.services.workspace import WorkspaceError

pytestmark = pytest.mark.skipif(
    os.environ.get("G8_BINDING_DB_TEST") != "1", reason="Opt-in retained PostgreSQL acceptance"
)


@pytest.fixture
def principals() -> tuple[Principal, Principal]:
    proposer = Principal(
        actor_id="synthetic-lineage-proposer",
        display_name="Synthetic lineage proposer",
        scope=ExactScope(
            tenant_id=UUID("805d8a32-d12b-4268-a236-b0b16e59da9f"),
            legal_entity_id="synthetic-lineage-" + uuid4().hex,
            period="2026-08",
            currency="GEL",
        ),
        permissions=("ontology_read", "ontology_admin", "ontology_propose", "ontology_review"),
    )
    return proposer, proposer.model_copy(update={"actor_id": "synthetic-lineage-reviewer"})


def node(kind: str, name: str, attributes: dict[str, Any]) -> ResourceMutation:
    return ResourceMutation(
        object_type=kind,
        identity_key="synthetic:" + uuid4().hex,
        display_name="SYNTHETIC " + name,
        attributes=attributes,
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        evidence_class="REFERENCE_TEMPLATE",
    )


def accept(
    principals: tuple[Principal, Principal],
    mutations: list[ResourceMutation],
    policy: str | None = None,
) -> list[CanonicalResource]:
    proposer, reviewer = principals
    value = ResourceProposal(
        title="SYNTHETIC historical lineage acceptance",
        rationale="Isolated non-authentic version-pinned dependency acceptance",
        access_entity=policy or proposer.scope.legal_entity_id,
        mutations=mutations,
    )
    resources.propose(proposer, value)
    resources.review(
        reviewer,
        value.proposal_id,
        ResourceReview(
            decision="APPROVED", rationale="Independent synthetic historical lineage review"
        ),
    )
    return [
        CanonicalResource.model_validate(
            resources.get_resource(proposer, item.resource_id)["resource"]
        )
        for item in mutations
    ]


def test_asof_root_and_exact_old_dependencies_survive_correction_and_revocation(
    principals: tuple[Principal, Principal],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proposer, _ = principals
    entity_mutation = node("LegalEntity", "original company", {})
    entity = accept(principals, [entity_mutation])[0]
    chart = accept(
        principals,
        [
            node(
                "LocalChartOfAccounts",
                "chart",
                {"legal_entity_id": str(entity.resource_id), "code": "SYNTHETIC"},
            )
        ],
    )[0]
    account_mutation = node(
        "LocalAccount",
        "original account",
        {"chart_id": str(chart.resource_id), "account_code": "001"},
    )
    account = accept(principals, [account_mutation])[0]
    effective = datetime(2026, 8, 15, tzinfo=UTC)
    original = history.historical_graph(
        proposer, account.resource_id, valid_at=effective, known_at=account.system_from
    )
    assert original["root_version_id"] == str(account.version_id)
    assert str(entity.version_id) in {row["version_id"] for row in original["nodes"]}
    corrected_entity = accept(
        principals,
        [
            entity_mutation.model_copy(
                update={
                    "expected_version_id": entity.version_id,
                    "display_name": "SYNTHETIC corrected company",
                    "valid_from": datetime(2025, 12, 1, tzinfo=UTC),
                }
            )
        ],
    )[0]
    revoked_entity = accept(
        principals,
        [
            entity_mutation.model_copy(
                update={
                    "expected_version_id": corrected_entity.version_id,
                    "authority_state": "REVOKED",
                }
            )
        ],
    )[0]
    corrected = accept(
        principals,
        [
            account_mutation.model_copy(
                update={
                    "expected_version_id": account.version_id,
                    "display_name": "SYNTHETIC backdated account correction",
                    "valid_from": datetime(2026, 7, 1, tzinfo=UTC),
                }
            )
        ],
    )[0]
    after = history.historical_graph(
        proposer, account.resource_id, valid_at=effective, known_at=corrected.system_from
    )
    assert after["root_version_id"] == str(corrected.version_id)
    versions = {row["version_id"] for row in after["nodes"]}
    assert str(entity.version_id) in versions
    assert (
        str(corrected_entity.version_id) not in versions
        and str(revoked_entity.version_id) not in versions
    )
    assert all(
        edge["source_version_id"] in versions and edge["target_version_id"] in versions
        for edge in after["edges"]
    )
    assert original == history.historical_graph(
        proposer, account.resource_id, valid_at=effective, known_at=account.system_from
    )
    # Revocation is visible as recorded history; this endpoint does not grant action authority.
    revoked_account = accept(
        principals,
        [
            account_mutation.model_copy(
                update={"expected_version_id": corrected.version_id, "authority_state": "REVOKED"}
            )
        ],
    )[0]
    revoked_graph = history.historical_graph(
        proposer, account.resource_id, valid_at=effective, known_at=revoked_account.system_from
    )
    assert (
        next(
            row
            for row in revoked_graph["nodes"]
            if row["version_id"] == str(revoked_account.version_id)
        )["authority_state"]
        == "REVOKED"
    )
    assert revoked_graph["purpose"] == "HISTORICAL_LINEAGE"
    outsider = proposer.model_copy(
        update={
            "permissions": ("ontology_read",),
            "scope": proposer.scope.model_copy(update={"legal_entity_id": "unrelated-company"}),
        }
    )
    monkeypatch.setenv(
        "FINAI_ACCESS_TOKENS",
        json.dumps(
            {
                "reader": proposer.model_dump(mode="json"),
                "outsider": outsider.model_dump(mode="json"),
            }
        ),
    )
    get_settings.cache_clear()
    client = TestClient(app, headers={"Authorization": "Bearer reader"})
    path = f"/v1/ontology/resources/{account.resource_id}/graph"
    assert client.get(
        path,
        params={"valid_at": effective.isoformat(), "known_at": corrected.system_from.isoformat()},
    ).json()["root_version_id"] == str(corrected.version_id)
    assert client.get(path, params={"valid_at": "2026-08-15T00:00:00"}).status_code == 422
    assert TestClient(app).get(path).status_code == 401
    blocked = TestClient(app, headers={"Authorization": "Bearer outsider"}).get(path)
    assert blocked.status_code == 404 and "SYNTHETIC" not in blocked.text
    monkeypatch.setattr(history, "MAX_DEPTH", 0)
    with pytest.raises(WorkspaceError, match="bound"):
        history.historical_graph(proposer, account.resource_id)
    monkeypatch.setattr(history, "MAX_DEPTH", 16)
    monkeypatch.setattr(history, "MAX_NODES", 1)
    with pytest.raises(WorkspaceError, match="bound"):
        history.historical_graph(proposer, account.resource_id)
    monkeypatch.setattr(history, "MAX_NODES", 1000)
    monkeypatch.setattr(history, "MAX_EDGES", 1)
    with pytest.raises(WorkspaceError, match="edge bound"):
        history.historical_graph(proposer, account.resource_id)


def test_hidden_root_or_pinned_dependency_refuses_incomplete_graph(
    principals: tuple[Principal, Principal],
) -> None:
    proposer, _ = principals
    hidden = accept(principals, [node("LegalEntity", "PRIVATE COMPANY NAME", {})])[0]
    shared = accept(
        principals,
        [
            node(
                "LocalChartOfAccounts",
                "tenant chart",
                {"legal_entity_id": str(hidden.resource_id), "code": "SYNTHETIC"},
            )
        ],
        "__TENANT__",
    )[0]
    outsider = proposer.model_copy(
        update={
            "permissions": ("ontology_read",),
            "scope": proposer.scope.model_copy(update={"legal_entity_id": "unrelated-company"}),
        }
    )
    with pytest.raises(WorkspaceError) as absent:
        history.historical_graph(outsider, hidden.resource_id)
    assert absent.value.status == 404
    tenant_only = outsider.model_copy(
        update={"scope": outsider.scope.model_copy(update={"legal_entity_id": "__TENANT__"})}
    )
    with pytest.raises(WorkspaceError) as incomplete:
        history.historical_graph(tenant_only, shared.resource_id)
    assert incomplete.value.status == 404 and "PRIVATE" not in incomplete.value.detail


def test_intra_proposal_later_recording_pin_refuses_future_knowledge(
    principals: tuple[Principal, Principal],
) -> None:
    # Registry currently timestamps rows individually even though proposal acceptance is atomic.
    entity = node("LegalEntity", "later recorded dependency", {})
    chart = node(
        "LocalChartOfAccounts",
        "earlier recorded root",
        {"legal_entity_id": str(entity.resource_id), "code": "SYNTHETIC"},
    )
    recorded_chart, recorded_entity = accept(principals, [chart, entity])
    assert recorded_chart.system_from < recorded_entity.system_from
    with pytest.raises(WorkspaceError, match="not yet recorded"):
        history.historical_graph(
            principals[0],
            chart.resource_id,
            valid_at=datetime(2026, 8, 15, tzinfo=UTC),
            known_at=recorded_chart.system_from,
        )
    complete = history.historical_graph(
        principals[0],
        chart.resource_id,
        valid_at=datetime(2026, 8, 15, tzinfo=UTC),
        known_at=recorded_entity.system_from,
    )
    assert str(recorded_entity.version_id) in {row["version_id"] for row in complete["nodes"]}
