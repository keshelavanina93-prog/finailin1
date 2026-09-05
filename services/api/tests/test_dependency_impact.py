"""Opt-in retained PostgreSQL acceptance for transitive review impact and policy."""

import json
import os
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4, uuid5

import psycopg
import pytest

from finai_api.domain.authority import ExactScope
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceMutation, ResourceProposal, ResourceReview
from finai_api.domain.review import Principal
from finai_api.services import dependency_impact, resources
from finai_api.services.workspace import WorkspaceError

pytestmark = pytest.mark.skipif(
    os.environ.get("G8_BINDING_DB_TEST") != "1", reason="Opt-in retained DB acceptance"
)


def proposal(
    operator: Principal, mutations: list[ResourceMutation], scope: str | None = None
) -> ResourceProposal:
    return ResourceProposal(
        title="SYNTHETIC downstream impact acceptance",
        rationale="Isolated non-authentic graph and governed promotion acceptance",
        access_entity=scope or operator.scope.legal_entity_id,
        mutations=mutations,
    )


def approve(reviewer: Principal, value: ResourceProposal) -> None:
    resources.review(
        reviewer,
        value.proposal_id,
        ResourceReview(
            decision="APPROVED", rationale="Independent synthetic dependency impact acceptance"
        ),
    )


@pytest.fixture
def graph() -> dict[str, Any]:
    tenant = UUID("805d8a32-d12b-4268-a236-b0b16e59da9f")
    scope = ExactScope(
        tenant_id=tenant,
        legal_entity_id="synthetic-impact-" + uuid4().hex,
        period="2026-08",
        currency="GEL",
    )
    operator = Principal(
        actor_id="synthetic-impact-proposer",
        display_name="Synthetic proposer",
        scope=scope,
        permissions=("ontology_read", "ontology_admin", "ontology_propose", "ontology_review"),
    )
    reviewer = operator.model_copy(update={"actor_id": "synthetic-impact-reviewer"})
    kind = "ImpactNode" + uuid4().hex[:10]
    schema = ResourceMutation(
        object_type="SchemaDefinition",
        identity_key=kind,
        display_name="SYNTHETIC graph schema",
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        attributes={
            "fields": {
                key: {
                    "field_id": str(uuid4()),
                    "semantic_id": str(
                        canonical_id(
                            tenant,
                            "SemanticContract",
                            "Identifier" if key == "code" else "CanonicalReference",
                        )
                    ),
                    "kind": "identifier" if key == "code" else "reference",
                    "required": key == "code",
                    "target_type": None if key == "code" else "*",
                }
                for key in ("code", "left", "right")
            },
            "additional_fields": False,
        },
        evidence_class="REFERENCE_TEMPLATE",
    )
    schema_proposal = proposal(operator, [schema], "__PLATFORM__")
    resources.propose(operator, schema_proposal)
    approve(reviewer, schema_proposal)
    ids = {key: uuid4() for key in ("A", "B", "C", "D")}
    attrs = {
        "A": {"code": "A"},
        "B": {"code": "B", "left": str(ids["A"])},
        "C": {"code": "C", "left": str(ids["A"])},
        "D": {"code": "D", "left": str(ids["B"]), "right": str(ids["C"])},
    }
    mutations = {
        key: ResourceMutation(
            resource_id=ids[key],
            object_type=kind,
            identity_key="synthetic:" + str(ids[key]),
            display_name="SYNTHETIC node " + key,
            attributes=values,
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            evidence_class="REFERENCE_TEMPLATE",
        )
        for key, values in attrs.items()
    }
    initial = proposal(operator, list(mutations.values()))
    proposed = resources.propose(operator, initial)
    # Proposed A -> B/C -> D is a benign diamond and must be retained before review.
    downstream = [
        item
        for item in proposed.validation["downstream_impact"]["affected"]
        if item["root_resource_id"] == str(ids["A"])
    ]
    assert {item["resource_id"] for item in downstream} == {
        str(ids[key]) for key in ("B", "C", "D")
    }
    assert all(item["state"] == "PROPOSED" for item in downstream)
    approve(reviewer, initial)
    versions = {key: uuid5(initial.proposal_id, str(identifier)) for key, identifier in ids.items()}
    update = mutations["A"].model_copy(
        update={"expected_version_id": versions["A"], "attributes": {"code": "A revised"}}
    )
    return {
        "operator": operator,
        "reviewer": reviewer,
        "ids": ids,
        "mutations": mutations,
        "versions": versions,
        "update": update,
        "kind": kind,
    }


def test_transitive_current_snapshot_detects_new_consumer_and_excludes_obsolete_edges(
    graph: dict[str, Any],
) -> None:
    operator, reviewer = graph["operator"], graph["reviewer"]
    pending = proposal(operator, [graph["update"]])
    detail = resources.propose(operator, pending)
    affected = detail.validation["downstream_impact"]["affected"]
    assert {row["resource_id"]: row["depth"] for row in affected} == {
        str(graph["ids"]["B"]): 1,
        str(graph["ids"]["C"]): 1,
        str(graph["ids"]["D"]): 2,
    }
    assert all(row["state"] == "CURRENT" for row in affected)
    extra = ResourceMutation(
        object_type=graph["kind"],
        identity_key="synthetic:" + uuid4().hex,
        display_name="SYNTHETIC new report consumer",
        attributes={"code": "E", "left": str(graph["ids"]["D"])},
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        evidence_class="REFERENCE_TEMPLATE",
    )
    added = proposal(operator, [extra])
    resources.propose(operator, added)
    approve(reviewer, added)
    with pytest.raises(WorkspaceError, match="Downstream dependency impact changed"):
        approve(reviewer, pending)
    assert resources.proposal_detail(operator, pending.proposal_id).decision is None
    refreshed = proposal(operator, [graph["update"]])
    revised = resources.propose(operator, refreshed)
    assert any(
        row["resource_id"] == str(extra.resource_id) and row["depth"] == 3
        for row in revised.validation["downstream_impact"]["affected"]
    )
    approve(reviewer, refreshed)
    # Remove B's live edge; immutable older B versions must not appear as current consumers.
    remove = graph["mutations"]["B"].model_copy(
        update={"expected_version_id": graph["versions"]["B"], "attributes": {"code": "B"}}
    )
    removed = proposal(operator, [remove])
    resources.propose(operator, removed)
    approve(reviewer, removed)
    latest_a = graph["update"].model_copy(
        update={"expected_version_id": uuid5(refreshed.proposal_id, str(graph["ids"]["A"]))}
    )
    snapshot = resources.propose(operator, proposal(operator, [latest_a])).validation[
        "downstream_impact"
    ]
    assert str(graph["ids"]["B"]) not in {row["resource_id"] for row in snapshot["affected"]}


def test_hidden_consumers_are_restricted_at_rest_and_require_steward(graph: dict[str, Any]) -> None:
    operator, reviewer = graph["operator"], graph["reviewer"]
    hidden = ResourceMutation(
        object_type=graph["kind"],
        identity_key="synthetic:" + uuid4().hex,
        display_name="SYNTHETIC PRIVATE CONSUMER " + uuid4().hex,
        attributes={"code": "private", "left": str(graph["ids"]["A"])},
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        evidence_class="REFERENCE_TEMPLATE",
    )
    hidden_proposal = proposal(operator, [hidden], "__TENANT__")
    resources.propose(operator, hidden_proposal)
    approve(reviewer, hidden_proposal)
    scoped = operator.model_copy(
        update={"permissions": ("ontology_read", "ontology_propose", "ontology_review")}
    )
    with pytest.raises(WorkspaceError, match="authorized tenant steward"):
        resources.propose(scoped, proposal(scoped, [graph["update"]]))
    pending = proposal(operator, [graph["update"]])
    admin_detail = resources.propose(operator, pending)
    assert any(
        row["resource_id"] == str(hidden.resource_id)
        for row in admin_detail.validation["downstream_impact"]["affected"]
    )
    redacted = resources.proposal_detail(scoped, pending.proposal_id).validation[
        "downstream_impact"
    ]
    assert redacted["status"] == "RESTRICTED" and redacted["affected"] == []
    with resources.resource_connection(scoped) as conn:
        payload = conn.execute(
            "SELECT payload FROM resource_proposals WHERE tenant_id=%s AND proposal_id=%s",
            (scoped.scope.tenant_id, pending.proposal_id),
        ).fetchone()[0]
        assert hidden.display_name not in json.dumps(payload)
        assert str(hidden.resource_id) not in json.dumps(payload)
        assert (
            conn.execute(
                "SELECT snapshot FROM proposal_impact_snapshots "
                "WHERE tenant_id=%s AND proposal_id=%s",
                (scoped.scope.tenant_id, pending.proposal_id),
            ).fetchone()
            is None
        )
    sentinel = scoped.model_copy(
        update={
            "scope": scoped.scope.model_copy(update={"legal_entity_id": "__TENANT_RESTRICTED__"})
        }
    )
    with resources.resource_connection(sentinel) as conn:
        assert (
            conn.execute(
                "SELECT snapshot FROM proposal_impact_snapshots "
                "WHERE tenant_id=%s AND proposal_id=%s",
                (sentinel.scope.tenant_id, pending.proposal_id),
            ).fetchone()
            is None
        )
    with (
        resources.resource_connection(scoped) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute("SELECT public.g8_has_hidden_current_dependents(%s)", (hidden.resource_id,))
    scoped_reviewer = reviewer.model_copy(update={"permissions": scoped.permissions})
    with pytest.raises(WorkspaceError, match="authorized tenant steward"):
        approve(scoped_reviewer, pending)
    approve(reviewer, pending)


def test_depth_size_and_real_cycle_fail_closed(
    graph: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    operator = graph["operator"]
    monkeypatch.setattr(dependency_impact, "MAX_DEPTH", 1)
    with pytest.raises(WorkspaceError, match="depth bound"):
        resources.propose(operator, proposal(operator, [graph["update"]]))
    monkeypatch.setattr(dependency_impact, "MAX_DEPTH", 16)
    monkeypatch.setattr(dependency_impact, "MAX_RESOURCES", 2)
    with pytest.raises(WorkspaceError, match="resource bound"):
        resources.propose(operator, proposal(operator, [graph["update"]]))
    monkeypatch.setattr(dependency_impact, "MAX_RESOURCES", 1000)
    cyclic = graph["update"].model_copy(
        update={"attributes": {"code": "A", "left": str(graph["ids"]["D"])}}
    )
    with pytest.raises(WorkspaceError, match="cycle"):
        resources.propose(operator, proposal(operator, [cyclic]))
