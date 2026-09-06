"""Exact certification requirements over the existing canonical dependency universe."""

from typing import Any
from uuid import UUID

from finai_api.domain.certification import CertificationContract
from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.domain.review import Principal
from finai_api.services.certification import receipt_for_current_use
from finai_api.services.certification_requirements import (
    _requirements,
    validate_requirement_coverage,
)
from finai_api.services.workspace import WorkspaceError


def certified_event(
    cursor: Any,
    principal: Principal,
    subject: VersionReference,
    event: dict[str, Any],
    required: VersionReference | None = None,
) -> dict[str, Any]:
    """A CERTIFIED label alone is never sufficient for current consumption."""
    payload = event["payload"]
    try:
        receipt_id = UUID(payload["certification_receipt_id"])
        contract = VersionReference.model_validate(payload["certification_contract"])
    except (ValueError, TypeError, KeyError) as exc:
        raise WorkspaceError(409, "Certified state lacks exact retained contract evidence") from exc
    if required is not None and contract != required:
        raise WorkspaceError(409, "Certified input does not satisfy the required exact policy")
    receipt = receipt_for_current_use(cursor, principal, receipt_id, subject, contract)
    if event.get("certification_proof_hash") != receipt["proof_hash"]:
        raise WorkspaceError(409, "Certified lifecycle evidence hash does not match its receipt")
    return {
        "receipt_id": str(receipt_id),
        "contract": contract.model_dump(mode="json"),
        "proof_hash": receipt["proof_hash"],
        "claim": "CANONICAL_DEFINITION_CONFORMANCE",
    }


def requirements_for_use(
    cursor: Any,
    principal: Principal,
    consumer: dict[str, Any],
    pins: list[VersionReference],
) -> tuple[dict[str, VersionReference], set[str]]:
    """Derive controls from validated schema/policy pins, never caller role flags."""
    from finai_api.services.resource_lifecycle import _version

    raw = consumer["attributes"].get("certification_requirements")
    if raw is None:
        raise WorkspaceError(409, "Certified consumption requires exact policy requirements")
    requirements = _requirements(raw)
    validate_requirement_coverage(requirements, pins, consumer["schema_version_id"])
    by_resource = {str(pin.resource_id): pin for pin in pins}
    controls = {
        str(pin.resource_id) for pin in pins if pin.version_id == consumer["schema_version_id"]
    }
    for material_id, policy_ref in requirements.items():
        if material_id == str(consumer["resource_id"]):
            raise WorkspaceError(409, "A consumer cannot certify itself")
        policy = _version(cursor, principal, policy_ref)
        if policy["object_type"] != "CertificationContract":
            raise WorkspaceError(409, "Certified use requires a canonical CertificationContract")
        spec = CertificationContract.model_validate(policy["attributes"])
        subject = _version(cursor, principal, by_resource[material_id])
        if subject["object_type"] != spec.definition.subject_type:
            raise WorkspaceError(409, "Certification policy does not apply to this input type")
        controls.add(str(policy_ref.resource_id))
    return requirements, controls
