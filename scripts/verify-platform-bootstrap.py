"""Rollback-only native proof of exact bootstrap semantic pins and replay safety."""

import argparse
import importlib.util
import json
import os
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
from finai_api.domain.ontology_catalog import platform_definitions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output.drive.upper() != "D:":
        raise ValueError("Verification evidence must stay on D:")
    spec = importlib.util.spec_from_file_location(
        "g8_platform_installer", Path(__file__).with_name("install-ontology.py")
    )
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    tenant, rejected_tenant = uuid4(), uuid4()
    definitions = [
        d
        for d in platform_definitions(tenant)
        if (
            d["object_type"] == "SemanticContract"
            and d["identity_key"] in {"CanonicalReference", "AccountCode"}
        )
        or (
            d["object_type"] == "SchemaDefinition"
            and d["identity_key"] == "LocalAccount"
        )
    ]
    assert len(definitions) == 3
    with psycopg.connect(os.environ["FINAI_MIGRATION_DATABASE_URL"]) as conn:
        assert (
            str(conn.execute("SHOW data_directory").fetchone()[0])
            .upper()
            .startswith("D:")
        )
        try:
            first = installer.install(conn, tenant, definitions)
            assert len(first["created_identities"]) == 3
            assert first["exact_semantic_edges_created"] == 3
            conn.execute("SET CONSTRAINTS ALL IMMEDIATE")
            rows = conn.execute(
                "SELECT d.relation,v.attributes->>'kind' FROM resource_dependencies d "
                "JOIN resource_versions v ON v.tenant_id=d.tenant_id "
                "AND v.version_id=d.target_version_id WHERE d.tenant_id=%s ORDER BY d.relation",
                (tenant,),
            ).fetchall()
            assert rows == [
                ("SEMANTIC:account_code", "identifier"),
                ("SEMANTIC:chart_id", "reference"),
                ("SEMANTIC:evidence_id", "reference"),
            ]
            second = installer.install(conn, tenant, definitions)
            assert (
                not second["created_identities"]
                and len(second["existing_identities_unchanged"]) == 3
            )
            assert second["exact_semantic_edges_created"] == 0
            changed = deepcopy(definitions)
            schema = next(d for d in changed if d["object_type"] == "SchemaDefinition")
            schema["attributes"]["fields"]["account_code"]["kind"] = "text"
            replay = installer.install(conn, tenant, changed)
            assert replay["historical_schema_repair_performed"] is False
            stored = conn.execute(
                "SELECT attributes FROM resource_versions WHERE tenant_id=%s "
                "AND object_type='SchemaDefinition'",
                (tenant,),
            ).fetchone()[0]
            assert stored["fields"]["account_code"]["kind"] == "identifier"
            # A schema naming another tenant's exact semantic identity must not
            # resolve it. The failed installation must roll back all of its rows.
            try:
                with conn.transaction():
                    installer.install(conn, rejected_tenant, [deepcopy(schema)])
            except ValueError as exc:
                assert "exact bootstrap semantics" in str(exc)
            else:
                raise AssertionError("Unresolved cross-tenant semantics were accepted")
            assert (
                conn.execute(
                    "SELECT count(*) FROM canonical_identities WHERE tenant_id=%s",
                    (rejected_tenant,),
                ).fetchone()[0]
                == 0
            )
        finally:
            conn.rollback()
        assert (
            conn.execute(
                "SELECT count(*) FROM canonical_identities WHERE tenant_id IN (%s,%s)",
                (tenant, rejected_tenant),
            ).fetchone()[0]
            == 0
        )
    evidence = {
        "state": "NATIVE_ROLLBACK_CONTRACT_PASS",
        "recorded_at": datetime.now(UTC).isoformat(),
        "new_schema_exact_semantic_edges": 3,
        "idempotent_replay": True,
        "existing_schema_attributes_unchanged": True,
        "unresolved_or_foreign_semantics_roll_back_installation": True,
        "fixture_identities_retained": 0,
        "company_or_account_facts_created": 0,
        "historical_schema_repair_performed": False,
        "release_accepted": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence))


if __name__ == "__main__":
    main()
