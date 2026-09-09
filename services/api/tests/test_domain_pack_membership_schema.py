"""Software schema capability does not publish or populate a company domain pack."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

import pytest

from finai_api.domain.ontology_catalog import platform_definitions
from finai_api.services.ontology_definition_validation import validate_definition
from finai_api.services.schema_compatibility import schema_compatibility
from finai_api.services.workspace import WorkspaceError


def pack_schema():
    return next(
        item["attributes"]
        for item in platform_definitions(UUID("805d8a32-d12b-4268-a236-b0b16e59da9f"))
        if item["object_type"] == "SchemaDefinition" and item["identity_key"] == "DomainPack"
    )


def test_membership_fields_keep_legacy_pack_schema_backward_compatible():
    current = pack_schema()
    legacy = deepcopy(current)
    for field, target in (
        ("membership_group_id", "ObjectTypeGroup"),
        ("membership_interface_id", "ObjectInterface"),
    ):
        spec = legacy["fields"].pop(field)
        assert spec["kind"] == "reference" and spec["target_type"] == target
        assert spec["required"] is False
    assert schema_compatibility("DomainPack", current, legacy)["compatibility"] == (
        "BACKWARD_COMPATIBLE"
    )
    assert current["fields"]["code"] == legacy["fields"]["code"]
    assert current["fields"]["version"] == legacy["fields"]["version"]


@pytest.mark.parametrize("field", [None, "membership_group_id", "membership_interface_id"])
def test_pack_accepts_legacy_or_single_membership_without_creating_another_registry(field):
    attributes = {"code": "fixture", "version": "1"}
    if field:
        attributes[field] = "11111111-1111-4111-8111-111111111111"
    item = SimpleNamespace(object_type="DomainPack", attributes=attributes)
    # Typed reference validation/pinning runs earlier in the shared publication path.
    validate_definition(item, {}, {}, lambda *_: pytest.fail("No second resolver is permitted"))


def test_pack_refuses_ambiguous_membership_even_when_references_share_identity():
    identity = "11111111-1111-4111-8111-111111111111"
    item = SimpleNamespace(
        object_type="DomainPack",
        attributes={"membership_group_id": identity, "membership_interface_id": identity},
    )
    with pytest.raises(WorkspaceError, match="at most one definition") as failure:
        validate_definition(item, {}, {}, lambda *_: {})
    assert failure.value.status == 422
