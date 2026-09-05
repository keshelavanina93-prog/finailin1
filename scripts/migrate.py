"""Explicit deployment migration; never run DDL from API startup."""

import os
from pathlib import Path

import psycopg

root = Path(__file__).resolve().parents[1]
with psycopg.connect(
    os.environ["FINAI_MIGRATION_DATABASE_URL"], autocommit=True, connect_timeout=5
) as conn:
    for migration in sorted((root / "services/api/migrations").glob("*.sql")):
        version = int(migration.name.split("_")[0])
        registry = conn.execute(
            "SELECT to_regclass('public.schema_migrations')"
        ).fetchone()
        if registry and registry[0]:
            applied = conn.execute(
                "SELECT 1 FROM schema_migrations WHERE version=%s", (version,)
            ).fetchone()
            if applied:
                continue
        conn.execute(migration.read_text(encoding="utf-8"))
        print(f"Applied {migration.name}")
