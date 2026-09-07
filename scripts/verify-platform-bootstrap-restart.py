"""Explicit committed fixture proof restricted to the disposable D: CI database.

Run create, restart only the verified CI cluster, then run verify. The proof
retains a synthetic platform tenant; it never touches the mounted product DB.
"""

import argparse
import hashlib
import importlib.util
import json
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import psycopg
from finai_api.domain.ontology_catalog import platform_definitions

ROOT = Path(__file__).resolve().parents[1]
if ROOT.drive.upper() != "D:":
    raise ValueError("Verification artifacts must remain on D:")
EVIDENCE = ROOT / ".finai/artifacts/committed-bootstrap-proof.json"
spec = importlib.util.spec_from_file_location(
    "installer", ROOT / "scripts/install-ontology.py"
)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def connect():
    conn = psycopg.connect(os.environ["FINAI_MIGRATION_DATABASE_URL"])
    directory = str(conn.execute("SHOW data_directory").fetchone()[0]).replace(
        "\\", "/"
    )
    port = int(conn.execute("SHOW port").fetchone()[0])
    if directory.lower() != "d:/finai/g8-ci-repair/.finai/data/postgres-ci" or port != 55441:
        conn.close()
        raise ValueError("Only the disposable CI database may receive this fixture")
    return conn


def snapshot(conn, tenant):
    results = {}
    for table in (
        "canonical_identities",
        "resource_versions",
        "resource_heads",
        "resource_dependencies",
    ):
        rows = conn.execute(
            f"SELECT to_jsonb(t) FROM {table} t WHERE tenant_id=%s", (tenant,)
        ).fetchall()
        encoded = sorted(json.dumps(row[0], sort_keys=True) for row in rows)
        results[table] = {
            "count": len(rows),
            "sha256": hashlib.sha256("\n".join(encoded).encode()).hexdigest(),
        }
    return results


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("action", choices=["create", "verify"])
args = parser.parse_args()
EVIDENCE.parent.mkdir(parents=True, exist_ok=True)

if args.action == "create":
    tenant = str(uuid4())
    with connect() as conn:
        result = installer.install(conn, tenant, platform_definitions(tenant))
        assert (
            len(result["created_identities"]) == 142
            and result["exact_semantic_edges_created"] == 438
        )
        before = snapshot(conn, tenant)
        started_at = conn.execute("SELECT pg_postmaster_start_time()").fetchone()[0]
    with connect() as conn:
        assert snapshot(conn, tenant) == before
    EVIDENCE.write_text(
        json.dumps(
            {
                "fixture_tenant": tenant,
                "snapshot": before,
                "postmaster_started_before": started_at.isoformat(),
                "commit_reopen_pass": True,
                "database_restart_pass": False,
                "synthetic_only": True,
            },
            indent=2,
        )
    )
    print(
        "Committed 142 synthetic platform definitions and 438 edges; separate-connection reopen passed."
    )
elif args.action == "verify":
    evidence = json.loads(EVIDENCE.read_text())
    with connect() as conn:
        started_at = conn.execute("SELECT pg_postmaster_start_time()").fetchone()[0]
        if started_at <= datetime.fromisoformat(evidence["postmaster_started_before"]):
            raise ValueError("Database has not restarted since fixture commit")
        assert snapshot(conn, evidence["fixture_tenant"]) == evidence["snapshot"]
        result = installer.install(
            conn,
            evidence["fixture_tenant"],
            platform_definitions(evidence["fixture_tenant"]),
        )
        assert (
            not result["created_identities"]
            and result["exact_semantic_edges_created"] == 0
        )
        assert snapshot(conn, evidence["fixture_tenant"]) == evidence["snapshot"]
    evidence["database_restart_pass"] = True
    evidence["postmaster_started_after"] = started_at.isoformat()
    evidence["replay_after_restart_unchanged"] = True
    EVIDENCE.write_text(json.dumps(evidence, indent=2))
    print(
        "Committed definitions, versions, heads and exact edges survived database restart; replay unchanged."
    )
