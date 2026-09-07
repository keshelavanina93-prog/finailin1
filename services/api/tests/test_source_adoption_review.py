"""Synthetic server governance checks, not authentic later-source acceptance."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_source_adoption_contract import baseline as baseline
from test_source_adoption_contract import later, pin

from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.domain.source_adoption import (
    AdoptionDefinition,
    SourceAdoptionSelection,
    SourceFamilySelection,
)
from finai_api.services import resource_lifecycle, source_adoption
from finai_api.services.workspace import WorkspaceError


class Connection:
    conflict = None
    hidden = False

    def __init__(self):
        self.queries = []

    def cursor(self, **_):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, params):
        self.queries.append((query, params))
        return self

    def fetchone(self):
        if "g8_has_hidden_current_dependents" in self.queries[-1][0]:
            return None if self.hidden is None else {"hidden": self.hidden}
        return self.conflict


def reference(value):
    return VersionReference(resource_id=value.resource_id, version_id=value.version_id)


@pytest.fixture
def review(monkeypatch, baseline):
    conn = Connection()
    principal = SimpleNamespace(scope=SimpleNamespace(tenant_id=str(uuid4())))
    successor = later(baseline)
    snapshots = {str(item.binding.resource_id): item for item in (baseline, successor)}
    rows = {}

    def retain(ref, kind, attributes=None):
        row = {
            **ref.model_dump(mode="json"),
            "object_type": kind,
            "attributes": attributes or {},
            "evidence_class": "USER_ASSERTED",
            "system_from": datetime.now(UTC) - timedelta(days=1),
            "access_entity": "entity-A",
        }
        rows[str(ref.resource_id)] = row
        return row

    for snapshot in snapshots.values():
        retain(snapshot.binding, "SourceAccountingBinding")
    retain(baseline.company, "LegalEntity")
    monkeypatch.setattr(source_adoption, "_version", lambda _c, _p, ref: rows[str(ref.resource_id)])
    monkeypatch.setattr(source_adoption, "_latest", lambda *_: None)
    monkeypatch.setattr(source_adoption, "upstream_authority", lambda *_: None)
    monkeypatch.setattr(source_adoption, "validate_current_binding", lambda *_: None)
    monkeypatch.setattr(
        source_adoption, "derive_snapshot", lambda _p, row, _r: snapshots[str(row["resource_id"])]
    )
    resolver = source_adoption.Resolver(conn, principal, rows.__getitem__)
    family_selection = SourceFamilySelection(
        family_key="seg-base",
        source_system="1C-accounting",
        display_name="SEG Base source",
        baseline_binding=reference(baseline.binding),
        rationale="Review exact retained baseline",
    )
    family_content = source_adoption.family_content(principal, family_selection, resolver)
    family_pin = pin().model_copy(update={"resource_id": family_content[0]})
    family = retain(family_pin, "SourceFamily", family_content[3])
    selection = SourceAdoptionSelection(
        family=reference(family_pin),
        predecessor_binding=reference(baseline.binding),
        successor_binding=reference(successor.binding),
        policy="DISJOINT_PERIOD_ADDITION",
        rationale="Review explicit later disjoint period",
    )
    content = source_adoption.adoption_content(principal, selection, resolver)

    def mutation(content, kind="SourceSnapshotAdoption"):
        return ResourceMutation(
            resource_id=content[0],
            identity_key=content[1],
            display_name=content[2],
            attributes=deepcopy(content[3]),
            object_type=kind,
            evidence_class="USER_ASSERTED",
            valid_from=datetime.now(UTC),
        )

    return SimpleNamespace(
        conn=conn,
        principal=principal,
        rows=rows,
        snapshots=snapshots,
        baseline=baseline,
        successor=successor,
        family=family,
        family_pin=family_pin,
        selection=selection,
        resolver=resolver,
        item=mutation(content),
        family_item=mutation(family_content, "SourceFamily"),
        retain=retain,
        mutation=mutation,
        validate=lambda item, previous=None: source_adoption.validate(
            conn, principal, item, lambda identity, *_: rows[identity], previous
        ),
    )


def test_generic_review_accepts_only_rederived_contract_and_preserves_original(review):
    before = deepcopy(review.item.attributes)
    review.validate(review.family_item)
    review.validate(review.item)
    assert review.item.attributes == before
    assert before["definition"]["predecessor"]["missing_amount_coordinates"] == ["Base!S288"]
    assert (
        before["definition"]["successor"]["period"] != before["definition"]["predecessor"]["period"]
    )
    assert "total" not in before
    assert review.conn.queries


@pytest.mark.parametrize("kind", ["family", "adoption"])
@pytest.mark.parametrize("change", ["hash", "schema", "count", "missing", "meaning", "snapshot"])
def test_generic_proposal_rejects_fabricated_observation(review, kind, change):
    item = review.family_item if kind == "family" else review.item
    observed = item.attributes["definition"]["baseline" if kind == "family" else "successor"]
    if change == "hash":
        observed["source_sha256"] = "f" * 64
    elif change == "schema":
        observed["schema_sha256"] = "f" * 64
    elif change == "count":
        observed["source_rows"] += 1
    elif change == "missing":
        observed.update(missing_amount_count=1, missing_amount_coordinates=["Base!S999"])
    elif change == "meaning":
        observed["meaning"]["amount_field"] = "annotated_amount"
    else:
        observed["document_id"] = "invented-source"
    with pytest.raises(WorkspaceError, match="differs from retained bytes"):
        review.validate(item)


def test_nonbaseline_predecessor_needs_reviewed_membership(review):
    next_snapshot = later(review.successor)
    review.snapshots[str(next_snapshot.binding.resource_id)] = next_snapshot
    review.retain(next_snapshot.binding, "SourceAccountingBinding")
    selection = review.selection.model_copy(
        update={
            "predecessor_binding": reference(review.successor.binding),
            "successor_binding": reference(next_snapshot.binding),
        }
    )
    with pytest.raises(WorkspaceError, match="non-baseline predecessor"):
        source_adoption.adoption_content(review.principal, selection, review.resolver)


@pytest.mark.parametrize("change", ["family", "successor"])
def test_predecessor_adoption_requires_exact_family_and_successor_membership(review, change):
    prior = AdoptionDefinition.model_validate(review.item.attributes["definition"])
    prior = prior.model_copy(
        update={
            "family": pin() if change == "family" else prior.family,
            "successor": review.baseline if change == "successor" else prior.successor,
        }
    )
    prior_pin = pin()
    review.retain(
        prior_pin, "SourceSnapshotAdoption", {"definition": prior.model_dump(mode="json")}
    )
    selection = review.selection.model_copy(
        update={
            "predecessor_binding": reference(review.successor.binding),
            "predecessor_adoption": reference(prior_pin),
        }
    )
    with pytest.raises(WorkspaceError, match="exact member"):
        source_adoption.adoption_content(review.principal, selection, review.resolver)


def test_competing_successor_checked_in_generic_validation(review):
    review.conn.conflict = {"resource_id": str(uuid4())}
    with pytest.raises(WorkspaceError, match="already has a reviewed successor"):
        review.validate(review.item)
    query, args = review.conn.queries[-1]
    assert "predecessor_binding_id" in query and "successor_binding_id" in query
    assert args[2:] == (
        review.item.attributes["family_id"],
        review.item.attributes["predecessor_binding_id"],
        review.item.attributes["successor_binding_id"],
    )


def test_read_successor_has_no_aggregation_or_old_period_inheritance(monkeypatch, review):
    adoption_pin = pin().model_copy(update={"resource_id": review.item.resource_id})
    review.retain(adoption_pin, "SourceSnapshotAdoption", review.item.attributes)
    monkeypatch.setattr(
        source_adoption.resources, "resource_connection", lambda *_a, **_k: review.conn
    )
    monkeypatch.setattr(
        source_adoption.resources, "_get", lambda _c, _t, key: review.rows[str(key)]
    )
    result = source_adoption.read_successor(review.principal, reference(adoption_pin))
    assert result["accounting_aggregation_authorized"] is False
    assert result["source"] == review.successor.model_dump(mode="json")
    assert result["source"]["period"] != review.baseline.period.model_dump(mode="json")
    assert review.baseline.missing_amount_coordinates == ["Base!S288"]


@pytest.mark.parametrize("change", ["withdrawn", "unavailable", "stale", "coproposed", "upstream"])
def test_resolver_refuses_invalid_dependencies(monkeypatch, review, change):
    ref = reference(review.baseline.binding)
    row = review.rows[str(ref.resource_id)]
    if change == "withdrawn":
        monkeypatch.setattr(
            source_adoption,
            "_latest",
            lambda *_: {"payload": {"target_state": "REVOKED", "availability_state": "AVAILABLE"}},
        )
    elif change == "unavailable":
        monkeypatch.setattr(
            source_adoption,
            "_latest",
            lambda *_: {
                "payload": {"target_state": "APPROVED", "availability_state": "UNAVAILABLE"}
            },
        )
    elif change == "stale":
        ref = ref.model_copy(update={"version_id": uuid4()})
    elif change == "coproposed":
        del row["system_from"]
    else:

        def unavailable(*_):
            raise WorkspaceError(409, "Upstream authority withdrawn")

        monkeypatch.setattr(source_adoption, "upstream_authority", unavailable)
    resolver = source_adoption.Resolver(review.conn, review.principal, review.rows.__getitem__)
    with pytest.raises(WorkspaceError):
        resolver.exact(ref, "SourceAccountingBinding")


@pytest.mark.parametrize("change", ["future", "expired", "superseded"])
def test_real_temporal_version_gate_is_used(monkeypatch, review, change):
    ref = reference(review.baseline.binding)
    row = deepcopy(review.rows[str(ref.resource_id)])
    now = datetime.now(UTC)
    row.update(
        effective_version_id=ref.version_id,
        authority_state="APPROVED",
        valid_from=now - timedelta(days=1),
        valid_to=None,
    )
    if change == "future":
        row["valid_from"] = now + timedelta(days=1)
    elif change == "expired":
        row["valid_to"] = now - timedelta(seconds=1)
    else:
        row["effective_version_id"] = uuid4()
    monkeypatch.setattr(resource_lifecycle, "retained_with_effective_version", lambda *_: row)
    monkeypatch.setattr(source_adoption, "_version", resource_lifecycle._version)
    resolver = source_adoption.Resolver(review.conn, review.principal, review.rows.__getitem__)
    with pytest.raises(WorkspaceError, match="eligible for current use"):
        resolver.exact(ref, "SourceAccountingBinding")


def test_adoption_is_immutable_and_withdrawal_keeps_original_contract(review):
    previous = {
        "attributes": deepcopy(review.item.attributes),
        "display_name": review.item.display_name,
    }
    with pytest.raises(WorkspaceError, match="immutable"):
        review.validate(review.item, previous)
    withdrawn = review.item.model_copy(update={"authority_state": "REVOKED"})
    review.validate(withdrawn, previous)
    withdrawn.attributes["definition"]["successor"]["source_rows"] += 1
    with pytest.raises(WorkspaceError, match="preserve the original"):
        review.validate(withdrawn, previous)


@pytest.mark.parametrize("kind", ["family", "adoption"])
@pytest.mark.parametrize("policy", ["entity-A", "entity-B", "__TENANT__"])
def test_generic_review_keeps_company_and_family_access_policy(review, kind, policy):
    item = review.family_item if kind == "family" else review.item

    def validate():
        source_adoption.validate(
            review.conn,
            review.principal,
            item,
            lambda identity, *_: review.rows[identity],
            None,
            access_entity=policy,
        )

    if policy == "entity-A":
        validate()
    else:
        with pytest.raises(WorkspaceError, match="exact company/family access boundary"):
            validate()


@pytest.mark.parametrize("hidden", [True, None])
def test_hidden_or_unknown_membership_refuses_without_exposing_hidden_ids(review, hidden):
    review.conn.hidden = hidden
    review.conn.queries.clear()
    with pytest.raises(WorkspaceError) as caught:
        review.validate(review.item)
    assert (
        caught.value.detail == "Recurring-source membership is incomplete in the authorized context"
    )
    assert len(review.conn.queries) == 1
    query, args = review.conn.queries[0]
    assert "g8_has_hidden_current_dependents" in query
    assert str(args[0]) == review.item.attributes["family_id"]
    assert review.item.attributes["family_id"] not in caught.value.detail


def test_same_policy_field_restriction_blocks_before_visible_conflict_lookup(review):
    assert review.family["access_entity"] == "entity-A"
    review.conn.hidden = True
    review.conn.conflict = None  # Caller-visible list contains no adoption.
    review.conn.queries.clear()
    with pytest.raises(WorkspaceError, match="membership is incomplete"):
        source_adoption.validate(
            review.conn,
            review.principal,
            review.item,
            lambda identity, *_: review.rows[identity],
            None,
            access_entity="entity-A",
        )
    assert all("resource_heads" not in query for query, _ in review.conn.queries)


def test_two_transitions_in_one_generic_proposal_refused_before_publication(review):
    principal = SimpleNamespace(
        scope=SimpleNamespace(
            tenant_id=review.principal.scope.tenant_id, legal_entity_id="entity-A"
        ),
        permissions=("ontology_propose",),
    )
    proposal = ResourceProposal(
        title="Synthetic competing source transitions",
        rationale="Must refuse parallel successors",
        access_entity="entity-A",
        mutations=[review.item, review.item.model_copy(update={"resource_id": uuid4()})],
    )
    review.conn.queries.clear()
    with pytest.raises(WorkspaceError, match="one recurring-source transition"):
        source_adoption.resources._validate(review.conn, principal, proposal)
    assert review.conn.queries == []
