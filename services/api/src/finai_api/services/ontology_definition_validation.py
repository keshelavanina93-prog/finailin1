"""Definition validation shares the registry's dependency resolver and publication lock."""

from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid5

from pydantic import ValidationError

from finai_api.domain.object_sets import PropertyFilter
from finai_api.domain.ontology_definitions import (
    DEFINITION_MODELS,
    DerivedDefinition,
    Expression,
    FactContract,
    FactReconciliation,
    InterfaceDefinition,
)
from finai_api.domain.regulation import RegulatoryDefinition
from finai_api.domain.resources import ResourceMutation
from finai_api.services.object_filter_contract import validate_filters
from finai_api.services.workspace import WorkspaceError


def validate_definition(
    item: ResourceMutation,
    schemas: dict[str, str],
    links: dict[str, str],
    target: Callable[[str, str, str], dict[str, Any]],
) -> None:
    model = DEFINITION_MODELS.get(item.object_type)
    if model is None:
        return
    try:
        definition = model.model_validate(item.attributes["definition"])
    except (ValidationError, KeyError) as exc:
        raise WorkspaceError(422, f"Invalid {item.object_type} definition: {exc}") from exc
    source = str(item.resource_id)

    if item.object_type == "RegulatoryRule":
        assert isinstance(definition, RegulatoryDefinition)
        if item.evidence_class != "SOURCE_BOUND":
            raise WorkspaceError(422, "Regulatory interpretations require retained source evidence")
        act = target(str(item.attributes["act_id"]), source, "REGULATORY_ACT")
        if str(act["attributes"].get("evidence_id")) != str(item.attributes["evidence_id"]):
            raise WorkspaceError(422, "Rule evidence must match the referenced act version")
        if act["attributes"].get("reference", "").startswith("MATSNE:"):
            observation = target(
                str(uuid5(UUID(str(item.attributes["evidence_id"])), "matsne-publication")),
                source,
                "REGULATORY_PUBLICATION",
            )
            if (
                definition.source_version_complete
                and not observation["attributes"]["observation"]["current_law_verified"]
            ):
                raise WorkspaceError(
                    422, "Retained Matsne capture does not verify complete applicable law"
                )
        return

    if item.object_type == "FactReconciliation":
        assert isinstance(definition, FactReconciliation)
        contracts = [
            FactContract.model_validate(
                target(str(item.attributes[side + "_contract_id"]), source, "RECONCILE:" + side)[
                    "attributes"
                ]["definition"]
            )
            for side in ("left", "right")
        ]
        if item.attributes["left_contract_id"] == item.attributes["right_contract_id"]:
            raise WorkspaceError(422, "Reconciliation needs two distinct fact contracts")
        for fact_contract in contracts:
            if not set(definition.group_by).issubset(fact_contract.dimensions):
                raise WorkspaceError(422, "Reconciliation grain must be shared declared dimensions")
            if fact_contract.time_field not in definition.group_by:
                raise WorkspaceError(
                    422, "Reconciliation must preserve the declared reporting period"
                )
            if (
                fact_contract.period_start_field
                and fact_contract.period_start_field not in definition.group_by
            ):
                raise WorkspaceError(
                    422, "Reconciliation must preserve the complete period interval"
                )
            if fact_contract.aggregation in {"ratio_of_sums", "non_additive"}:
                raise WorkspaceError(422, "Reconcile underlying components, not ratios")
        if (
            set(contracts[0].partition_fields) != set(contracts[1].partition_fields)
            or contracts[0].unit_field != contracts[1].unit_field
            or contracts[0].time_field != contracts[1].time_field
            or contracts[0].period_start_field != contracts[1].period_start_field
            or contracts[0].aggregation != contracts[1].aggregation
        ):
            raise WorkspaceError(422, "Reconciliation must preserve matching accounting partitions")
        return

    def schema(name: str) -> dict[str, Any]:
        if name not in schemas:
            raise WorkspaceError(422, f"Unknown ontology type: {name}")
        return target(schemas[name], source, "DEFINITION_TYPE:" + name)

    if item.object_type == "ObjectSetDefinition":
        payload = definition.model_dump(mode="json")
        root = schema(payload["object_type"])
        fields = root["attributes"]["fields"]
        validate_filters(
            [PropertyFilter.model_validate(value) for value in payload["filters"]], fields
        )
        # Traversal definitions bind the link type and endpoint schemas, not UI labels.
        current_types = {payload["object_type"]}
        for step in payload["traversal"]:
            if step["kind"] == "link":
                if step["name"] not in links:
                    raise WorkspaceError(422, "Saved traversal references an unknown link type")
                link = target(links[step["name"]], source, "DEFINITION_LINK:" + step["name"])
                outgoing = step["direction"] == "outgoing"
                inputs = set(link["attributes"]["sources" if outgoing else "targets"])
                outputs = set(link["attributes"]["targets" if outgoing else "sources"])
                if "*" not in inputs and not current_types.intersection(inputs):
                    raise WorkspaceError(
                        422, "Link cannot originate from the current traversal types"
                    )
                if "*" in outputs:
                    raise WorkspaceError(
                        422, "Saved traversal requires explicitly typed link endpoints"
                    )
                current_types = outputs
            elif step["direction"] == "outgoing":
                outputs = set()
                for name in current_types:
                    spec = schema(name)["attributes"]["fields"].get(step["name"], {})
                    if spec.get("kind") != "reference" or spec.get("target_type") in {None, "*"}:
                        raise WorkspaceError(
                            422, "Saved traversal requires a declared typed reference"
                        )
                    outputs.add(spec["target_type"])
                current_types = outputs
            else:
                outputs = set()
                for name, identifier in schemas.items():
                    candidate = target(identifier, source, "TRAVERSAL_CANDIDATE:" + name)
                    spec = candidate["attributes"]["fields"].get(step["name"], {})
                    if spec.get("kind") == "reference" and spec.get("target_type") in current_types:
                        outputs.add(name)
                if not outputs:
                    raise WorkspaceError(
                        422, "No declared incoming reference matches the traversal"
                    )
                current_types = outputs
            for name in current_types:
                schema(name)
        for identifier in payload.get("resource_ids") or []:
            selected = target(identifier, source, "SET_ROOT:" + identifier)
            if selected["object_type"] != payload["object_type"]:
                raise WorkspaceError(422, "Object Set root identity has a different object type")
    elif item.object_type == "ObjectInterface":
        for name, spec in definition.model_dump(mode="json")["fields"].items():
            if spec.get("semantic_id"):
                semantic = target(spec["semantic_id"], source, "INTERFACE_SEMANTIC:" + name)
                if (
                    semantic["object_type"] != "SemanticContract"
                    or semantic["attributes"].get("kind") != spec["kind"]
                ):
                    raise WorkspaceError(
                        422, f"Interface property {name} does not match its semantic contract"
                    )
            if spec.get("target_type"):
                schema(spec["target_type"])
    elif item.object_type == "ObjectTypeGroup":
        for name in definition.model_dump()["types"]:
            schema(name)
    elif item.object_type == "ObjectTypeImplementation":
        interface = target(item.attributes["interface_id"], source, "IMPLEMENTS")
        contract = target(item.attributes["schema_id"], source, "IMPLEMENTATION_SCHEMA")
        required = InterfaceDefinition.model_validate(
            interface["attributes"]["definition"]
        ).model_dump(mode="json")["fields"]
        mapping = definition.model_dump()["fields"]
        fields = contract["attributes"]["fields"]
        if set(mapping) != set(required):
            raise WorkspaceError(422, "Implementation must map every declared interface property")
        for name, field in mapping.items():
            spec = fields.get(field)
            if not spec or spec["kind"] != required[name]["kind"]:
                raise WorkspaceError(422, f"Interface property {name} has an incompatible mapping")
            if required[name]["required"] and not spec["required"]:
                raise WorkspaceError(
                    422, f"Interface property {name} requires a required source field"
                )
            for key in ("semantic_id", "target_type"):
                if required[name].get(key) is not None and str(spec.get(key)) != str(
                    required[name][key]
                ):
                    raise WorkspaceError(
                        422, f"Interface property {name} has an incompatible {key} mapping"
                    )
    elif item.object_type == "DerivedProperty":
        assert isinstance(definition, DerivedDefinition)
        contract = target(item.attributes["schema_id"], source, "DERIVED_SCHEMA")
        fields = contract["attributes"]["fields"]
        if definition.name in fields:
            raise WorkspaceError(422, "Derived property cannot overwrite a stored property")
        budget = [100]

        def check(expression: Expression, depth: int = 0) -> str:
            budget[0] -= 1
            if budget[0] < 0 or depth > 10:
                raise WorkspaceError(422, "Derived expression exceeds its complexity limit")
            if expression.op == "field":
                spec = fields.get(expression.field)
                if not spec or spec["kind"] not in {"integer", "decimal", "text", "identifier"}:
                    raise WorkspaceError(422, "Derived input must be a declared scalar property")
                return "decimal" if spec["kind"] in {"integer", "decimal"} else "text"
            if expression.op == "literal":
                assert expression.value is not None
                try:
                    return "decimal" if Decimal(expression.value).is_finite() else "text"
                except (InvalidOperation, TypeError):
                    return "text"
            kinds = [check(arg, depth + 1) for arg in expression.args]
            if expression.op == "concat":
                return "text"
            if expression.op == "coalesce":
                if len(set(kinds)) != 1:
                    raise WorkspaceError(422, "Coalesce operands must have the same kind")
                return kinds[0]
            if any(kind != "decimal" for kind in kinds):
                raise WorkspaceError(
                    422,
                    "Arithmetic requires numeric inputs; money needs explicit currency semantics",
                )
            return "decimal"

        if check(definition.expression) != definition.result_kind:
            raise WorkspaceError(422, "Derived expression does not match its declared result kind")
    elif item.object_type == "FactContract":
        assert isinstance(definition, FactContract)
        contract = target(item.attributes["schema_id"], source, "FACT_SCHEMA")
        if contract.get("identity_key") in {"SourceJournalMovement", "SourceTrialBalanceRow"}:
            raise WorkspaceError(
                409,
                "Bind source observations to ledger, unit and an authoritative fact "
                "representation before defining financial aggregation",
            )
        fields = contract["attributes"]["fields"]
        family = fields.get(definition.source_family_field, {})
        if family.get("kind") != "identifier" or not family.get("required"):
            raise WorkspaceError(422, "Fact source family must be a required identifier field")
        for name in definition.grain:
            spec = fields.get(name)
            if not spec or not spec.get("required"):
                raise WorkspaceError(422, "Fact grain fields must be declared and required")
            if spec["kind"] not in {
                "identifier",
                "reference",
                "date",
                "datetime",
                "integer",
                "text",
            }:
                raise WorkspaceError(422, "Fact grain fields must be scalar identities")
        if fields[definition.time_field]["kind"] not in {"date", "datetime"}:
            raise WorkspaceError(422, "Fact time must be a date or timestamp")
        if definition.period_start_field and (
            fields[definition.period_start_field]["kind"] != "date"
            or fields[definition.time_field]["kind"] != "date"
        ):
            raise WorkspaceError(422, "Accounting period bounds must be calendar dates")
        if fields[definition.unit_field]["kind"] not in {"identifier", "reference"}:
            raise WorkspaceError(422, "Currency/unit must be an explicit identity")
        measure = fields.get(definition.measure, {})
        if measure.get("kind") not in {"decimal", "integer"} or not measure.get("required"):
            raise WorkspaceError(422, "Fact measure must be a required numeric scalar")
        if definition.denominator_measure:
            denominator = fields.get(definition.denominator_measure, {})
            if denominator.get("kind") not in {"decimal", "integer"} or not denominator.get(
                "required"
            ):
                raise WorkspaceError(422, "Ratio denominator must be a required numeric scalar")
        if definition.row_role_field:
            role = fields.get(definition.row_role_field, {})
            if role.get("kind") not in {"identifier", "text"} or not role.get("required"):
                raise WorkspaceError(422, "Row role must be a required text or identifier field")
        if definition.parent_key_field:
            parent = fields.get(definition.parent_key_field, {})
            key = fields[definition.hierarchy_key_field]
            if parent.get("kind") != key.get("kind") or key.get("kind") not in {
                "identifier",
                "text",
                "reference",
            }:
                raise WorkspaceError(422, "Parent and hierarchy keys need compatible identities")
    elif item.object_type == "ObjectBinding":
        source_schema = target(item.attributes["source_schema_id"], source, "BINDING_SOURCE")
        destination = target(item.attributes["target_schema_id"], source, "BINDING_TARGET")
        source_fields = source_schema["attributes"]["fields"]
        target_fields = destination["attributes"]["fields"]
        payload = definition.model_dump()
        if (
            payload["identity_field"] not in source_fields
            or payload["display_field"] not in source_fields
        ):
            raise WorkspaceError(
                422, "Binding identity and display fields must exist in the source schema"
            )
        if payload["identity_mode"] == "CANONICAL_REFERENCE":
            identity_spec = source_fields[payload["identity_field"]]
            if (
                identity_spec.get("kind") != "reference"
                or identity_spec.get("target_type") != destination["identity_key"]
                or not identity_spec.get("required")
            ):
                raise WorkspaceError(
                    422,
                    "Canonical binding identity must be a required reference to its target type",
                )
        mapped = set()
        for binding in payload["fields"]:
            a, b = (
                source_fields.get(binding["source_field"]),
                target_fields.get(binding["target_field"]),
            )
            if (
                not a
                or not b
                or a["kind"] != b["kind"]
                or a.get("target_type") != b.get("target_type")
            ):
                raise WorkspaceError(422, "Binding fields must have compatible canonical types")
            mapped.add(binding["target_field"])
        if any(spec["required"] and name not in mapped for name, spec in target_fields.items()):
            raise WorkspaceError(422, "Binding must supply every required target property")
