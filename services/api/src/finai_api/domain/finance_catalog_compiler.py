"""Compile declarative finance definitions onto the existing canonical ontology kernel.

The output contains platform definitions only. Company constructions and descriptive
Function/Action requirements never become approved resources through compilation.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid5

from finai_api.domain.finance_catalog_loader import (
    CatalogProperty,
    load_finance_catalog,
    validate_finance_catalog,
)
from finai_api.domain.object_sets import ObjectSetQuery, PropertyFilter

TYPE_ALIASES = {"CanonicalJournalEntry": "JournalEntry", "CanonicalJournalLine": "JournalLine"}
FIELD_ALIASES = {
    "LocalAccount": {"code": "account_code"},
    "GroupAccount": {"code": "account_code"},
    "Currency": {"iso_code": "code"},
    "FiscalPeriod": {"start_date": "starts_on", "end_date": "ends_on"},
    "LegalEntity": {"registration_id": "registration_code"},
    "SourceEvidence": {"bytes_hash": "sha256"},
    "JournalLine": {
        "entry_id": "journal_id", "local_account_id": "account_id",
        "dimension_bindings": "dimensions",
    },
}
METADATA = {
    "id": "resource_id", "type": "object_type", "display_name": "display_name",
    "version_id": "version_id", "valid_from": "valid_from", "valid_to": "valid_to",
}
UNRESOLVED_METADATA = {
    "tenant_id", "authority_state", "epistemic", "known_at", "recorded_at",
    "supersedes_version_id",
}
REFERENCES = {
    "legal_entity_id": "LegalEntity", "ledger_id": "Ledger", "period_id": "FiscalPeriod",
    "scenario_version_id": "ScenarioVersion", "chart_id": "LocalChartOfAccounts",
    "local_account_id": "LocalAccount", "group_account_id": "GroupAccount",
    "fs_item_id": "FinancialStatementItem", "reporting_line_id": "ReportingLine",
    "entry_id": "JournalEntry", "evidence_id": "SourceEvidence",
    "intercompany_partner_id": "LegalEntity", "restricted_entity_id": "LegalEntity",
    "mapping_version_id": "AccountMappingVersion", "party_id": "Party",
    "contract_id": "Contract", "product_id": "Product", "department_id": "Department",
    "cost_article_id": "CostArticle", "cash_flow_article_id": "CashFlowArticle",
    "tax_id": "Tax", "asset_id": "Asset", "employee_id": "Employee",
    "warehouse_id": "Warehouse", "region_id": "Region", "channel_id": "Channel",
    "lot_id": "Lot", "budget_article_id": "BudgetArticle", "unit_id": "Unit",
    "parent_account_id": "LocalAccount", "parent_department_id": "Department",
    "location_id": "Location", "from_entity_id": "LegalEntity", "to_entity_id": "LegalEntity",
    "source_document_id": "SourceRecord",
}
SEMANTICS = {
        "text": "Text", "identifier": "Identifier", "decimal": "Amount", "date": "Date",
    "datetime": "Time", "boolean": "Flag", "integer": "Count",
    "reference": "CanonicalReference", "definition": "OntologyDefinition",
}


@dataclass(frozen=True)
class CatalogCompilation:
    definitions: list[dict[str, Any]]
    manifest: dict[str, Any]
    diagnostics: list[dict[str, Any]]


def _hash(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def runtime_type(name: str) -> str:
    return TYPE_ALIASES.get(name, name)


def runtime_field(object_type: str, field: str) -> str:
    return FIELD_ALIASES.get(runtime_type(object_type), {}).get(field, field)


def _field_shape(prop: CatalogProperty) -> tuple[str, str | None, dict[str, Any]]:
    value = prop.value_type
    constraints: dict[str, Any] = {}
    target = REFERENCES.get(prop.name)
    if prop.name.endswith("currency_id") or (
        prop.name.startswith("currency_") and prop.name.endswith("_id")
    ):
        target = "Currency"
    kind = {
        "integer": "integer", "boolean": "boolean", "decimal_string": "decimal",
        "date": "date", "datetime": "datetime", "sha256": "identifier",
        "identifier": "identifier",
    }.get(value, "text")
    if target is not None:
        kind = "reference"
    elif prop.name.endswith("_id"):
        kind = "identifier"
    if value.endswith("[]"):
        kind, target = "definition", None
        constraints = {
            "type": "array", "maxItems": 1000,
            "items": {"type": "object" if value == "DimensionBinding[]" else "string"},
        }
    elif value.startswith("enum:"):
        constraints["enum"] = value[5:].split("|")
    elif value.startswith("const:"):
        constraints["const"] = value[6:]
    elif value == "sha256":
        constraints["pattern"] = "^[a-f0-9]{64}$"
    if prop.pattern is not None:
        constraints["pattern"] = prop.pattern
    return kind, target, constraints


def compile_finance_catalog(
    tenant: UUID,
    base_definitions: list[dict[str, Any]],
    *,
    catalog: dict[str, Any] | None = None,
) -> CatalogCompilation:
    # Local import allows ontology_catalog.platform_definitions to call this compiler.
    from finai_api.domain.ontology_catalog import CATALOG_NAMESPACE, canonical_id
    from finai_api.domain.resource_metadata import METADATA_FIELDS

    raw = load_finance_catalog() if catalog is None else catalog
    model = validate_finance_catalog(raw)
    if model.status != "SPEC_ACCEPTED":
        raise ValueError("Only a SPEC_ACCEPTED catalog may compile platform definitions")
    type_names = [runtime_type(item.api_name) for item in model.object_types]
    if len(type_names) != len(set(type_names)):
        raise ValueError("Catalog object aliases collide on the same runtime identity")
    definitions = deepcopy(base_definitions)
    index = {(item["object_type"], item["identity_key"]): item for item in definitions}
    if len(index) != len(definitions):
        raise ValueError("Base definitions contain duplicate canonical identities")
    permitted = {
        "SemanticContract", "SchemaDefinition", "LinkType", "ObjectInterface",
        "ObjectTypeImplementation", "ObjectTypeGroup", "ObjectSetDefinition",
        "DerivedProperty", "FactContract", "ObjectBinding",
    }
    if any(item["object_type"] not in permitted for item in definitions):
        raise ValueError("Compiler baseline must contain platform definitions, never company rows")
    diagnostics: list[dict[str, Any]] = []
    requirements: dict[str, Any] = {}

    def diagnostic(code: str, subject: str, detail: Any) -> None:
        diagnostics.append({"code": code, "subject": subject, "detail": detail})

    def put(kind: str, name: str, attributes: dict[str, Any]) -> dict[str, Any]:
        key = (kind, name)
        if key in index:
            raise ValueError(f"Compiled definition collides with baseline: {kind}/{name}")
        item = {
            "object_type": kind, "identity_key": name, "display_name": name,
            "attributes": attributes,
        }
        definitions.append(item)
        index[key] = item
        return item

    interfaces = {item.api_name: item for item in model.interfaces}
    members: dict[str, list[str]] = {name: [] for name in interfaces}
    object_props: dict[str, dict[str, CatalogProperty]] = {}
    for item in model.object_types:
        name = runtime_type(item.api_name)
        props: dict[str, CatalogProperty] = {}
        for interface in item.implements:
            members[interface].append(name)
            props.update({prop.name: prop for prop in interfaces[interface].properties})
        props.update({prop.name: prop for prop in item.properties})
        object_props[name] = props
        field_names = [runtime_field(name, key) for key in props]
        if len(field_names) != len(set(field_names)):
            raise ValueError(f"Catalog property aliases collide on {name}")
        old = index.get(("SchemaDefinition", name))
        fields = old["attributes"]["fields"] if old else {}
        for property_name, prop in props.items():
            subject = f"{name}.{property_name}"
            if property_name in METADATA:
                continue
            if property_name in UNRESOLVED_METADATA:
                diagnostic("NATIVE_METADATA_REQUIRES_EXPLICIT_SEMANTICS", subject, prop.value_type)
                continue
            if prop.derived:
                diagnostic("DERIVED_EXPRESSION_REQUIRED", subject, "No expression supplied")
                continue
            field = runtime_field(name, property_name)
            kind, target, constraints = _field_shape(prop)
            semantic = SEMANTICS[kind]
            if ("SemanticContract", semantic) not in index:
                raise ValueError(f"Missing baseline semantic contract: {semantic}")
            spec = {
                "field_id": str(uuid5(CATALOG_NAMESPACE, f"field:{name}:{field}")),
                "semantic_id": str(canonical_id(tenant, "SemanticContract", semantic)),
                "kind": kind, "required": prop.required if old is None else False,
                "target_type": target, "deprecated": False,
            }
            if constraints:
                spec["constraints"] = constraints
            requirements[subject] = {
                "runtime_field": field, "required": prop.required,
                "value_type": prop.value_type, "constraints": constraints,
            }
            if field in fields:
                before = fields[field]
                if before["kind"] != kind or before.get("target_type") != target:
                    diagnostic("EXISTING_FIELD_REPRESENTATION_PRESERVED", subject, before["kind"])
                if constraints and before.get("constraints") != constraints:
                    diagnostic("CONSTRAINT_MIGRATION_REQUIRED", subject, constraints)
                continue
            fields[field] = spec
            if old is not None and prop.required:
                diagnostic("REQUIRED_FIELD_MIGRATION_REQUIRED", subject, field)
        if old is None:
            if not fields:
                raise ValueError(f"Object type has no storable properties: {name}")
            put("SchemaDefinition", name, {
                "fields": fields, "additional_fields": False,
                "compatibility": "BACKWARD", "version": model.catalog_version,
            })

    for link in model.link_types:
        def endpoints(name: str) -> list[str]:
            result = sorted(set(members[name])) if name in members else [runtime_type(name)]
            if not result:
                raise ValueError(f"Link interface has no object implementations: {name}")
            return result

        sources, targets = endpoints(link.from_type), endpoints(link.to_type)
        old = index.get(("LinkType", link.api_name))
        attributes = {
            "sources": sources, "targets": targets,
            "meaning": link.constraint or link.api_name.replace("_", " ").lower(),
        }
        if old is None:
            put("LinkType", link.api_name, attributes)
        elif (
            not set(sources).issubset(old["attributes"]["sources"])
            or not set(targets).issubset(old["attributes"]["targets"])
        ):
            diagnostic("EXISTING_LINK_ENDPOINTS_PRESERVED", link.api_name, attributes)
        diagnostic("LINK_CARDINALITY_REVIEW_REQUIRED", link.api_name, link.cardinality)

    for name, interface_def in interfaces.items():
        fields = {}
        mappings: dict[str, dict[str, str]] = {member: {} for member in sorted(set(members[name]))}
        for prop in interface_def.properties:
            if prop.name in UNRESOLVED_METADATA:
                continue
            if prop.name in METADATA:
                fields[prop.name] = dict(METADATA_FIELDS[METADATA[prop.name]])
                for mapping in mappings.values():
                    mapping[prop.name] = "meta:" + METADATA[prop.name]
                continue
            candidates = []
            for member in mappings:
                field = runtime_field(member, prop.name)
                spec = index[("SchemaDefinition", member)]["attributes"]["fields"].get(field)
                candidates.append((member, field, spec))
            shapes = {(spec["kind"], spec.get("target_type")) for _, _, spec in candidates if spec}
            if len(shapes) != 1 or any(spec is None for _, _, spec in candidates):
                diagnostic("INTERFACE_PROPERTY_REPRESENTATION_CONFLICT", f"{name}.{prop.name}",
                           "Explicit per-type adapter is required; property is not projected")
                continue
            kind, target = next(iter(shapes))
            fields[prop.name] = {
                "kind": kind, "required": all(spec["required"] for _, _, spec in candidates),
            }
            if target:
                fields[prop.name]["target_type"] = target
            for member, field, _ in candidates:
                mappings[member][prop.name] = field
        put("ObjectInterface", name, {"definition": {"fields": fields}})
        for member, mapping in mappings.items():
            put("ObjectTypeImplementation", f"finance.{member}.{name}", {
                "interface_id": str(canonical_id(tenant, "ObjectInterface", name)),
                "schema_id": str(canonical_id(tenant, "SchemaDefinition", member)),
                "definition": {"fields": mapping},
            })

    groups: dict[str, list[str]] = {}
    for item in model.object_types:
        groups.setdefault(item.type_group, []).append(runtime_type(item.api_name))
    for name, types in groups.items():
        put("ObjectTypeGroup", name, {"definition": {"types": sorted(set(types))}})

    set_parameters: dict[str, list[str]] = {}
    for query_set in model.object_sets:
        name = runtime_type(query_set.base_type)
        fields = index[("SchemaDefinition", name)]["attributes"]["fields"]
        filters: list[PropertyFilter] = []
        parameters: list[str] = []
        blocked = False
        for condition in query_set.default_filters:
            if condition == "tenant":
                continue  # Server-owned tenant isolation is mandatory for every Object Set.
            if condition == "authority_state=ACCEPTED":
                diagnostic("NATIVE_APPROVED_QUERY", query_set.api_name,
                           "Kernel queries APPROVED versions; catalog label is not a new state")
                continue
            if "=" in condition:
                key, value = condition.split("=", 1)
                key = runtime_field(name, key)
                if key not in fields:
                    raise ValueError(f"Unknown Object Set filter field: {name}.{key}")
                filters.append(PropertyFilter(field=key, value=value))
            elif condition.endswith(" unknown"):
                key = runtime_field(name, condition.removesuffix(" unknown"))
                if key not in fields:
                    raise ValueError(f"Unknown Object Set filter field: {name}.{key}")
                if fields[key]["required"]:
                    blocked = True
                    diagnostic("CANDIDATE_INTAKE_SET_REQUIRED", query_set.api_name,
                               "Required canonical references cannot represent unclassified rows")
                else:
                    filters.append(PropertyFilter(field=key, value=None))
            else:
                key = runtime_field(name, condition)
                if key not in fields:
                    raise ValueError(f"Unknown Object Set parameter: {name}.{key}")
                parameters.append(key)
        query = ObjectSetQuery(object_type=name, filters=filters)
        if blocked or parameters:
            query = query.model_copy(update={"resource_ids": []})
        if parameters:
            set_parameters[query_set.api_name] = parameters
            diagnostic("OBJECT_SET_PARAMETER_REQUIRED", query_set.api_name, parameters)
        put("ObjectSetDefinition", query_set.api_name,
            {"definition": query.model_dump(mode="json")})

    # Compile executable definition families into the same governed resource
    # store as schemas, links and object sets. The catalog contains no company
    # rows; publication still goes through the normal independent review path.
    from finai_api.domain.ontology_definitions import (
        BindingDefinition,
        DerivedDefinition,
        FactContract,
    )

    def schema_resource_id(schema_name: str) -> str:
        runtime_name = runtime_type(schema_name)
        if ("SchemaDefinition", runtime_name) not in index:
            raise ValueError(f"Definition schema is not compiled: {schema_name}")
        return str(canonical_id(tenant, "SchemaDefinition", runtime_name))

    for derived in model.derived_properties:
        schema_name = runtime_type(derived.schema_type)
        derived_definition = DerivedDefinition.model_validate(derived.definition)
        put("DerivedProperty", derived.api_name, {
            "schema_id": schema_resource_id(schema_name),
            "definition": derived_definition.model_dump(mode="json"),
        })

    for fact in model.fact_contracts:
        schema_name = runtime_type(fact.schema_type)
        fact_definition = FactContract.model_validate(fact.definition)
        put("FactContract", fact.api_name, {
            "schema_id": schema_resource_id(schema_name),
            "definition": fact_definition.model_dump(mode="json"),
        })

    for binding in model.source_bindings:
        binding_definition = BindingDefinition.model_validate(binding.definition)
        put("ObjectBinding", binding.api_name, {
            "source_schema_id": schema_resource_id(binding.source_schema),
            "target_schema_id": schema_resource_id(binding.target_schema),
            "definition": binding_definition.model_dump(mode="json"),
        })

    for function in model.functions:
        diagnostic("FUNCTION_IMPLEMENTATION_REQUIRED", function.api_name, function.model_dump())
    for action in model.actions:
        diagnostic("ACTION_BINDING_REQUIRED", action.api_name, action.model_dump())

    # Resolve every compiled schema reference, including aliases, before publication.
    for compiled_definition in definitions:
        if compiled_definition["object_type"] != "SchemaDefinition":
            continue
        for field in compiled_definition["attributes"]["fields"].values():
            target = field.get("target_type")
            # Bootstrap meta schemas are built into the kernel, not seeded definitions.
            if (
                target not in (None, "*", "SchemaDefinition", "SemanticContract", "LinkType")
                and ("SchemaDefinition", target) not in index
            ):
                raise ValueError(f"Unresolved runtime reference target: {target}")
    manifest = {
        "catalog_id": model.catalog_id, "catalog_version": model.catalog_version,
        "catalog_sha256": _hash(raw), "coa_pin_sha256": model.coa_pin_sha256,
        "catalog_hash_semantics": "SORTED_COMPACT_JSON_UTF8",
        "definitions_sha256": _hash(definitions), "type_aliases": TYPE_ALIASES,
        "field_aliases": FIELD_ALIASES, "property_requirements": requirements,
        "derived_properties": [item.api_name for item in model.derived_properties],
        "fact_contracts": [item.api_name for item in model.fact_contracts],
        "source_bindings": [item.api_name for item in model.source_bindings],
        "object_set_parameters": set_parameters,
        "resources": [{
            "object_type": item["object_type"], "identity_key": item["identity_key"],
            "resource_id": str(canonical_id(tenant, item["object_type"], item["identity_key"])),
            "content_sha256": _hash(item),
        } for item in definitions],
        "functions_executable": False, "company_instances_created": 0,
    }
    return CatalogCompilation(definitions, manifest, diagnostics)


def bind_catalog_object_set(
    compilation: CatalogCompilation, name: str, parameters: dict[str, str]
) -> ObjectSetQuery:
    """Bind a parameterized template without ever widening an unbound saved set."""
    required = compilation.manifest["object_set_parameters"].get(name, [])
    if set(parameters) != set(required):
        raise ValueError("Object Set parameters must match its declared parameters exactly")
    spec = next((item for item in compilation.definitions
                 if item["object_type"] == "ObjectSetDefinition"
                 and item["identity_key"] == name), None)
    if spec is None:
        raise ValueError("Unknown catalog Object Set")
    query = ObjectSetQuery.model_validate(spec["attributes"]["definition"])
    if not required:
        return query
    filters = list(query.filters)
    for field in required:
        value = parameters[field]
        if field.endswith("_id"):
            value = str(UUID(value))
        filters.append(PropertyFilter(field=field, value=value))
    return query.model_copy(update={"filters": filters, "resource_ids": None})
