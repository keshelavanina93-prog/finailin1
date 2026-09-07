"""Rollback-only native proof of complete bootstrap pins and current-authority refusal."""

import argparse
import importlib.util
import json
import os
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg
from finai_api.domain.authority import ExactScope
from finai_api.domain.ontology_catalog import canonical_id, platform_definitions
from finai_api.domain.resource_lifecycle import (
    LifecycleRequest,
    LifecycleReview,
    VersionReference,
)
from finai_api.domain.resources import (
    ResourceMutation,
    ResourceProposal,
    ResourceReview,
)
from finai_api.domain.review import Principal
from finai_api.services import resource_lifecycle, resources
from psycopg.conninfo import conninfo_to_dict


def snapshot(conn, tenant):
    """Read complete retained rows, not just counts that could hide a rewritten head."""
    return {
        table: conn.execute(
            f"SELECT to_jsonb(t) FROM {table} t WHERE tenant_id=%s ORDER BY to_jsonb(t)::text",
            (tenant,),
        ).fetchall()
        for table in (
            "canonical_identities",
            "resource_versions",
            "resource_heads",
            "resource_dependencies",
            "resource_proposals",
            "resource_decisions",
            "resource_lifecycle_requests",
            "resource_lifecycle_decisions",
            "resource_lifecycle_events",
        )
    }


@contextmanager
def reviewed_fixture(conn, tenant):
    """Run the actual canonical review services in this rollback-only connection.

    Only connection ownership is adapted; validation, independent review, SQL
    constraints and current-authority services are not replaced.
    """
    author = Principal(
        actor_id="synthetic-bootstrap-author",
        display_name="SYNTHETIC bootstrap author",
        scope=ExactScope(
            tenant_id=tenant,
            legal_entity_id="synthetic-bootstrap",
            period="2026-09",
            currency="GEL",
        ),
        permissions=(
            "ontology_read",
            "ontology_admin",
            "ontology_propose",
            "ontology_review",
        ),
    )
    reviewer = author.model_copy(update={"actor_id": "synthetic-bootstrap-reviewer"})

    @contextmanager
    def connection(principal, **options):
        with conn.transaction():
            conn.execute(
                "SELECT set_config('finai.tenant_id',%s,true),"
                "set_config('finai.entity_id',%s,true),set_config('finai.tenant_access','true',true),"
                "set_config('finai.read_permissions',%s,true)",
                (
                    str(principal.scope.tenant_id),
                    principal.scope.legal_entity_id,
                    json.dumps(principal.permissions),
                ),
            )
            yield conn

    with (
        patch.object(resources, "resource_connection", connection),
        patch.object(resource_lifecycle, "resource_connection", connection),
    ):
        yield author, reviewer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output.drive.upper() != "D:":
        raise ValueError("Verification evidence must stay on D:")
    database = conninfo_to_dict(os.environ["FINAI_MIGRATION_DATABASE_URL"])
    if (
        database.get("host") not in ("127.0.0.1", "localhost")
        or database.get("port") != "55441"
    ):
        raise ValueError(
            "This proof requires the isolated CI PostgreSQL on loopback port 55441"
        )
    spec = importlib.util.spec_from_file_location(
        "g8_platform_installer", Path(__file__).with_name("install-ontology.py")
    )
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    tenant, rejected_tenant = uuid4(), uuid4()
    definitions = platform_definitions(tenant)
    schemas = [d for d in definitions if d["object_type"] == "SchemaDefinition"]
    semantic_count = sum(d["object_type"] == "SemanticContract" for d in definitions)
    expected_edges = sum(len(d["attributes"]["fields"]) for d in schemas)
    assert (len(definitions), len(schemas), semantic_count, expected_edges) == (
        142,
        96,
        18,
        438,
    )
    original_schema = next(d for d in schemas if d["identity_key"] == "LocalAccount")
    semantic_id = canonical_id(tenant, "SemanticContract", "AccountCode")
    semantic_version = installer.seed_version(semantic_id)
    semantic_ref = VersionReference(
        resource_id=semantic_id, version_id=semantic_version
    )

    def new_schema():
        return {
            "object_type": "SchemaDefinition",
            "identity_key": "BootstrapVerification" + uuid4().hex,
            "display_name": "SYNTHETIC rollback-only semantic consumer",
            "attributes": {
                "additional_fields": False,
                "fields": {
                    "code": deepcopy(
                        original_schema["attributes"]["fields"]["account_code"]
                    ),
                },
            },
        }

    refused = []
    with psycopg.connect(os.environ["FINAI_MIGRATION_DATABASE_URL"]) as conn:
        data_directory = str(conn.execute("SHOW data_directory").fetchone()[0])
        assert data_directory.upper().startswith("D:")
        try:
            first = installer.install(conn, tenant, definitions)
            assert len(first["created_identities"]) == 142
            assert first["exact_semantic_edges_created"] == 438
            conn.execute("SET CONSTRAINTS ALL IMMEDIATE")
            rows = conn.execute(
                "SELECT d.relation,s.attributes->'fields'->substring(d.relation from 10)->>'kind',"
                "v.attributes->>'kind',d.target_resource_id,d.target_version_id "
                "FROM resource_dependencies d JOIN resource_versions s "
                "ON s.tenant_id=d.tenant_id AND s.version_id=d.version_id "
                "JOIN resource_versions v ON v.tenant_id=d.tenant_id AND v.version_id=d.target_version_id "
                "WHERE d.tenant_id=%s",
                (tenant,),
            ).fetchall()
            assert len(rows) == 438
            assert all(
                relation.startswith("SEMANTIC:")
                and stored_kind == kind
                and installer.seed_version(resource) == version
                for relation, stored_kind, kind, resource, version in rows
            )
            original = snapshot(conn, tenant)
            second = installer.install(conn, tenant, definitions)
            assert (
                not second["created_identities"]
                and second["exact_semantic_edges_created"] == 0
            )
            assert len(second["existing_identities_unchanged"]) == 142
            assert snapshot(conn, tenant) == original

            with reviewed_fixture(conn, tenant) as (author, reviewer):
                with conn.transaction(force_rollback=True):
                    successor = ResourceMutation(
                        resource_id=semantic_id,
                        object_type="SemanticContract",
                        identity_key="AccountCode",
                        display_name="SYNTHETIC reviewed AccountCode successor",
                        access_entity="__PLATFORM__",
                        expected_version_id=semantic_version,
                        attributes={"kind": "identifier", "version": 2},
                        valid_from=datetime.now(UTC) - timedelta(seconds=1),
                    )
                    proposal = ResourceProposal(
                        title="SYNTHETIC rollback-only semantic successor",
                        rationale="Verify bootstrap preserves an independently reviewed existing successor",
                        access_entity="__PLATFORM__",
                        mutations=[successor],
                    )
                    resources.propose(author, proposal)
                    resources.review(
                        reviewer,
                        proposal.proposal_id,
                        ResourceReview(
                            decision="APPROVED",
                            rationale="Independent synthetic successor verification",
                        ),
                    )
                    current = resources.get_resource(author, semantic_id)["resource"]
                    assert current["version_id"] != str(semantic_version)
                    # Heads are mutable indexes; deliberately remove only an isolated fixture head.
                    headless = canonical_id(tenant, "LinkType", "CONNECTS")
                    assert (
                        conn.execute(
                            "DELETE FROM resource_heads WHERE tenant_id=%s AND resource_id=%s RETURNING version_id",
                            (tenant, headless),
                        ).fetchone()
                        is not None
                    )
                    changed = deepcopy(definitions)
                    next(
                        d
                        for d in changed
                        if d["object_type"] == "SchemaDefinition"
                        and d["identity_key"] == "LocalAccount"
                    )["attributes"]["fields"]["account_code"]["kind"] = "text"
                    before = snapshot(conn, tenant)
                    replay = installer.install(conn, tenant, changed)
                    assert (
                        not replay["created_identities"]
                        and replay["exact_semantic_edges_created"] == 0
                    )
                    assert snapshot(conn, tenant) == before
                    candidate = new_schema()
                    try:
                        with conn.transaction():
                            installer.install(conn, tenant, [candidate])
                    except ValueError as exc:
                        assert "unavailable" in str(exc)
                        refused.append("reviewed_semantic_successor")
                    else:
                        raise AssertionError(
                            "A non-effective seed was accepted for a new schema"
                        )
                    assert snapshot(conn, tenant) == before
                assert snapshot(conn, tenant) == original

                for state in ("UNAVAILABLE", "REVOKED"):
                    with conn.transaction(force_rollback=True):
                        observed = LifecycleRequest(
                            subject=semantic_ref,
                            target_state="OBSERVED",
                            epistemic_state="OBSERVED",
                            business_state="PROVISIONAL",
                            availability_state=(
                                "UNAVAILABLE" if state == "UNAVAILABLE" else "AVAILABLE"
                            ),
                            reason="SYNTHETIC rollback-only availability verification",
                        )
                        resource_lifecycle.request_transition(author, observed)
                        resource_lifecycle.review_transition(
                            reviewer,
                            observed.request_id,
                            LifecycleReview(
                                decision="APPROVED",
                                reason="Independent synthetic lifecycle verification",
                            ),
                        )
                        if state == "REVOKED":
                            event = resource_lifecycle.history(author, semantic_ref)[
                                "events"
                            ][-1]
                            revoked = LifecycleRequest(
                                subject=semantic_ref,
                                expected_event_id=event["event_id"],
                                target_state="REVOKED",
                                epistemic_state="OBSERVED",
                                business_state="PROVISIONAL",
                                availability_state="AVAILABLE",
                                reason="SYNTHETIC rollback-only withdrawal verification",
                            )
                            resource_lifecycle.request_transition(author, revoked)
                            resource_lifecycle.review_transition(
                                reviewer,
                                revoked.request_id,
                                LifecycleReview(
                                    decision="APPROVED",
                                    reason="Independent synthetic withdrawal verification",
                                ),
                            )
                        before = snapshot(conn, tenant)
                        candidate = new_schema()
                        try:
                            with conn.transaction():
                                installer.install(conn, tenant, [candidate])
                        except ValueError as exc:
                            assert "withdrawn" in str(exc)
                            refused.append(state.lower() + "_semantic_seed")
                        else:
                            raise AssertionError("Withdrawn semantic seed was accepted")
                        assert snapshot(conn, tenant) == before
                        assert not installer.install(conn, tenant, definitions)[
                            "created_identities"
                        ]
                        assert snapshot(conn, tenant) == before
                    assert snapshot(conn, tenant) == original

            try:
                with conn.transaction():
                    installer.install(conn, rejected_tenant, [new_schema()])
            except ValueError as exc:
                assert "exact bootstrap semantics" in str(exc)
                refused.append("foreign_semantic_identity")
            else:
                raise AssertionError("Cross-tenant semantic reference was accepted")
            assert not conn.execute(
                "SELECT 1 FROM canonical_identities WHERE tenant_id=%s",
                (rejected_tenant,),
            ).fetchall()
            conn.execute("SET CONSTRAINTS ALL IMMEDIATE")
        finally:
            conn.rollback()
        assert all(not rows for rows in snapshot(conn, tenant).values())
        assert all(not rows for rows in snapshot(conn, rejected_tenant).values())
    evidence = {
        "state": "NATIVE_ROLLBACK_CONTRACT_PASS",
        "recorded_at": datetime.now(UTC).isoformat(),
        "database_port": 55441,
        "data_directory": data_directory,
        "platform_definitions": 142,
        "schema_definitions": 96,
        "semantic_contracts": 18,
        "new_schema_exact_semantic_edges": 438,
        "all_exact_seed_kinds_and_versions_verified": True,
        "idempotent_replay": True,
        "reviewed_successor_and_headless_identity_unchanged": True,
        "existing_attributes_versions_heads_dependencies_and_reviews_unchanged": True,
        "canonical_resource_and_lifecycle_review_used": True,
        "refusals_rolled_back_without_partial_publication": refused,
        "fixture_identities_retained": 0,
        "company_or_account_facts_created": 0,
        "historical_schema_repair_performed": False,
        "commit_restart_proof": False,
        "release_accepted": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence))


if __name__ == "__main__":
    main()
