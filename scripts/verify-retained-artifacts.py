"""Retain built bytes through shared evidence and independently reviewed Artifact resources."""

import argparse
import importlib.util
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import (
    ResourceMutation,
    ResourceProposal,
    ResourceReview,
)
from finai_api.domain.review import Principal
from finai_api.services import resources, source_documents
from finai_api.services.workspace import WorkspaceError

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "artifact_sources", ROOT / "scripts/package-source.py"
)
sources = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sources)


def current(principal, identity):
    try:
        return resources.get_resource(principal, identity)["resource"]
    except WorkspaceError as exc:
        if exc.status != 404:
            raise
        return None


def retain(principal, reviewer, path, expected_hash, kind):
    sources.check_path(path)
    if not 0 < path.stat().st_size <= 32_000_000:
        raise ValueError("Artifact exceeds existing evidence-store bounds")
    content = path.read_bytes()
    digest = sources.digest(content)
    if digest != expected_hash:
        raise ValueError("Artifact differs from selected build identity")
    document = source_documents.retain_document(principal, path.name, content)
    repeated = source_documents.retain_document(principal, path.name, content)
    if repeated != document:
        raise ValueError("Retained artifact identity changed on repeat")
    evidence = canonical_id(principal.scope.tenant_id, "SourceEvidence", digest)
    identity = canonical_id(principal.scope.tenant_id, "Artifact", "sha256:" + digest)
    attributes = {
        "sha256": digest,
        "byte_length": len(content),
        "document_id": document["document_id"],
        "evidence_id": str(evidence),
        "definition": {
            "contract": "retained-build-artifact/1",
            "authority": "RETAINED_BYTES_ONLY",
            "artifact_kind": kind,
        },
    }
    mutations = []
    previous_evidence = current(principal, evidence)
    if previous_evidence is None:
        mutations.append(
            ResourceMutation(
                resource_id=evidence,
                object_type="SourceEvidence",
                identity_key=digest,
                display_name="G8 retained " + kind.lower().replace("_", " "),
                valid_from=datetime.now(UTC),
                evidence_class="SOURCE_BOUND",
                attributes={"sha256": digest, "source_system": "G8_BUILD_ARTIFACT"},
            )
        )
    elif previous_evidence["attributes"]["sha256"] != digest:
        raise ValueError("Existing canonical evidence differs")
    previous = current(principal, identity)
    if previous is None:
        mutations.append(
            ResourceMutation(
                resource_id=identity,
                object_type="Artifact",
                identity_key="sha256:" + digest,
                display_name="G8 " + kind.lower().replace("_", " "),
                valid_from=datetime.now(UTC),
                evidence_class="SOURCE_BOUND",
                attributes=attributes,
            )
        )
    elif previous["attributes"] != attributes:
        raise ValueError(
            "Existing Artifact descriptor differs; explicit review required"
        )
    proposal_id = None
    if mutations:
        proposal = ResourceProposal(
            title="Retain G8 " + kind.lower().replace("_", " "),
            rationale="Verify immutable bytes and shared identity only; no deployment or release approval",
            access_entity=principal.scope.legal_entity_id,
            mutations=mutations,
        )
        resources.propose(principal, proposal)
        resources.review(
            reviewer,
            proposal.proposal_id,
            ResourceReview(
                decision="APPROVED",
                rationale="Independent retained-byte hash/scope review; build and release authority are not granted",
            ),
        )
        proposal_id = str(proposal.proposal_id)
    accepted = current(principal, identity)
    metadata, restored = source_documents.document_bytes(
        principal, document["document_id"]
    )
    if restored != content or metadata["source_sha256"] != digest:
        raise ValueError("Retained Artifact readback differs")
    return {
        "resource_id": str(identity),
        "version_id": str(accepted["version_id"]),
        "content_hash": accepted["content_hash"],
        "sha256": digest,
        "byte_length": len(content),
        "document_id": document["document_id"],
        "evidence_id": str(evidence),
        "proposal_id": proposal_id,
        "artifact_kind": kind,
        "repeated_retention_equal": True,
        "readback_equal": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-archive", required=True, type=Path, action="append")
    parser.add_argument("--api-receipt", required=True, type=Path)
    parser.add_argument("--web-receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    for path in (*args.source_archive, args.api_receipt, args.web_receipt, args.output):
        sources.check_path(path)
    verified_sources = [(path, sources.verify(path)) for path in args.source_archive]
    api = json.loads(args.api_receipt.read_text(encoding="utf-8"))
    web = json.loads(args.web_receipt.read_text(encoding="utf-8"))
    if not {api["archive_sha256"], web["source"]["archive_sha256"]}.issubset(
        {proof["archive_sha256"] for _, proof in verified_sources}
    ):
        raise ValueError("Both component source archives must be supplied")
    grants = json.loads(os.environ["FINAI_ACCESS_TOKENS"])
    token, principal = next(
        (token, Principal.model_validate(grant))
        for token, grant in grants.items()
        if {"ingest", "ontology_propose", "ontology_read"}.issubset(
            grant["permissions"]
        )
    )
    reviewer = next(
        Principal.model_validate(grant)
        for grant in grants.values()
        if "ontology_review" in grant["permissions"]
        and grant["actor_id"] != principal.actor_id
        and Principal.model_validate(grant).scope == principal.scope
    )
    inputs = [
        (path, proof["archive_sha256"], "SOURCE_ARCHIVE")
        for path, proof in verified_sources
    ] + [
        (Path(api["wheel"]), api["wheel_sha256"], "API_WHEEL"),
        (
            args.web_receipt.parent / web["archive"],
            web["archive_sha256"],
            "WEB_STANDALONE",
        ),
    ]
    result = [retain(principal, reviewer, *item) for item in inputs]
    with httpx.Client(
        base_url="http://127.0.0.1:3062/api/ontology",
        headers={"Authorization": "Bearer " + token},
        timeout=60,
        trust_env=False,
        follow_redirects=False,
    ) as client:
        for item in result:
            response = client.get("/resources/" + item["resource_id"])
            response.raise_for_status()
            if response.json()["resource"]["version_id"] != item["version_id"]:
                raise ValueError("Product proxy returned a different Artifact version")
    proof = {
        "contract": "g8-retained-artifact-proof/1",
        "artifacts": result,
        "product_proxy_readback": True,
        "authority": "RETAINED_BYTES_ONLY",
        "release_accepted": False,
        "deployment_granted": False,
    }
    args.output.write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    print(
        f"{len(result)} canonical artifacts retained and independently reviewed; exact bytes and product readback verified."
    )


if __name__ == "__main__":
    main()
