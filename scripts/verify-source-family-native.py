"""Focused native tamper/RLS checks against an already reviewed source family.

Every mutation attempted here is deliberately invalid and must be refused before
publication. No compatible successor or financial result is manufactured.
"""

import argparse
import json
import os
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.domain.review import Principal
from finai_api.services import resources, source_adoption
from finai_api.services.workspace import WorkspaceError

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("identity", type=UUID)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
output = args.output.resolve()
if output.drive.lower() != "d:":
    raise ValueError("Native acceptance artifacts must stay on D:")
principals = [
    Principal.model_validate(p)
    for p in json.loads(os.environ["FINAI_ACCESS_TOKENS"]).values()
]
maker = next(
    p
    for p in principals
    if {"ontology_admin", "ontology_propose"} <= set(p.permissions)
)
original = resources.get_resource(maker, args.identity)["resource"]
assert original["object_type"] == "SourceFamily"
checks = []
for field, value in [
    ("source_sha256", "f" * 64),
    ("schema_sha256", "f" * 64),
    ("source_rows", 595),
    ("missing_amounts", None),
    ("amount_field", "annotated_amount"),
]:
    attrs = deepcopy(original["attributes"])
    baseline = attrs["definition"]["baseline"]
    if field == "missing_amounts":
        baseline.update(missing_amount_count=0, missing_amount_coordinates=[])
    elif field == "amount_field":
        baseline["meaning"][field] = value
    else:
        baseline[field] = value
    proposal = ResourceProposal(
        title="NIN-56 invalid source-family integrity probe",
        rationale="This altered retained observation must be rejected before proposal publication.",
        access_entity=original["access_entity"],
        mutations=[
            ResourceMutation(
                resource_id=args.identity,
                expected_version_id=original["version_id"],
                object_type="SourceFamily",
                identity_key=original["identity_key"],
                display_name=original["display_name"],
                attributes=attrs,
                valid_from=datetime.now(UTC),
                evidence_class="USER_ASSERTED",
            )
        ],
    )
    try:
        resources.propose(maker, proposal)
    except WorkspaceError as exc:
        assert exc.status == 422 and "differs from retained bytes" in exc.detail
        checks.append({"tamper": field, "status": exc.status, "refusal": exc.detail})
    else:
        raise AssertionError(
            f"Forged source-family {field} passed native proposal validation"
        )
    try:
        resources.proposal_detail(maker, proposal.proposal_id)
    except WorkspaceError as exc:
        assert exc.status == 404
    else:
        raise AssertionError("An invalid source-family proposal was retained")
foreign = maker.model_copy(
    update={
        "scope": maker.scope.model_copy(
            update={"legal_entity_id": "synthetic-foreign-" + uuid4().hex}
        ),
        "permissions": ("ontology_read",),
    }
)
try:
    resources.get_resource(foreign, args.identity)
except WorkspaceError as exc:
    assert exc.status == 404
    checks.append({"foreign_entity": "REFUSED", "status": 404})
else:
    raise AssertionError("A foreign entity read the reviewed source family")
after = resources.get_resource(maker, args.identity)["resource"]
assert after == original
result = {
    "family": source_adoption.pin(after).model_dump(mode="json"),
    "native_checks": checks,
    "original_family_unchanged": True,
    "invalid_proposals_retained": False,
    "adoption_published": False,
    "authentic_later_source_acceptance": False,
}
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result, indent=2))
