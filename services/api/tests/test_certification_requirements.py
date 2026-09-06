from datetime import UTC, datetime
from uuid import uuid4

import pytest

from finai_api.domain.resource_lifecycle import VersionReference
from finai_api.domain.resources import ResourceMutation
from finai_api.services.certification_requirements import (
    validate_requirement_coverage,
    validate_requirements,
)
from finai_api.services.workspace import WorkspaceError


def ref():
    return VersionReference(resource_id=uuid4(), version_id=uuid4())


def fixture():
    material, policy, schema = ref(), ref(), ref()
    rows = {
        str(material.resource_id): {
            "version_id": material.version_id,
            "object_type": "SchemaDefinition",
        },
        str(policy.resource_id): {
            "version_id": policy.version_id,
            "object_type": "CertificationContract",
            "attributes": {
                "definition": {
                    "claim": "CANONICAL_DEFINITION_CONFORMANCE",
                    "evaluator": "canonical-structural-contract/v1",
                    "subject_type": "SchemaDefinition",
                    "required_checks": ["impact"],
                    "meaning": "Definition structural conformance",
                    "limitations": "Not accounting certification",
                }
            },
        },
    }
    item = ResourceMutation(
        object_type="SchemaDefinition",
        identity_key="test-consumer",
        display_name="Test",
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        attributes={
            "minimum_authority_state": "CERTIFIED",
            "certification_requirements": {
                str(material.resource_id): policy.model_dump(mode="json")
            },
        },
    )
    calls = []

    def target(identity, source, relation):
        calls.append((identity, source, relation))
        return rows[identity]

    return item, material, policy, schema, rows, calls, target


def test_schema_material_is_not_exempt_and_relations_are_exact():
    item, material, policy, schema, _, calls, target = fixture()
    requirements = validate_requirements(item, target, schema.version_id)
    validate_requirement_coverage(requirements, [material, policy, schema], schema.version_id)
    assert {call[2] for call in calls} == {
        "CERTIFICATION_POLICY:" + str(material.resource_id),
        "CERTIFICATION_SUBJECT:" + str(material.resource_id),
    }
    with pytest.raises(WorkspaceError):
        validate_requirement_coverage({}, [material, schema], schema.version_id)


@pytest.mark.parametrize(
    "attack", ["wrong_version", "wrong_type", "wrong_subject", "schema_control"]
)
def test_policy_or_material_cannot_be_relabelled_as_control(attack):
    item, material, policy, schema, rows, _, target = fixture()
    if attack == "wrong_version":
        rows[str(policy.resource_id)]["version_id"] = uuid4()
    elif attack == "wrong_type":
        rows[str(policy.resource_id)]["object_type"] = "SchemaDefinition"
    elif attack == "wrong_subject":
        rows[str(material.resource_id)]["object_type"] = "LegalEntity"
    else:
        rows[str(material.resource_id)]["version_id"] = schema.version_id
    with pytest.raises(WorkspaceError):
        validate_requirements(item, target, schema.version_id)


def test_coverage_rejects_missing_extraneous_and_conflicting_pins():
    item, material, policy, schema, _, _, target = fixture()
    requirements = validate_requirements(item, target)
    for pins in (
        [policy, schema],
        [material, schema],
        [material, policy, schema, ref()],
        [material, policy],
        [material, policy, schema, material.model_copy(update={"version_id": uuid4()})],
    ):
        with pytest.raises(WorkspaceError):
            validate_requirement_coverage(requirements, pins, schema.version_id)


def test_ambiguous_uuid_and_extra_policy_fields_are_rejected():
    item, material, policy, _, _, _, target = fixture()
    for mapping in (
        {str(material.resource_id).upper(): policy.model_dump(mode="json")},
        {str(material.resource_id): {**policy.model_dump(mode="json"), "skip": True}},
    ):
        item.attributes["certification_requirements"] = mapping
        with pytest.raises(WorkspaceError):
            validate_requirements(item, target)
