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
    mutations = {item.resource_id: item for item in proposal.mutations}
    results = []
    for check in proposal.expectations:
        value: Any = mutations[check.resource_id].attributes
        present = True
        for field in check.attribute_path:
            if not isinstance(value, dict) or field not in value:
                present = False
                break
            value = value[field]
        passed = present and json.dumps(value, sort_keys=True) == json.dumps(
            check.expected, sort_keys=True
        )
        results.append({"name": check.name, "status": "PASS" if passed else "FAIL"})
    return {
        "evaluator": EVALUATOR,
        "proposal_hash": binding["proposal_hash"],
        "binding_hash": sha256(
            json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "status": "PASS" if all(r["status"] == "PASS" for r in results) else "FAIL",
        "expectations": results,
        "recorded_at": datetime.now(UTC).isoformat(),
        "checks": ["schema compatibility", "identity cycles", "dependency version pins", "impact"]
        + [f"{r['name']}: {r['status']}" for r in results],
        "scope": "Structural contract checks; domain evaluations are not certified.",
    }


def require_evaluation(proposal: ResourceProposal, retained: dict[str, Any]) -> None:
    evidence = retained.get("evaluation", {})
    if evidence.get("status") == "FAIL":
        raise WorkspaceError(409, "Proposal expectations failed; submit a corrected proposal")
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
