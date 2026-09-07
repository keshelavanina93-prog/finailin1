"""Review local API expectations and retain actual server-collected observations."""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from finai_api.api.routes import REQUIRED_SCHEMA_VERSION
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import (
    ResourceMutation,
    ResourceProposal,
    ResourceReview,
)
from finai_api.domain.review import Principal
from finai_api.services import function_execution, resources
from finai_api.services.workspace import WorkspaceError

TARGET_KEY = "local-development:g8-api"
AGENT_KEY = "local-development:g8-api-observer"
DESIRED_KEY = "local-development:g8-api-expected-state"


def prepare(p: Principal, grants: dict) -> dict:
    target = canonical_id(p.scope.tenant_id, "DeploymentTarget", TARGET_KEY)
    agent = canonical_id(p.scope.tenant_id, "RuntimeAgent", AGENT_KEY)
    desired = canonical_id(p.scope.tenant_id, "DesiredState", DESIRED_KEY)
    manifest = function_execution.manifest()
    specs = [
        (
            target,
            "DeploymentTarget",
            TARGET_KEY,
            "G8 local API",
            {
                "definition": {
                    "environment_class": "LOCAL_DEVELOPMENT",
                    "component": "api",
                    "label": "G8 local API",
                }
            },
        ),
        (
            agent,
            "RuntimeAgent",
            AGENT_KEY,
            "Local API observer",
            {
                "deployment_target_id": str(target),
                "definition": {"actor_id": p.actor_id},
            },
        ),
        (
            desired,
            "DesiredState",
            DESIRED_KEY,
            "Reviewed local API expectations",
            {
                "deployment_target_id": str(target),
                "runtime_agent_id": str(agent),
                "definition": {
                    "expected_code_sha256": manifest["code_sha256"],
                    "expected_dependency_sha256": manifest["dependency_sha256"],
                    "required_schema_version": REQUIRED_SCHEMA_VERSION,
                    "max_observation_age_seconds": 300,
                },
            },
        ),
    ]
    mutations = []
    for identity, kind, key, label, attrs in specs:
        try:
            previous = resources.get_resource(p, identity)["resource"]
        except WorkspaceError as exc:
            if exc.status != 404:
                raise
            previous = None
        # Refresh exact dependency pins in the same independently reviewed proposal.
        mutations.append(
            ResourceMutation(
                resource_id=identity,
                object_type=kind,
                identity_key=key,
                display_name=label,
                expected_version_id=UUID(str(previous["version_id"]))
                if previous
                else None,
                valid_from=datetime.now(UTC),
                attributes=attrs,
            )
        )
    reviewer = next(
        Principal.model_validate(g)
        for g in grants.values()
        if {"ontology_admin", "ontology_review"}.issubset(g["permissions"])
        and g["actor_id"] != p.actor_id
        and str(g["scope"]["tenant_id"]) == str(p.scope.tenant_id)
    )
    proposal = ResourceProposal(
        title="Review local API observation target and expectations",
        rationale="Bind local observer and expected package/schema; no release or deployment approval",
        access_entity=p.scope.legal_entity_id,
        mutations=mutations,
    )
    resources.propose(p, proposal)
    resources.review(
        reviewer,
        proposal.proposal_id,
        ResourceReview(
            decision="APPROVED",
            rationale="Reviewed local development target, observer identity and expected package; unattested release provenance remains explicit",
        ),
    )
    return {
        "proposal_id": str(proposal.proposal_id),
        "target_id": str(target),
        "agent_id": str(agent),
        "desired_state": {
            "resource_id": str(desired),
            "version_id": str(
                resources.get_resource(p, desired)["resource"]["version_id"]
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--read-only", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/development/evidence/nin31-runtime-observation.json"),
    )
    args = parser.parse_args()
    grants = json.loads(os.environ["FINAI_ACCESS_TOKENS"])
    token, principal = next(
        (t, Principal.model_validate(g))
        for t, g in grants.items()
        if {"ontology_admin", "ontology_propose", "ontology_read"}.issubset(
            g["permissions"]
        )
    )
    if args.prepare:
        result = prepare(principal, grants)
        args.output.with_suffix(".preparation.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )
        print(
            "Canonical local API target, observer and expectations independently reviewed."
        )
        return
    previous = (
        json.loads(args.output.read_text(encoding="utf-8")) if args.read_only else None
    )
    with httpx.Client(
        base_url="http://127.0.0.1:3062/api/ontology",
        headers={"Authorization": "Bearer " + token},
        timeout=60,
    ) as client:
        if previous:
            request = previous["request"]
        else:
            desired = canonical_id(
                principal.scope.tenant_id, "DesiredState", DESIRED_KEY
            )
            response = client.get(f"/resources/{desired}")
            response.raise_for_status()
            request = {
                "request_id": str(uuid4()),
                "desired_state": {
                    "resource_id": str(desired),
                    "version_id": response.json()["resource"]["version_id"],
                },
            }
            args.output.write_text(
                json.dumps({"request": request}, indent=2) + "\n", encoding="utf-8"
            )
        if not args.read_only:
            response = client.post(
                "http://127.0.0.1:8062/v1/ontology/runtime-observations", json=request
            )
            response.raise_for_status()
            result = response.json()
        else:
            response = client.get(f"/runtime-observations/{request['request_id']}")
            response.raise_for_status()
            result = response.json()
        assert result["request_id"] == request["request_id"]
        assert result["current_use_authorized"] is False
        assert result["deployment_authorized"] is False
        report = result["reported_state"]
        assert report["contract"] == "runtime-observation/1"
        assert report["release_provenance"] == "LOCAL_DEVELOPMENT_UNATTESTED"
        UUID(report["observation"]["observer_instance_id"])
        assert (
            report["desired_state"]["version_id"]
            == request["desired_state"]["version_id"]
        )
        if not args.read_only:
            assert report["recorded_state"] == "MATCH", report["recorded_state"]
            assert report["observation"]["disk_matches_loaded"] is True
            assert (
                report["observation"]["database_schema_version"]
                >= REQUIRED_SCHEMA_VERSION
            )
            assert all(
                report["observation"]["health"][key] == "ready"
                for key in ("database", "schema", "evidence_store")
            )
        response = client.get(f"/runtime-observations/{request['request_id']}")
        response.raise_for_status()
        assert response.json()["reported_state"] == result["reported_state"]
        if not args.read_only:
            response = client.post(
                "http://127.0.0.1:8062/v1/ontology/runtime-observations", json=request
            )
            response.raise_for_status()
            assert response.json()["reported_state"] == result["reported_state"]
        if previous and previous.get("result"):
            assert previous["result"]["reported_state"] == result["reported_state"]
        response = client.get("/runtime-observations")
        response.raise_for_status()
        history = response.json()
    args.output.write_text(
        json.dumps(
            {
                "checked_at": datetime.now(UTC).isoformat(),
                "request": request,
                "result": result,
                "history": history,
                "retained_replay_and_history_equal": True,
                "release_accepted": False,
                "deployment_authorized": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        "Actual API reported state retained and reopened; no release or deployment authority granted."
    )


if __name__ == "__main__":
    main()
