import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from finai_api.domain.authority import canonical_sha256
from finai_api.domain.resources import ResourceProposal
from finai_api.services.workspace import WorkspaceError

EVALUATOR = "canonical-structural-contract/v1"


def evaluation_binding(proposal: ResourceProposal, validation: dict[str, Any]) -> dict[str, Any]:
    return {
        "proposal_hash": canonical_sha256(proposal),
        "dependency_heads": validation["dependency_heads"],
        "dependencies": validation["dependencies"],
        "schema_versions": validation["schema_versions"],
        "impact_fingerprint": validation["downstream_impact"]["fingerprint"],
        "compatibility": validation["compatibility"],
        "identity_cycles": validation["identity_cycles"],
    }


def record_evaluation(proposal: ResourceProposal, validation: dict[str, Any]) -> dict[str, Any]:
    binding = evaluation_binding(proposal, validation)
    return {
        "evaluator": EVALUATOR,
        "proposal_hash": binding["proposal_hash"],
        "binding_hash": sha256(
            json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "status": "PASS",
        "recorded_at": datetime.now(UTC).isoformat(),
        "checks": ["schema compatibility", "identity cycles", "dependency version pins", "impact"],
        "scope": "Structural contract checks; domain evaluations are not certified.",
    }


def require_evaluation(proposal: ResourceProposal, retained: dict[str, Any]) -> None:
    evidence = retained.get("evaluation", {})
    if (
        evidence.get("evaluator") != EVALUATOR
        or evidence.get("status") != "PASS"
        or evidence.get("proposal_hash") != canonical_sha256(proposal)
        or evidence.get("binding_hash")
        != sha256(
            json.dumps(
                evaluation_binding(proposal, retained), sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
    ):
        raise WorkspaceError(
            409, "Matching proposal evaluation evidence is required; submit a refreshed proposal"
        )
