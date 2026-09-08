"""Reviewed runtime installation must consume accepted semantics, not seed UUIDs."""

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4, uuid5

from test_definition_history import DB, retained  # noqa: F401

from finai_api.domain.ontology_catalog import CATALOG_NAMESPACE, canonical_id, platform_definitions
from finai_api.domain.resources import ResourceMutation, ResourceProposal, ResourceReview
from finai_api.services import resources


@DB
def test_runtime_installs_external_schemas_against_reviewed_semantics(monkeypatch, retained):  # noqa: F811
    reader, _ = retained
    maker = reader.model_copy(
        update={
            "scope": reader.scope.model_copy(update={"tenant_id": uuid4()}),
            "permissions": ("ontology_admin", "ontology_read", "ontology_propose"),
        }
    )
    checker = maker.model_copy(
        update={
            "actor_id": "synthetic-runtime-installer-reviewer",
            "permissions": ("ontology_admin", "ontology_read", "ontology_review"),
        }
    )
    tenant = maker.scope.tenant_id
    semantics = ResourceProposal(
        title="Synthetic reviewed platform semantics",
        rationale="Fixture establishes reviewed semantics without any bootstrap seed versions",
        access_entity="__PLATFORM__",
        mutations=[
            ResourceMutation(
                resource_id=canonical_id(tenant, spec["object_type"], spec["identity_key"]),
                valid_from=datetime.now(UTC),
                **spec,
            )
            for spec in platform_definitions(tenant)
            if spec["object_type"] == "SemanticContract"
        ],
    )
    resources.propose(maker, semantics)
    resources.review(
        checker,
        semantics.proposal_id,
        ResourceReview(
            decision="APPROVED",
            rationale="Independently review synthetic platform semantics",
        ),
    )
    semantic_id = canonical_id(tenant, "SemanticContract", "OntologyDefinition")
    reviewed = resources.get_resource(maker, semantic_id)["resource"]
    seed_id = uuid5(CATALOG_NAMESPACE, f"{semantic_id}:platform-v1")
    assert UUID(reviewed["version_id"]) != seed_id
    monkeypatch.setenv(
        "FINAI_ACCESS_TOKENS",
        json.dumps(
            {
                "synthetic-installer-maker": maker.model_dump(mode="json"),
                "synthetic-installer-checker": checker.model_dump(mode="json"),
            }
        ),
    )
    path = Path(__file__).resolve().parents[3] / "scripts" / "install-ontology-runtime.py"
    spec = importlib.util.spec_from_file_location("synthetic_runtime_installer", path)
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    installer.main()

    for kind in (
        "ExternalOntologySource",
        "ExternalOntologyRelease",
        "ExternalOntologyModule",
        "OntologyImportRun",
        "OntologyProfile",
        "ExternalConstraintProfile",
        "OntologyValidationReport",
    ):
        schema_id = canonical_id(tenant, "SchemaDefinition", kind)
        row = resources.get_resource(maker, schema_id)["resource"]
        assert row["authority_state"] == "APPROVED"
        assert row["access_entity"] == "__PLATFORM__"
        with resources.resource_connection(maker) as conn:
            target = conn.execute(
                "SELECT target_resource_id,target_version_id FROM resource_dependencies "
                "WHERE tenant_id=%s AND version_id=%s AND relation='SEMANTIC:definition'",
                (tenant, row["version_id"]),
            ).fetchall()
            decision = conn.execute(
                "SELECT p.submitted_by,d.reviewed_by,d.decision FROM resource_versions v "
                "JOIN resource_proposals p USING(tenant_id,proposal_id) "
                "JOIN resource_decisions d USING(tenant_id,proposal_id) "
                "WHERE v.tenant_id=%s AND v.version_id=%s",
                (tenant, row["version_id"]),
            ).fetchone()
        assert target == [(semantic_id, UUID(reviewed["version_id"]))]
        assert decision == (maker.actor_id, checker.actor_id, "APPROVED")
        if kind in {"ExternalOntologyModule", "OntologyImportRun"}:
            assert row["attributes"]["fields"]["release_id"]["target_type"] == (
                "ExternalOntologyRelease"
            )
        if kind in {
            "ExternalOntologyRelease", "ExternalOntologyModule", "OntologyImportRun",
            "OntologyValidationReport",
        }:
            assert row["attributes"]["fields"]["evidence_id"]["target_type"] == "SourceEvidence"

    def snapshot():
        with resources.resource_connection(maker) as conn:
            return [
                conn.execute(
                    f"SELECT count(*) FROM {table} WHERE tenant_id=%s", (tenant,)
                ).fetchone()[0]
                for table in (
                    "resource_proposals",
                    "resource_decisions",
                    "resource_versions",
                    "resource_dependencies",
                )
            ]

    accepted = snapshot()
    installer.main()
    assert snapshot() == accepted
    assert resources.get_resource(maker, semantic_id)["resource"] == reviewed
