"""Explicit deployment migration; never run DDL from API startup."""
import os
from pathlib import Path

import psycopg

root = Path(__file__).resolve().parents[1]
with psycopg.connect(os.environ["FINAI_MIGRATION_DATABASE_URL"]) as conn:
    for migration in sorted((root / "services/api/migrations").glob("*.sql")):
        conn.execute(migration.read_text(encoding="utf-8"))
        print(f"Applied {migration.name}")
