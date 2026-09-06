"""Publication shape and pin coverage checks; these never grant certified current use."""

from collections.abc import Callable, Mapping, Sequence
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from finai_api.domain.certification import CertificationContract
from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.domain.resources import ResourceMutation
from finai_api.services.workspace import WorkspaceError


def _requirements(raw: Any) -> dict[str, VersionReference]:
    if not isinstance(raw, dict) or not 1 <= len(raw) <= 1000:
        raise WorkspaceError(409, "Certification requirements must be a resource-to-policy mapping")
    result = {}
    try:
        for key, value in raw.items():
            identifier = str(UUID(key))
            if identifier != key or identifier in result:
                raise ValueError("Material IDs must use unique canonical UUID strings")
            if not isinstance(value, dict) or set(value) != {"resource_id", "version_id"}:
                raise ValueError("An exact certification policy reference is required")
            result[identifier] = VersionReference.model_validate(value)
    except (ValueError, TypeError, AttributeError, ValidationError) as exc:
        raise WorkspaceError(409, "Invalid exact certification requirements") from exc
    return result


def validate_requirements(
    item: ResourceMutation,
    target: Callable[[str, str, str], dict[str, Any]],
    schema_version_id: UUID | str | None = None,
) -> dict[str, VersionReference]:
    """Record material/policy pins and check declared type applicability.

    Exact policy schema pins, receipts, current authority and complete direct-pin
    coverage still require the runtime guard; a successful return is not certification.
    """
    raw = item.attributes.get("certification_requirements")
    if raw is None:
        if item.attributes.get("minimum_authority_state") == "CERTIFIED":
            raise WorkspaceError(409, "Certified consumption requires explicit policy mappings")
        return {}
    requirements = _requirements(raw)
    source = str(item.resource_id)
    for material_id, reference in requirements.items():
        if material_id == source or str(reference.resource_id) == source:
            raise WorkspaceError(409, "A consumer cannot certify itself or act as its own policy")
        policy = target(str(reference.resource_id), source, "CERTIFICATION_POLICY:" + material_id)
        subject = target(material_id, source, "CERTIFICATION_SUBJECT:" + material_id)
        if (
            str(policy["version_id"]) != str(reference.version_id)
            or policy["object_type"] != "CertificationContract"
        ):
            raise WorkspaceError(409, "Certification policy must match the exact contract version")
        if schema_version_id is not None and str(subject["version_id"]) == str(schema_version_id):
            raise WorkspaceError(409, "The consumer schema is an authority control, not material")
        try:
            specification = CertificationContract.model_validate(policy["attributes"])
        except ValidationError as exc:
            raise WorkspaceError(409, "Invalid canonical certification policy") from exc
        if subject["object_type"] != specification.definition.subject_type:
            raise WorkspaceError(409, "Certification policy does not apply to the material type")
    return requirements


def validate_requirement_coverage(
    requirements: Mapping[str, VersionReference],
    direct_pins: Sequence[VersionReference],
    schema_version_id: UUID | str | None = None,
) -> None:
    """Check all direct material inputs are mapped; only exact controls are exempt.

    Invoke after policy type/applicability validation. Repeated relation pins may name
    the same exact version, but conflicting versions for an identity fail closed.
    """
    pins: dict[str, UUID] = {}
    for pin in direct_pins:
        key = str(pin.resource_id)
        if key in pins and pins[key] != pin.version_id:
            raise WorkspaceError(409, "Conflicting direct certification dependency versions")
        pins[key] = pin.version_id
    controls = set()
    for policy in requirements.values():
        if pins.get(str(policy.resource_id)) != policy.version_id:
            raise WorkspaceError(409, "Certification policy is not an exact direct dependency")
        controls.add(str(policy.resource_id))
    if schema_version_id is not None:
        if not any(str(version) == str(schema_version_id) for version in pins.values()):
            raise WorkspaceError(409, "Consumer schema is missing from direct dependency pins")
        controls.update(
            key for key, version in pins.items() if str(version) == str(schema_version_id)
        )
    if set(requirements) != set(pins) - controls:
        raise WorkspaceError(
            409, "Certification mappings must exactly cover direct material inputs"
        )
