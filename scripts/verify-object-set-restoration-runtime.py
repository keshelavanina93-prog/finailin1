"""Prepare and verify reviewed restoration of an authentic saved source selection."""

import argparse
import importlib.util
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceReview
from finai_api.domain.review import Principal
from finai_api.services import resources

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "restoration_membership", ROOT / "scripts/verify-membership-query-runtime.py"
)
membership = importlib.util.module_from_spec(spec)
spec.loader.exec_module(membership)
KEY = "sog-source-contexts:restoration:v1"


def read(client, path, **params):
    response = client.get(path, params=params)
    response.raise_for_status()
    return response.json()


def selected(client, resource, time):
    return read(
        client,
        f"/model/sets/{resource['resource_id']}/objects",
        version=resource["version_id"],
        offset=0,
        limit=10,
        **time,
    )


def check_rows(result, columns):
    objects = result["objects"]
    assert result["total"] == len(columns) == len(objects)
    assert result["next_offset"] is None
    assert {row["attributes"]["source_column"] for row in objects} == set(columns)
    expected = (
        membership.EXPECTED
        if len(columns) == 2
        else {"7959af7f-a1bb-5573-8006-d1fc14f58681"}
    )
    assert {row["resource_id"] for row in objects} == expected
    assert all(
        row["attributes"]["evidence_id"] == membership.EVIDENCE for row in objects
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--prepare", action="store_true")
    modes.add_argument("--review-proposal", type=UUID)
    modes.add_argument("--read-only", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:3062/api/ontology")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT
        / "docs/development/evidence/nin6-object-set-restoration-runtime.json",
    )
    args = parser.parse_args()
    assert args.output.resolve().drive.lower() == "d:"
    grants = json.loads(os.environ["FINAI_ACCESS_TOKENS"])
    token, author = next(
        (token, Principal.model_validate(grant))
        for token, grant in grants.items()
        if {"ontology_admin", "ontology_propose", "ontology_read"}
        <= set(grant["permissions"])
    )
    identity = str(canonical_id(author.scope.tenant_id, "ObjectSetDefinition", KEY))
    save = lambda proof: membership.save(args.output, proof)
    with httpx.Client(
        base_url=args.base_url,
        headers={"Authorization": "Bearer " + token},
        trust_env=False,
        timeout=90,
    ) as client:
        if args.prepare:
            assert not args.output.exists(), (
                "Existing proof must be reused, not overwritten"
            )
            reviewer = next(
                Principal.model_validate(grant)
                for grant in grants.values()
                if grant["actor_id"] != author.actor_id
                and grant["scope"] == author.scope.model_dump(mode="json")
                and {"ontology_admin", "ontology_review"} <= set(grant["permissions"])
            )
            original = membership.shared.publish(
                author,
                reviewer,
                "ObjectSetDefinition",
                KEY,
                "Region and Department source selection",
                {"definition": membership.query()},
            )
            proof = {"phase": "FIRST_VERSION_PREPARED", "original": original}
            save(proof)
            narrowed = membership.shared.publish(
                author,
                reviewer,
                "ObjectSetDefinition",
                KEY,
                "Region source selection",
                {"definition": membership.query(values=["Y"])},
            )
            now = datetime.now(UTC).isoformat()
            proof.update(narrowed=narrowed, time={"valid_at": now, "known_at": now})
            save(proof)
            initial = selected(client, original, proof["time"])
            current = selected(client, narrowed, proof["time"])
            check_rows(initial, ["Y", "AA"])
            check_rows(current, ["Y"])
            proof.update(
                phase="RESTORATION_REVIEW_READY",
                original_result=initial,
                narrowed_result=current,
            )
            save(proof)
            print(
                json.dumps(
                    {
                        "resource_id": identity,
                        "original": membership.pin(original),
                        "narrowed": membership.pin(narrowed),
                        "time": proof["time"],
                    }
                )
            )
            return
        proof = json.loads(args.output.read_text(encoding="utf-8"))
        original, narrowed = proof["original"], proof["narrowed"]
        assert original["resource_id"] == narrowed["resource_id"] == identity
        if args.review_proposal:
            detail = resources.proposal_detail(author, args.review_proposal)
            proposal = detail.proposal
            assert proposal.restores_versions == {
                UUID(identity): UUID(original["version_id"])
            }
            assert len(proposal.mutations) == 1
            mutation = proposal.mutations[0]
            assert str(mutation.expected_version_id) == narrowed["version_id"]
            for field in (
                "attributes",
                "display_name",
                "object_type",
                "evidence_class",
            ):
                assert getattr(mutation, field) == original[field]
            reviewer = next(
                Principal.model_validate(grant)
                for grant in grants.values()
                if grant["actor_id"] != detail.submitted_by
                and grant["scope"] == author.scope.model_dump(mode="json")
                and {"ontology_admin", "ontology_review"} <= set(grant["permissions"])
            )
            assert detail.decision in (None, "APPROVED")
            if detail.decision is None:
                detail = resources.review(
                    reviewer,
                    args.review_proposal,
                    ResourceReview(
                        decision="APPROVED",
                        rationale="Independent review restores the retained Region and Department source selection; no source or financial authority change",
                    ),
                )
            proof["restoration_proposal"] = detail.model_dump(mode="json")
            save(proof)
        assert "restoration_proposal" in proof, (
            "Review the browser-created proposal first"
        )
        detail = resources.proposal_detail(
            author, UUID(proof["restoration_proposal"]["proposal"]["proposal_id"])
        )
        assert (
            detail.decision == "APPROVED" and detail.reviewed_by != detail.submitted_by
        )
        restored = read(client, f"/resources/{identity}")["resource"]
        assert restored["version_id"] not in (
            original["version_id"],
            narrowed["version_id"],
        )
        assert restored["attributes"] == original["attributes"]
        initial, restricted, recovered = (
            selected(client, item, proof["time"])
            for item in (original, narrowed, restored)
        )
        assert initial == proof["original_result"]
        assert restricted == proof["narrowed_result"]
        check_rows(recovered, ["Y", "AA"])
        assert recovered["objects"] == initial["objects"]
        if "restored" in proof:
            assert (
                restored == proof["restored"] and recovered == proof["restored_result"]
            )
        proof.update(
            phase="REVIEWED_RESTORATION_VERIFIED",
            restored=restored,
            restored_result=recovered,
            restoration_proposal=detail.model_dump(mode="json"),
            source_objects_unchanged=True,
            financial_authority=False,
            last_readback_at=datetime.now(UTC).isoformat(),
        )
        save(proof)
        print(
            json.dumps({"phase": proof["phase"], "restored": membership.pin(restored)})
        )


if __name__ == "__main__":
    main()
