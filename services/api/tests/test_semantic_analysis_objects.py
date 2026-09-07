"""Measure-free canonical tables preserve exact ownership and source provenance."""

from copy import deepcopy
from uuid import uuid4

import pytest

from finai_api.services.semantic_analysis_objects import build
from finai_api.services.semantic_analysis_support import pin
from finai_api.services.workspace import WorkspaceError


class Resolver:
    def __init__(self):
        self.rows, self.links, self.originals = {}, {}, {}

    def add(self, kind, attrs, name=None):
        row = {
            "resource_id": str(uuid4()),
            "version_id": str(uuid4()),
            "content_hash": "a" * 64,
            "object_type": kind,
            "display_name": name or kind,
            "attributes": attrs,
        }
        self.rows[row["version_id"]] = row
        return row

    def version(self, ref):
        ref = ref.model_dump(mode="json") if hasattr(ref, "model_dump") else ref
        row = self.rows[str(ref["version_id"])]
        if str(row["resource_id"]) != str(ref["resource_id"]) or row["content_hash"] != ref.get(
            "content_hash", row["content_hash"]
        ):
            raise WorkspaceError(409, "Exact version mismatch")
        return row

    def dependencies(self, ref):
        return self.links.get(self.version(ref)["version_id"], [])

    def link(self, source, target, relation):
        self.links.setdefault(source["version_id"], []).append({**target, "relation": relation})

    def field(self, source, name):
        matches = [
            d
            for d in self.dependencies(source)
            if d["relation"] == "FIELD:" + name
            and str(d["resource_id"]) == str(source["attributes"].get(name))
        ]
        if len(matches) != 1:
            raise WorkspaceError(409, "Field lacks an exact retained reference")
        return matches[0]

    def source_cells(self, evidence, coordinate):
        row = self.version(evidence)
        return self.originals.get((row["attributes"]["sha256"], coordinate))


@pytest.fixture
def retained():
    r = Resolver()
    company = r.add("LegalEntity", {}, "Reviewed company")
    chart_schema = r.add(
        "SchemaDefinition",
        {
            "fields": {
                "legal_entity_id": {"kind": "reference", "target_type": "LegalEntity"},
            }
        },
    )
    chart_schema["identity_key"] = "LocalChartOfAccounts"
    chart = r.add("LocalChartOfAccounts", {"legal_entity_id": company["resource_id"]})
    chart["schema_version_id"] = chart_schema["version_id"]
    r.link(chart, chart_schema, "USES_SCHEMA")
    r.link(chart, company, "FIELD:legal_entity_id")
    schema = r.add(
        "SchemaDefinition",
        {
            "fields": {
                "account_code": {
                    "kind": "identifier",
                    "field_id": str(uuid4()),
                    "label": "Account code",
                },
                "chart_id": {"kind": "reference", "target_type": "LocalChartOfAccounts"},
                "evidence_id": {"kind": "reference", "target_type": "SourceEvidence"},
                "optional_number": {"kind": "integer"},
                "source_amount": {"kind": "decimal"},
                "configuration": {"kind": "definition"},
            }
        },
    )
    schema["identity_key"] = "LocalAccount"
    for name, spec in schema["attributes"]["fields"].items():
        semantic = r.add("SemanticContract", {}, "Meaning of " + name)
        spec["semantic_id"] = semantic["resource_id"]
        spec.setdefault("field_id", str(uuid4()))
        r.link(schema, semantic, "SEMANTIC:" + name)
    base = r.add("SourceEvidence", {"sha256": "b" * 64}, "Separate posting-use evidence")
    original = r.add("SourceEvidence", {"sha256": "c" * 64}, "Original chart evidence")
    objects, definitions = [], []
    for i, code in enumerate(["1210", "1220", "1297"]):
        coordinate = f"Sheet1!B{189 + i}"
        record = r.add(
            "SourceRecord", {"evidence_id": original["resource_id"], "coordinate": coordinate}
        )
        r.link(record, original, "FIELD:evidence_id")
        definition = r.add(
            "SourceAccountDefinition",
            {
                "account_code": code,
                "evidence_id": original["resource_id"],
                "source_record_id": record["resource_id"],
            },
            "Reviewed source account " + code,
        )
        r.link(definition, record, "FIELD:source_record_id")
        r.link(definition, original, "FIELD:evidence_id")
        attrs = {
            "account_code": code,
            "chart_id": chart["resource_id"],
            "evidence_id": base["resource_id"],
            "source_amount": "99999.99",
            "configuration": {"unreviewed_classification": "expense"},
        }
        if i:
            attrs["optional_number"] = None if i == 1 else 0
        obj = r.add("LocalAccount", attrs, "Account " + code)
        obj["schema_version_id"] = schema["version_id"]
        r.link(obj, schema, "USES_SCHEMA")
        r.link(obj, chart, "FIELD:chart_id")
        r.link(obj, base, "FIELD:evidence_id")
        r.link(obj, definition, "BOUND_SOURCE:" + definition["resource_id"])
        r.originals[("c" * 64, coordinate)] = {
            "document_id": "ir_" + "d" * 64,
            "source_sha256": "c" * 64,
            "sheet": "Sheet1",
            "coordinate": coordinate,
            "cells": [
                {
                    "label": "Original account code",
                    "value": code,
                    "coordinate": coordinate,
                    "formula": None,
                }
            ],
        }
        objects.append(deepcopy(obj))
        definitions.append(definition)
    function = r.add(
        "FunctionDefinition",
        {
            "definition": {
                "implementation_id": "ontology.object-set-derived/v1",
                "derived_property_ids": [],
            }
        },
        "Reviewed accounts",
    )
    output = {
        "function": pin(function).model_dump(mode="json"),
        "plan_hash": "e" * 64,
        "run_id": "fcr_" + "f" * 64,
        "objects": objects,
        "total": 3,
        "coverage": "QUERY_PAGE_ONLY",
        "next_offset": None,
        "query": {
            "offset": 0,
            "limit": 100,
            "valid_at": "2026-09-07T12:00:00Z",
            "known_at": "2026-09-07T12:00:00Z",
        },
    }
    history = {
        "status": "SUCCEEDED",
        "invocation_id": str(uuid4()),
        "receipt_hash": "1" * 64,
        "receipt": {"recorded_at": "2026-09-07T12:00:01Z"},
        "output": output,
    }
    plan = {
        "function": output["function"],
        "plan_hash": output["plan_hash"],
        "derived_properties": [],
    }
    return history, plan, r, company, schema, definitions


def project(retained):
    history, plan, resolver, company, *_ = retained
    return build(history, plan, resolver, company["resource_id"])


def test_accounts_are_definition_rows_without_numeric_measure(retained):
    original = deepcopy(retained[0])
    descriptor, rows, _ = project(retained)
    assert descriptor.contract == "semantic-analysis/2"
    assert descriptor.measure is None and descriptor.visual == "NONE"
    assert descriptor.row_noun == "objects" and descriptor.grain == ["__resource"]
    assert all(f.role != "MEASURE" and f.aggregation == "NONE" for f in descriptor.fields)
    assert all(row.values["source_amount"].value == "99999.99" for row in rows)
    assert "configuration" not in rows[0].values
    assert descriptor.company == pin(retained[3])
    assert not descriptor.current_use_authorized and not descriptor.business_effect_authorized
    assert retained[0] == original


def test_missing_null_and_numeric_zero_remain_distinct(retained):
    _, rows, _ = project(retained)
    values = [row.values["optional_number"] for row in rows]
    assert [(v.state, v.value) for v in values] == [("MISSING", None), ("NULL", None), ("VALUE", 0)]


def test_original_definition_cells_never_use_direct_base_evidence(retained):
    _, rows, contributors = project(retained)
    for row, definition in zip(rows, retained[5], strict=True):
        source = contributors[row.key][0]
        assert source.reference == pin(definition)
        assert source.basis == "ORIGINAL_SOURCE"
        assert source.source_sha256 == "c" * 64
        assert source.document_id == "ir_" + "d" * 64
        assert source.cells[0].value == definition["attributes"]["account_code"]
        assert source.cells[0].coordinate == source.coordinate


def test_unavailable_original_keeps_definition_pin_without_substitute_cells(retained):
    retained[2].originals.clear()
    _, _, contributors = project(retained)
    for group in contributors.values():
        source = group[0]
        assert source.basis == "UNAVAILABLE" and source.document_id is None
        assert all(cell.coordinate is None for cell in source.cells)
        assert all(cell.value != "99999.99" for cell in source.cells)


@pytest.mark.parametrize(
    "change",
    [
        "wrong_company",
        "mixed_schema",
        "missing_chart_schema",
        "wrong_chart_target",
        "attribute_tamper",
        "duplicate_identity",
        "definition_source_mismatch",
        "calculated_output",
    ],
)
def test_ambiguous_or_incompatible_authority_is_refused(retained, change):
    history, plan, resolver, company, schema, definitions = retained
    obj = history["output"]["objects"][0]
    canonical = resolver.version(obj)
    if change == "wrong_company":
        company = {"resource_id": str(uuid4())}
    elif change == "mixed_schema":
        other = resolver.add("SchemaDefinition", deepcopy(schema["attributes"]))
        other["identity_key"] = "LocalAccount"
        canonical["schema_version_id"] = obj["schema_version_id"] = other["version_id"]
        resolver.links[canonical["version_id"]] = [
            d for d in resolver.dependencies(canonical) if d["relation"] != "USES_SCHEMA"
        ]
        resolver.link(canonical, other, "USES_SCHEMA")
    elif change == "missing_chart_schema":
        chart = resolver.field(canonical, "chart_id")
        resolver.links[chart["version_id"]] = [
            d for d in resolver.dependencies(chart) if d["relation"] != "USES_SCHEMA"
        ]
    elif change == "wrong_chart_target":
        schema["attributes"]["fields"]["chart_id"]["target_type"] = "UnrelatedObject"
    elif change == "attribute_tamper":
        obj["attributes"]["account_code"] = "not-retained"
    elif change == "duplicate_identity":
        history["output"]["objects"].append(deepcopy(obj))
    elif change == "definition_source_mismatch":
        definition = definitions[0]
        base = resolver.field(canonical, "evidence_id")
        definition["attributes"]["evidence_id"] = base["resource_id"]
        resolver.links[definition["version_id"]] = [
            d for d in resolver.dependencies(definition) if d["relation"] != "FIELD:evidence_id"
        ]
        resolver.link(definition, base, "FIELD:evidence_id")
    else:
        history["output"]["derived_values"] = [{"value": 9}]
    with pytest.raises(WorkspaceError):
        build(history, plan, resolver, company["resource_id"])


@pytest.mark.parametrize(
    "change",
    [
        "retained_schema_version",
        "retained_object_type",
        "original_hash",
        "original_coordinate",
        "function_pin",
        "plan_hash",
    ],
)
def test_exact_output_and_original_evidence_integrity(retained, change):
    history, _, resolver, *_ = retained
    obj = history["output"]["objects"][0]
    if change == "retained_schema_version":
        obj["schema_version_id"] = str(uuid4())
    elif change == "retained_object_type":
        obj["object_type"] = "UnrelatedObject"
    elif change.startswith("original_"):
        original = next(iter(resolver.originals.values()))
        original["source_sha256" if change == "original_hash" else "coordinate"] = (
            "b" * 64 if change == "original_hash" else "Base!S5"
        )
    elif change == "function_pin":
        history["output"]["function"] = {
            **history["output"]["function"],
            "version_id": str(uuid4()),
        }
    else:
        history["output"]["plan_hash"] = "0" * 64
    with pytest.raises(WorkspaceError):
        project(retained)


def test_same_company_identity_with_mixed_reviewed_versions_is_refused(retained):
    history, _, resolver, company, *_ = retained
    obj = resolver.version(history["output"]["objects"][0])
    chart = resolver.field(obj, "chart_id")
    other_company = resolver.add("LegalEntity", {}, company["display_name"])
    other_company["resource_id"] = company["resource_id"]
    other_chart = resolver.add("LocalChartOfAccounts", deepcopy(chart["attributes"]))
    other_chart["resource_id"] = chart["resource_id"]
    other_chart["schema_version_id"] = chart["schema_version_id"]
    chart_schema = next(d for d in resolver.dependencies(chart) if d["relation"] == "USES_SCHEMA")
    resolver.link(other_chart, chart_schema, "USES_SCHEMA")
    resolver.link(other_chart, other_company, "FIELD:legal_entity_id")
    resolver.links[obj["version_id"]] = [
        d for d in resolver.dependencies(obj) if d["relation"] != "FIELD:chart_id"
    ]
    resolver.link(obj, other_chart, "FIELD:chart_id")
    with pytest.raises(WorkspaceError, match="Mixed"):
        project(retained)


def test_scalar_field_without_exact_semantic_dependency_is_schema_only(retained):
    _, _, resolver, _, schema, _ = retained
    unpinned_id = schema["attributes"]["fields"]["account_code"]["semantic_id"]
    resolver.links[schema["version_id"]] = [
        d for d in resolver.dependencies(schema) if d["relation"] != "SEMANTIC:account_code"
    ]
    descriptor, rows, _ = project(retained)
    field = next(f for f in descriptor.fields if f.key == "account_code")
    assert field.semantic_id is None and field.definition == pin(schema)
    assert str(field.field_id) == schema["attributes"]["fields"]["account_code"]["field_id"]
    assert field.role == "ATTRIBUTE" and field.aggregation == "NONE"
    assert descriptor.measure is None and descriptor.visual == "NONE"
    assert [row.values["account_code"].value for row in rows] == ["1210", "1220", "1297"]
    assert all(str(ref.resource_id) != unpinned_id for ref in descriptor.definitions)
    assert any(
        "Account code: no exact semantic version is retained" in reason
        for reason in descriptor.unavailable_operations
    )


@pytest.mark.parametrize("change", ["ambiguous", "wrong_type"])
def test_invalid_retained_semantics_never_degrade_to_schema_only(retained, change):
    _, _, resolver, _, schema, _ = retained
    semantic = next(
        d for d in resolver.dependencies(schema) if d["relation"] == "SEMANTIC:account_code"
    )
    other = resolver.add("SemanticContract" if change == "ambiguous" else "UnrelatedObject", {})
    other["resource_id"] = semantic["resource_id"]
    if change == "wrong_type":
        resolver.links[schema["version_id"]] = [
            d for d in resolver.dependencies(schema) if d["relation"] != "SEMANTIC:account_code"
        ]
    resolver.link(schema, other, "SEMANTIC:account_code")
    with pytest.raises(WorkspaceError):
        project(retained)


def test_partial_page_is_labelled_without_claiming_complete_chart(retained):
    retained[0]["output"].update(total=38, next_offset=3)
    descriptor, rows, _ = project(retained)
    assert len(rows) == 3 and descriptor.measure is None
    coverage = {item.label: item.value for item in descriptor.coverage}
    assert coverage["Further query pages"] == "Available"
    assert coverage["Query result coverage"] == "Returned query page only"
    assert coverage["Financial report completeness"] == "Not established"


def test_without_source_binding_cells_are_explicitly_canonical(retained):
    history, _, resolver, *_ = retained
    for obj in history["output"]["objects"]:
        resolver.links[obj["version_id"]] = [
            d for d in resolver.dependencies(obj) if not d["relation"].startswith("BOUND_SOURCE:")
        ]
    _, _, contributors = project(retained)
    assert all(
        c.basis == "CANONICAL_DEFINITION" and c.document_id is None and c.coordinate is None
        for group in contributors.values()
        for c in group
    )
