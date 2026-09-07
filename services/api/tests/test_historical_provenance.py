"""Historical evidence never substitutes for an independently active dependency."""
# ruff: noqa: F811

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from psycopg.rows import dict_row
from test_definition_history import DB, item, retained  # noqa: F401

from finai_api.domain.resources import ResourceProposal, ResourceReview
from finai_api.services import resources
from finai_api.services.upstream_authority import upstream_authority
from finai_api.services.workspace import WorkspaceError


@DB
def test_historical_successor_active_diamond_and_withdrawal(retained):
    reader, publish = retained
    author = reader.model_copy(
        update={"permissions": ("ontology_read", "ontology_propose", "ontology_review")}
    )
    reviewer = author.model_copy(update={"actor_id": "synthetic-provenance-reviewer"})
    leaf = item("LegalEntity", {})
    leaf_row = publish(leaf)[0]
    source = item(
        "LocalChartOfAccounts", {"legal_entity_id": str(leaf.resource_id), "code": "SYNTHETIC"}
    )
    source_row = publish(source)[0]

    def bound(mutation):
        proposal = ResourceProposal(
            title="SYNTHETIC historical provenance",
            rationale="Synthetic exact historical versus active dependency verification",
            access_entity=reader.scope.legal_entity_id,
            mutations=[mutation],
            source_versions={
                mutation.resource_id: {source.resource_id: UUID(source_row["version_id"])}
            },
        )
        resources.propose(author, proposal)
        resources.review(
            reviewer,
            proposal.proposal_id,
            ResourceReview(
                decision="APPROVED",
                rationale="Independent synthetic historical lineage verification",
            ),
        )
        return resources.get_resource(reader, mutation.resource_id)["resource"]

    historical = bound(item("LegalEntity", {}))
    mixed = bound(
        item("LocalChartOfAccounts", {"legal_entity_id": str(leaf.resource_id), "code": "MIXED"})
    )

    def check(row, opt=False, principal=reader):
        with (
            resources.resource_connection(principal) as conn,
            conn.cursor(row_factory=dict_row) as cursor,
        ):
            return upstream_authority(
                cursor,
                principal.scope.tenant_id,
                UUID(row["version_id"]),
                allow_historical_provenance=opt,
            )

    legacy = check(historical)
    assert legacy and all("lineage_use" not in p for p in legacy)
    opted = check(mixed, True)
    assert len({p["version_id"] for p in opted}) == len(opted)
    assert (
        next(p for p in opted if p["version_id"] == leaf_row["version_id"])["lineage_use"]
        == "ACTIVE"
    )
    corrected = leaf.model_copy(
        update={
            "expected_version_id": UUID(leaf_row["version_id"]),
            "display_name": "SYNTHETIC reviewed successor",
        }
    )
    current = publish(corrected)[0]
    with pytest.raises(WorkspaceError, match="current use"):
        check(historical)
    selected = check(historical, True)
    assert (
        next(p for p in selected if p["version_id"] == leaf_row["version_id"])["lineage_use"]
        == "HISTORICAL"
    )
    assert all(p["version_id"] != current["version_id"] for p in selected)
    with pytest.raises(WorkspaceError, match="current use"):
        check(mixed, True)
    hidden = reader.model_copy(
        update={
            "scope": reader.scope.model_copy(
                update={"legal_entity_id": "synthetic-inaccessible-provenance"}
            )
        }
    )
    # Call from a visible subject is enforced by callers; explicit hidden target lookup fails.
    with resources.resource_connection(hidden) as conn, conn.cursor(row_factory=dict_row) as cursor:
        from finai_api.services.effective_version import retained_with_effective_version

        assert (
            retained_with_effective_version(
                cursor,
                reader.scope.tenant_id,
                leaf.resource_id,
                UUID(leaf_row["version_id"]),
                datetime.now(UTC),
            )
            is None
        )
    revoked = corrected.model_copy(
        update={"expected_version_id": UUID(current["version_id"]), "authority_state": "REVOKED"}
    )
    publish(revoked)
    with pytest.raises(WorkspaceError, match="withdrawn"):
        check(historical, True)


@pytest.mark.parametrize(
    "state,availability",
    [("REVOKED", "AVAILABLE"), ("SUPERSEDED", "AVAILABLE"), ("OBSERVED", "UNAVAILABLE")],
)
def test_historical_pinned_lifecycle_withdrawal_remains_denied(monkeypatch, state, availability):
    from finai_api.services import upstream_authority as module

    consumer, version, resource = uuid4(), uuid4(), uuid4()

    class Cursor:
        def execute(self, sql, params):
            self.sql = sql
            return self

        def fetchall(self):
            return [
                {
                    "target_resource_id": resource,
                    "target_version_id": version,
                    "relation": "BOUND_SOURCE:" + str(resource),
                }
            ]

        def fetchone(self):
            if "authority_state FROM resource_versions" in self.sql:
                return {"authority_state": "APPROVED"}
            return {
                "event_id": uuid4(),
                "payload": {"target_state": state, "availability_state": availability},
            }

    monkeypatch.setattr(
        module,
        "retained_with_effective_version",
        lambda *_: {"authority_state": "APPROVED", "effective_version_id": uuid4()},
    )
    with pytest.raises(WorkspaceError, match="withdrawn"):
        upstream_authority(Cursor(), uuid4(), consumer, allow_historical_provenance=True)
