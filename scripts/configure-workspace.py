"""Upgrade local bootstrap credentials to explicit operator and reviewer identities."""

import json
import secrets
from hashlib import sha256
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / ".finai/local.json"
configuration = json.loads(path.read_text())
tokens = json.loads(configuration["FINAI_ACCESS_TOKENS"])
grants = {}
for token, value in tokens.items():
    grants[token] = (
        value
        if "scope" in value
        else {
            "actor_id": f"bootstrap-{sha256(token.encode()).hexdigest()[:24]}",
            "display_name": "Local operator",
            "scope": value,
            "permissions": ["read", "ingest", "export"],
        }
    )
if not any("review" in grant["permissions"] for grant in grants.values()):
    grants[secrets.token_hex(32)] = {
        "actor_id": "local-reviewer",
        "display_name": "Local reviewer",
        "scope": next(iter(grants.values()))["scope"],
        "permissions": ["read", "review", "export"],
    }
configuration["FINAI_ACCESS_TOKENS"] = json.dumps(grants)
path.write_text(json.dumps(configuration, indent=2))
print(
    "Configured separate local operator/reviewer identities in .finai/local.json; no secrets printed."
)
