"""Interface substitution preserves business meaning and canonical endpoint types."""

import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from finai_api.domain.ontology_definitions import InterfaceField
from finai_api.domain.resources import ResourceMutation
from finai_api.services.ontology_definition_validation import validate_definition
from finai_api.services.workspace import WorkspaceError


def mutation(kind, fields, **attributes):
    return ResourceMutation(
        object_type=kind,
        identity_key="synthetic-interface:" + uuid4().hex,
        display_name="SYNTHETIC interface acceptance",
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        evidence_class="REFERENCE_TEMPLATE",
        attributes={"definition": {"fields": fields}, **attributes},
    )


def implementation(required, fields, mapping):
    interface_id, schema_id = str(uuid4()), str(uuid4())
    item = mutation(
        "ObjectTypeImplementation", mapping, interface_id=interface_id, schema_id=schema_id
    )
    objects = {
        interface_id: {"attributes": {"definition": {"fields": required}}},
        schema_id: {"attributes": {"fields": fields}},
    }
    calls = []

    def target(identifier, source, relation):
        calls.append((identifier, source, relation))
        return objects[identifier]

    validate_definition(item, {}, {}, target)
    assert calls == [
        (interface_id, str(item.resource_id), "IMPLEMENTS"),
        (schema_id, str(item.resource_id), "IMPLEMENTATION_SCHEMA"),
    ]


def test_company_reference_cannot_be_substituted_with_account_reference():
    semantic = str(uuid4())
    company = {
        "kind": "reference",
        "required": True,
        "semantic_id": semantic,
        "target_type": "LegalEntity",
    }
    with pytest.raises(WorkspaceError, match="target_type"):
        implementation(
            {"company": company},
            {"account_id": {**company, "target_type": "LocalAccount"}},
            {"company": "account_id"},
        )


def test_same_storage_kind_does_not_make_different_semantics_substitutable():
    code = {"kind": "identifier", "required": True, "semantic_id": str(uuid4())}
    with pytest.raises(WorkspaceError, match="semantic_id"):
        implementation(
            {"account_code": code},
            {"tax_code": {**code, "semantic_id": str(uuid4())}},
            {"account_code": "tax_code"},
        )
    with pytest.raises(WorkspaceError, match="semantic_id"):
        implementation(
            {"account_code": code},
            {"source_code": {"kind": "identifier", "required": True}},
            {"account_code": "source_code"},
        )


def test_different_source_field_names_share_one_interface_semantic_identity():
    company = {
        "kind": "reference",
        "required": True,
        "semantic_id": str(uuid4()),
        "target_type": "LegalEntity",
    }
    for source_field in ("legal_entity_id", "company_id"):
        implementation({"company": company}, {source_field: company}, {"company": source_field})


def test_legacy_interface_remains_valid_without_claiming_semantic_constraints():
    legacy = {"kind": "identifier", "required": True}
    assert InterfaceField.model_validate(legacy).semantic_id is None
    implementation({"code": legacy}, {"source_code": legacy}, {"code": "source_code"})
    implementation(
        {"code": {"kind": "identifier"}}, {"source_code": legacy}, {"code": "source_code"}
    )
    for incompatible in (
        {"kind": "decimal", "required": True},
        {"kind": "identifier", "required": False},
    ):
        with pytest.raises(WorkspaceError):
            implementation({"code": legacy}, {"source_code": incompatible}, {"code": "source_code"})
    with pytest.raises(WorkspaceError, match="every declared"):
        implementation(
            {"code": legacy, "other": legacy}, {"source_code": legacy}, {"code": "source_code"}
        )


def test_interface_semantics_and_endpoint_use_shared_dependency_resolver():
    semantic_id, schema_id = str(uuid4()), str(uuid4())
    item = mutation(
        "ObjectInterface",
        {
            "company": {
                "kind": "reference",
                "semantic_id": semantic_id,
                "target_type": "LegalEntity",
            }
        },
    )
    calls = []

    def target(identifier, source, relation):
        calls.append((identifier, source, relation))
        return {"object_type": "SemanticContract", "attributes": {"kind": "reference"}}

    validate_definition(item, {"LegalEntity": schema_id}, {}, target)
    assert calls == [
        (semantic_id, str(item.resource_id), "INTERFACE_SEMANTIC:company"),
        (schema_id, str(item.resource_id), "DEFINITION_TYPE:LegalEntity"),
    ]
    with pytest.raises(WorkspaceError, match="Unknown ontology type"):
        validate_definition(item, {}, {}, target)


@pytest.mark.parametrize(
    "object_type,kind", [("LegalEntity", "reference"), ("SemanticContract", "identifier")]
)
def test_interface_rejects_non_semantic_identity_and_wrong_semantic_kind(object_type, kind):
    item = mutation(
        "ObjectInterface",
        {
            "company": {
                "kind": "reference",
                "semantic_id": str(uuid4()),
            }
        },
    )
    with pytest.raises(WorkspaceError, match="semantic contract"):
        validate_definition(
            item,
            {},
            {},
            lambda *_: {
                "object_type": object_type,
                "attributes": {"kind": kind},
            },
        )


def test_endpoint_constraints_only_apply_to_typed_reference_fields():
    with pytest.raises(ValidationError, match="Only reference"):
        InterfaceField(kind="identifier", target_type="LegalEntity")
    with pytest.raises(ValidationError):
        InterfaceField(kind="reference", target_type="*")
    with pytest.raises(ValidationError):
        InterfaceField(kind="identifier", semantic_id="account-code")


@pytest.mark.skipif(
    os.environ.get("G8_BINDING_DB_TEST") != "1", reason="Opt-in retained DB acceptance"
)
def test_retained_interface_pins_and_rejects_cross_company_account_implementation():
    from finai_api.domain.authority import ExactScope
    from finai_api.domain.ontology_catalog import canonical_id
    from finai_api.domain.resources import ResourceProposal, ResourceReview
    from finai_api.domain.review import Principal
    from finai_api.services import ontology_definitions, resources

    tenant = UUID("805d8a32-d12b-4268-a236-b0b16e59da9f")
    operator = Principal(
        actor_id="synthetic-interface-operator",
        display_name="Synthetic interface operator",
        scope=ExactScope(
            tenant_id=tenant,
            legal_entity_id="synthetic-interface-" + uuid4().hex,
            period="2026-08",
            currency="GEL",
        ),
        permissions=("ontology_read", "ontology_admin", "ontology_propose", "ontology_review"),
    )
    reviewer = operator.model_copy(update={"actor_id": "synthetic-interface-reviewer"})
    interface = mutation(
        "ObjectInterface",
        {
            "company": {
                "kind": "reference",
                "required": True,
                "semantic_id": str(canonical_id(tenant, "SemanticContract", "CanonicalReference")),
                "target_type": "LegalEntity",
            }
        },
    )

    def proposal(items):
        return ResourceProposal(
            title="SYNTHETIC interface substitution acceptance",
            rationale="Isolated non-authentic canonical interface semantic acceptance",
            access_entity=operator.scope.legal_entity_id,
            mutations=items,
        )

    initial = proposal([interface])
    resources.propose(operator, initial)
    resources.review(
        reviewer,
        initial.proposal_id,
        ResourceReview(
            decision="APPROVED",
            rationale="Retain synthetic interface dependency acceptance",
        ),
    )
    retained = ontology_definitions.definition(operator, interface.resource_id)
    pins = {p["relation"]: p for p in retained["dependencies"]}
    assert str(pins["INTERFACE_SEMANTIC:company"]["resource_id"]) == str(
        canonical_id(tenant, "SemanticContract", "CanonicalReference")
    )
    assert str(pins["DEFINITION_TYPE:LegalEntity"]["resource_id"]) == str(
        canonical_id(tenant, "SchemaDefinition", "LegalEntity")
    )
    assert all(
        pins[key]["version_id"]
        for key in (
            "INTERFACE_SEMANTIC:company",
            "DEFINITION_TYPE:LegalEntity",
        )
    )
    schema_id = str(canonical_id(tenant, "SchemaDefinition", "LocalChartOfAccounts"))
    valid = mutation(
        "ObjectTypeImplementation",
        {"company": "legal_entity_id"},
        interface_id=str(interface.resource_id),
        schema_id=schema_id,
    )
    company = ResourceMutation(
        object_type="LegalEntity",
        identity_key="synthetic:" + uuid4().hex,
        display_name="SYNTHETIC interface company",
        attributes={},
        valid_from=interface.valid_from,
        evidence_class="REFERENCE_TEMPLATE",
    )
    chart = ResourceMutation(
        object_type="LocalChartOfAccounts",
        identity_key="synthetic:" + uuid4().hex,
        display_name="SYNTHETIC interface chart",
        attributes={"legal_entity_id": str(company.resource_id), "code": "SYNTHETIC"},
        valid_from=interface.valid_from,
        evidence_class="REFERENCE_TEMPLATE",
    )
    valid_proposal = proposal([valid, company, chart])
    resources.propose(operator, valid_proposal)
    resources.review(
        reviewer,
        valid_proposal.proposal_id,
        ResourceReview(
            decision="APPROVED",
            rationale="Retain valid company reference implementation",
        ),
    )
    assert resources.get_resource(operator, valid.resource_id)["resource"]["attributes"][
        "definition"
    ] == {
        "fields": {"company": "legal_entity_id"},
    }
    reader = operator.model_copy(update={"permissions": ("ontology_read",)})
    result = ontology_definitions.run_group(reader, interface.resource_id, 0, 20)
    assert len(result["interface_values"]) == 1
    value = result["interface_values"][0]
    assert str(value["object_id"]) == str(chart.resource_id)
    assert value["status"] == "AVAILABLE"
    assert value["values"] == {"company": str(company.resource_id)}
    retained_mapping = ontology_definitions.definition(operator, valid.resource_id)
    mapped_schema = next(
        pin for pin in retained_mapping["dependencies"] if pin["relation"] == "FIELD:schema_id"
    )
    assert str(result["objects"][0]["schema_version_id"]) == str(mapped_schema["version_id"])
    assert str(value["implementation_version_id"]) == str(retained_mapping["version_id"])
    assert str(result["definition_version_id"]) == str(retained["version_id"])
    invalid = mutation(
        "ObjectTypeImplementation",
        {"company": "debit_account_id"},
        interface_id=str(interface.resource_id),
        schema_id=str(canonical_id(tenant, "SchemaDefinition", "SourceJournalMovement")),
    )
    with pytest.raises(WorkspaceError, match="target_type"):
        resources.propose(operator, proposal([invalid]))
