"""Finance compilation preserves kernel authority while exposing executable definitions."""

import json
from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID, uuid5

import pytest

from finai_api.domain.finance_catalog_compiler import (
    bind_catalog_object_set,
    compile_finance_catalog,
)
from finai_api.domain.finance_catalog_loader import (
    load_candidate_construction,
    load_finance_catalog,
    validate_finance_catalog,
)
from finai_api.domain.ontology_catalog import canonical_id, platform_definitions
from finai_api.domain.resources import ResourceMutation
from finai_api.services.ontology_definition_validation import validate_definition
from finai_api.services.schema_compatibility import schema_compatibility

TENANT = UUID("31ec0c66-14ca-4780-b361-d26afc2d3c46")


def compile_catalog():
    return compile_finance_catalog(TENANT, platform_definitions(TENANT))


def indexed(compilation):
    return {(item["object_type"], item["identity_key"]): item for item in compilation.definitions}


def test_preserves_existing_identity_field_and_constraints_without_company_rows():
    original = platform_definitions(TENANT)
    retained = deepcopy(original)
    compilation = compile_finance_catalog(TENANT, original)
    result = indexed(compilation)
    assert original == retained
    for old in original:
        item = result[old["object_type"], old["identity_key"]]
        if old["object_type"] == "SchemaDefinition":
            for field, specification in old["attributes"]["fields"].items():
                assert item["attributes"]["fields"][field] == specification
            assert schema_compatibility(
                item["identity_key"], item["attributes"], old["attributes"]
            )["compatibility"] == "BACKWARD_COMPATIBLE"
    assert ("SchemaDefinition", "CanonicalJournalLine") not in result
    account = result["SchemaDefinition", "LocalAccount"]["attributes"]["fields"]
    assert "account_code" in account and "code" not in account
    assert "tenant_id" not in account and "authority_state" not in account
    assert compilation.manifest["company_instances_created"] == 0
    assert all(row["object_type"] != "LocalAccount" for row in compilation.definitions)


def test_deterministic_ids_hashes_and_tenant_isolation():
    first, second = compile_catalog(), compile_catalog()
    assert first == second
    assert first.manifest["definitions_sha256"]
    other = compile_finance_catalog(UUID(int=2), platform_definitions(UUID(int=2)))
    ids = {row["resource_id"] for row in first.manifest["resources"]}
    assert not ids.intersection(row["resource_id"] for row in other.manifest["resources"])
    entry = next(row for row in first.manifest["resources"]
                 if row["identity_key"] == "LocalAccount")
    assert entry["resource_id"] == str(canonical_id(TENANT, "SchemaDefinition", "LocalAccount"))


def test_every_definition_validates_through_shared_runtime_contract_without_database():
    compilation = compile_catalog()
    loaded = {}
    for item in compilation.definitions:
        identity = canonical_id(TENANT, item["object_type"], item["identity_key"])
        loaded[str(identity)] = {
            **item, "resource_id": str(identity), "version_id": str(uuid5(identity, "test")),
        }
        if item["object_type"] == "SchemaDefinition":
            schema_compatibility(item["identity_key"], item["attributes"])
    schemas = {row["identity_key"]: key for key, row in loaded.items()
               if row["object_type"] == "SchemaDefinition"}
    links = {row["identity_key"]: key for key, row in loaded.items()
             if row["object_type"] == "LinkType"}

    def target(identity, *_):
        return loaded[str(identity)]

    for item in compilation.definitions:
        mutation = ResourceMutation(
            resource_id=canonical_id(TENANT, item["object_type"], item["identity_key"]),
            valid_from=datetime.now(UTC), **item,
        )
        validate_definition(mutation, schemas, links, target)


def test_interfaces_map_metadata_and_named_type_groups_are_registered():
    result = indexed(compile_catalog())
    marker = result["ObjectInterface", "IQueryable"]
    assert marker["attributes"]["definition"]["fields"] == {}
    implementation = result["ObjectTypeImplementation", "finance.LocalAccount.IResource"]
    assert implementation["attributes"]["definition"]["fields"]["id"] == "meta:resource_id"
    group = result["ObjectTypeGroup", "g8.finance"]["attributes"]["definition"]["types"]
    assert "JournalLine" in group and "CanonicalJournalLine" not in group


def test_constraints_compile_on_new_fields_without_changing_legacy_required_fields():
    result = indexed(compile_catalog())
    kind = result["SchemaDefinition", "ScenarioVersion"]["attributes"]["fields"]["kind"]
    assert kind["constraints"]["enum"] == ["ACTUAL", "BUDGET", "FORECAST", "ADJUSTMENT"]
    account = result["SchemaDefinition", "LocalAccount"]["attributes"]["fields"]
    assert account["currency_flag"]["kind"] == "boolean"
    sources = account["source_record_ids"]
    assert sources["kind"] == "definition" and sources["constraints"]["type"] == "array"


def test_parameterized_sets_fail_closed_until_exact_binding():
    compiled = compile_catalog()
    saved = indexed(compiled)["ObjectSetDefinition", "OS.Accounts.Chart"]
    assert saved["attributes"]["definition"]["resource_ids"] == []
    chart = str(UUID(int=9))
    query = bind_catalog_object_set(compiled, "OS.Accounts.Chart", {"chart_id": chart})
    assert query.resource_ids is None
    assert query.filters[0].field == "chart_id" and query.filters[0].value == chart
    with pytest.raises(ValueError, match="parameters"):
        bind_catalog_object_set(compiled, "OS.Accounts.Chart", {})
    with pytest.raises(ValueError):
        bind_catalog_object_set(compiled, "OS.Accounts.Chart", {"chart_id": "unbound"})
    unknown = indexed(compiled)["ObjectSetDefinition", "OS.Facts.NoAccountCode"]
    assert unknown["attributes"]["definition"]["resource_ids"] == []


def test_descriptive_functions_and_actions_are_requirements_not_executable_seeds():
    compilation = compile_catalog()
    assert compilation.manifest["functions_executable"] is False
    assert not {"FunctionDefinition", "ActionDefinition"}.intersection(
        item["object_type"] for item in compilation.definitions
    )
    classifier = [item for item in compilation.diagnostics
                  if item["subject"] == "fn.classify_fact"]
    assert classifier[0]["code"] == "FUNCTION_IMPLEMENTATION_REQUIRED"


def test_full_finance_depth_compiles_derived_facts_and_source_binding_resources():
    result = indexed(compile_catalog())
    derived = result["DerivedProperty", "derived.AccountPeriodFact.net_movement"]
    assert derived["attributes"]["schema_id"] == str(
        canonical_id(TENANT, "SchemaDefinition", "AccountPeriodFact")
    )
    assert derived["attributes"]["definition"]["expression"]["op"] == "subtract"
    fact = result["FactContract", "fact.AccountPeriodFact.closing"]
    assert fact["attributes"]["definition"]["aggregation"] == "closing_balance"
    assert "period_ends_on" in fact["attributes"]["definition"]["grain"]
    binding = result["ObjectBinding", "binding.SourceAccountDefinition.LocalAccount"]
    assert binding["attributes"]["source_schema_id"] == str(
        canonical_id(TENANT, "SchemaDefinition", "SourceAccountDefinition")
    )
    assert binding["attributes"]["definition"]["fields"]


@pytest.mark.parametrize("change", [
    lambda value: value["object_types"].append(deepcopy(value["object_types"][0])),
    lambda value: value["link_types"][0].update(to_type="InventedType"),
    lambda value: value["object_types"][0]["implements"].append("MissingInterface"),
    lambda value: value["object_types"][0]["properties"][0].update(value_type="moneyish"),
    lambda value: value["object_types"][0]["properties"][0].update(required="true"),
    lambda value: value["actions"][0].update(nyx_may_execute=True),
    lambda value: value["object_types"][0].update(title_property="does_not_exist"),
    lambda value: value["object_types"][0]["properties"][0].update(pattern="["),
    lambda value: value.update(catalog_version=True),
    lambda value: value.update(company_rows=[]),
])
def test_malformed_catalogs_are_rejected(change):
    value = load_finance_catalog()
    change(value)
    with pytest.raises(ValueError):
        validate_finance_catalog(value)


def test_unknown_set_predicate_and_duplicate_json_key_are_rejected(tmp_path):
    value = load_finance_catalog()
    value["object_sets"][0]["default_filters"] = ["invented=yes"]
    with pytest.raises(ValueError, match="filter field"):
        compile_finance_catalog(TENANT, platform_definitions(TENANT), catalog=value)
    path = tmp_path / "packages/contracts/catalog/ontology-catalog.g8-finance.v1.json"
    path.parent.mkdir(parents=True)
    text = json.dumps(load_finance_catalog())
    path.write_text(text.replace(
        '"catalog_version": 1', '"catalog_version": 1, "catalog_version": 2'
    ))
    with pytest.raises(ValueError, match="Duplicate JSON key"):
        load_finance_catalog(tmp_path)


def test_candidate_loader_is_allowlisted_and_does_not_promote():
    candidate = load_candidate_construction("g8.candidate.coa-406")
    assert candidate["status"] == "CANDIDATE" and len(candidate["mutations"]) == 406
    assert load_candidate_construction("g8.candidate.seg-entities")["not_catalog"] is True
    with pytest.raises(ValueError, match="Unknown candidate"):
        load_candidate_construction("../../ontology_catalog.py")
