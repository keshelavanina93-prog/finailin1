"""Add stable, local-only NYXCore credentials to the ignored runtime config."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
config_path = root / ".finai" / "local.json"
if not config_path.exists():
    raise SystemExit(".finai/local.json is missing; start local PostgreSQL once first.")
config = json.loads(config_path.read_text())
tokens = json.loads(config["FINAI_ACCESS_TOKENS"])
token = config.get("FINAI_DEV_ACCESS_TOKEN") or next(iter(tokens), "")
if not token or token not in tokens:
    raise SystemExit("No local workspace access token is available.")
config.update({
    "FINAI_DEV_LOGIN_ENABLED": "true",
    "FINAI_DEV_USERNAME": "nyxcore.local",
    "FINAI_DEV_PASSWORD": "NYXcore-local-2026!",
    "FINAI_DEV_ACCESS_TOKEN": token,
    "FINAI_PETROLEUM_ACTION_ADAPTER": "local",
    "NEXT_PUBLIC_FINAI_LOCAL_LOGIN": "true",
})
config_path.write_text(json.dumps(config, indent=2) + "\n")
print("Stable NYXCore local credentials configured in .finai/local.json")
