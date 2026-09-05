"""Create isolated local database and restricted runtime identity; secrets stay in .finai."""
import json
import os
import secrets
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

root = Path(__file__).resolve().parents[1]
config_file = root / ".finai/local.json"
if config_file.exists():
    print("Local database already provisioned; configuration: .finai/local.json")
    raise SystemExit(0)
admin = os.environ["FINAI_MIGRATION_DATABASE_URL"]
password, token = secrets.token_hex(32), secrets.token_hex(32)
with psycopg.connect(admin, autocommit=True) as conn:
    conn.execute(sql.SQL("CREATE ROLE finai_runtime LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS")
                 .format(sql.Literal(password)))
    conn.execute("CREATE DATABASE finai_dev")
database_admin = make_conninfo(admin, dbname="finai_dev")
with psycopg.connect(database_admin) as conn:
    conn.execute((root / "services/api/migrations/001_hydration.sql").read_text())
    conn.execute("GRANT CONNECT ON DATABASE finai_dev TO finai_runtime")
    conn.execute("GRANT USAGE ON SCHEMA public TO finai_runtime")
    conn.execute("GRANT SELECT, INSERT ON hydration_runs TO finai_runtime")
scope = {"tenant_id": "805d8a32-d12b-4268-a236-b0b16e59da9f", "legal_entity_id": "entity-ge-001",
         "period": "2026-08", "currency": "GEL"}
config_file.write_text(json.dumps({
    "FINAI_DATABASE_URL": make_conninfo(database_admin, user="finai_runtime", password=password),
    "FINAI_MIGRATION_DATABASE_URL": database_admin,
    "FINAI_ACCESS_TOKENS": json.dumps({token: scope}),
}, indent=2))
print("Provisioned finai_dev with restricted runtime role. Configuration: .finai/local.json")
