"""Counts projection tests use synthetic non-posting metadata, never financial measures."""

from copy import deepcopy
from uuid import uuid4

import pytest

from finai_api.services.grouped_observations import count_observations
from finai_api.services.semantic_analysis_counts import build
from finai_api.services.semantic_analysis_support import pin
from finai_api.services.workspace import WorkspaceError


class Resolver:
    def __init__(self):
        self.rows = {}
        self.links = {}
        self.original_cells = {}

    def source_cells(self, evidence_pin, coordinate):
        self.version(evidence_pin)
        return self.original_cells.get(coordinate)

    def add(self, kind, attributes, name=None):
        identity, version = str(uuid4()), str(uuid4())
        row = {
            "resource_id": identity,
            "version_id": version,
            "content_hash": "a" * 64,
            "object_type": kind,
            "display_name": name or kind,
            "attributes": attributes,
        }
        self.rows[version] = row
        return row

    def version(self, ref):
        if hasattr(ref, "model_dump"):
            ref = ref.model_dump(mode="json")
        row = self.rows[str(ref["version_id"])]
        if str(row["resource_id"]) != str(ref["resource_id"]) or row["content_hash"] != ref.get(
            "content_hash", row["content_hash"]
        ):
            raise WorkspaceError(409, "Exact version mismatch")
        return row

    def dependencies(self, ref):
        return self.links.get(str(self.version(ref)["version_id"]), [])

    def link(self, source, target, relation):
        self.links.setdefault(source["version_id"], []).append({**target, "relation": relation})


@pytest.fixture
def retained():
    resolver = Resolver()
    company = resolver.add("LegalEntity", {}, "Actual source company label")
    semantic = resolver.add("SemanticContract", {}, "Source header semantics")
    schema = resolver.add(
        "SchemaDefinition",
        {
            "fields": {
                "source_header": {
                    "kind": "text",
                    "required": False,
                    "semantic_id": semantic["resource_id"],
                    "field_id": str(uuid4()),
                    "label": "Source dimension",
                },
                "legal_entity_id": {"kind": "reference", "target_type": "LegalEntity"},
                "amount": {"kind": "decimal"},
            }
        },
    )
    schema["identity_key"] = "CompanyDimension"
    resolver.link(schema, semantic, "SEMANTIC:source_header")
    grouping = {"schema": pin(schema).model_dump(mode="json"), "fields": ["source_header"]}
    function = resolver.add(
        "FunctionDefinition",
        {
            "definition": {
                "implementation_id": "ontology.object-set-derived/v1",
                "group_count": {"schema_id": schema["resource_id"], "fields": ["source_header"]},
            }
        },
        "Source dimensions",
    )
    evidence = resolver.add("SourceEvidence", {"sha256": "b" * 64})
    objects = []
    for column, label in [("Y", "Region"), ("Z", "Budget article"), ("AA", "Department")]:
        record = resolver.add(
            "SourceRecord", {"coordinate": f"TR!{column}2", "evidence_id": evidence["resource_id"]}
        )
        resolver.link(record, evidence, "FIELD:evidence_id")
        resolver.original_cells[f"TR!{column}2"] = {
            "document_id": "doc_" + "f" * 64,
            "source_sha256": "b" * 64,
            "coordinate": f"TR!{column}2",
            "sheet": "TR",
            "cells": [
                {
                    "label": "Original header",
                    "value": label,
                    "coordinate": f"TR!{column}2",
                    "formula": None,
                }
            ],
        }
        row = resolver.add(
            "CompanyDimension",
            {
                "source_header": label,
                "source_record_id": record["resource_id"],
                "legal_entity_id": company["resource_id"],
                "amount": "99999.99",
            },
            label,
        )
        row["schema_version_id"] = schema["version_id"]
        resolver.link(row, company, "FIELD:legal_entity_id")
        resolver.link(row, record, "FIELD:source_record_id")
        objects.append(deepcopy(row))
    output = {
        "run_id": "fcr_" + "c" * 64,
        "objects": objects,
        "function": pin(function).model_dump(mode="json"),
        "plan_hash": "d" * 64,
        "total": 3,
        "next_offset": None,
        "coverage": "QUERY_PAGE_ONLY",
        "query": {
            "offset": 0,
            "limit": 10,
            "valid_at": "2026-09-07T12:00:00Z",
            "known_at": "2026-09-07T12:00:00Z",
        },
    }
    output["group_counts"] = count_observations(output, grouping, schema)
    history = {
        "invocation_id": str(uuid4()),
        "status": "SUCCEEDED",
        "receipt_hash": "e" * 64,
        "receipt": {"recorded_at": "2026-09-07T12:00:01Z"},
        "output": output,
    }
    plan = {
        "function": output["function"],
        "group_count": grouping,
        "plan_hash": output["plan_hash"],
    }
    return history, plan, resolver, company, schema


def test_nonposting_metadata_projects_retained_counts_without_money_inference(retained):
    history, plan, resolver, company, _ = retained
    original = deepcopy(history)
    descriptor, rows, contributors = build(history, plan, resolver, company["resource_id"])
    assert descriptor.grain == ["source_header"]
    assert descriptor.fields[0].label == "Source dimension"
    assert len(rows) == 3 and all(row.values[descriptor.measure].value == 1 for row in rows)
    assert descriptor.fields[-1].unit == "Source observations"
    assert "amount" not in {field.key for field in descriptor.fields}
    assert {
        contributor.coordinate for values in contributors.values() for contributor in values
    } == {"TR!Y2", "TR!Z2", "TR!AA2"}
    assert all(
        contributor.source_sha256 == "b" * 64
        for values in contributors.values()
        for contributor in values
    )
    assert descriptor.current_use_authorized is False
    assert history == original


@pytest.mark.parametrize(
    "change",
    [
        "count",
        "boolean_count",
        "company",
        "schema",
        "function",
        "canonical",
        "partition",
        "partial",
        "semantic",
    ],
)
def test_hostile_shapes_and_authority_mismatches_refused(retained, change):
    history, plan, resolver, company, schema = retained
    output = history["output"]
    company_id = company["resource_id"]
    if change == "count":
        output["group_counts"]["groups"][0]["count"] = 9
    elif change == "boolean_count":
        output["group_counts"]["groups"][0]["count"] = True
    elif change == "company":
        company_id = str(uuid4())
    elif change == "schema":
        output["objects"][0]["schema_version_id"] = str(uuid4())
    elif change == "function":
        resolver.version(plan["function"])["attributes"]["definition"]["group_count"]["fields"] = [
            "amount"
        ]
    elif change == "canonical":
        resolver.version(output["objects"][0])["attributes"]["source_header"] = (
            "Changed canonical fact"
        )
    elif change == "partition":
        output["group_counts"]["groups"][1]["contributors"] = output["group_counts"]["groups"][0][
            "contributors"
        ]
    elif change == "partial":
        output["next_offset"] = 10
    else:
        resolver.links[schema["version_id"]] = []
    with pytest.raises(WorkspaceError):
        build(history, plan, resolver, company_id)


def test_missing_and_null_remain_distinct_without_zero_coercion(retained):
    history, plan, resolver, company, schema = retained
    objects = history["output"]["objects"]
    for obj, attrs in [(objects[0], {}), (objects[1], {"source_header": None})]:
        obj["attributes"].pop("source_header")
        obj["attributes"].update(attrs)
        resolver.version(obj)["attributes"] = deepcopy(obj["attributes"])
    history["output"]["group_counts"] = count_observations(
        history["output"], plan["group_count"], schema
    )
    _, rows, _ = build(history, plan, resolver, company["resource_id"])
    assert {row.values["source_header"].state for row in rows} == {"VALUE", "NULL", "MISSING"}


def test_unresolved_company_reference_is_not_inferred_from_authorization_scope(retained):
    history, plan, resolver, company, _ = retained
    row = history["output"]["objects"][0]
    resolver.links[row["version_id"]] = [
        dep
        for dep in resolver.links[row["version_id"]]
        if dep["relation"] != "FIELD:legal_entity_id"
    ]
    with pytest.raises(WorkspaceError, match="unambiguous retained reference"):
        build(history, plan, resolver, company["resource_id"])


def test_schema_driven_group_field_needs_no_workbook_specific_page(retained):
    history, plan, resolver, company, schema = retained
    schema["attributes"]["fields"]["category"] = schema["attributes"]["fields"].pop("source_header")
    resolver.links[schema["version_id"]][0]["relation"] = "SEMANTIC:category"
    plan["group_count"]["fields"] = ["category"]
    resolver.version(plan["function"])["attributes"]["definition"]["group_count"]["fields"] = [
        "category"
    ]
    for obj in history["output"]["objects"]:
        obj["attributes"]["category"] = obj["attributes"].pop("source_header")
        resolver.version(obj)["attributes"] = deepcopy(obj["attributes"])
    history["output"]["group_counts"] = count_observations(
        history["output"], plan["group_count"], schema
    )
    descriptor, rows, _ = build(history, plan, resolver, company["resource_id"])
    assert descriptor.grain == ["category"] and len(rows) == 3


def test_original_cells_are_read_from_exact_source_not_canonical_attributes(retained):
    history, plan, resolver, company, _ = retained
    _, _, contributors = build(history, plan, resolver, company["resource_id"])
    cells = [
        cell
        for group in contributors.values()
        for contributor in group
        for cell in contributor.cells
    ]
    assert {cell.value for cell in cells} == {"Region", "Budget article", "Department"}
    assert all(cell.coordinate in {"TR!Y2", "TR!Z2", "TR!AA2"} for cell in cells)
    assert "99999.99" not in {cell.value for cell in cells}
    assert all(c.document_id == "doc_" + "f" * 64 for group in contributors.values() for c in group)


def test_unavailable_original_is_explicit_without_canonical_attribute_substitution(retained):
    history, plan, resolver, company, _ = retained
    resolver.original_cells.clear()
    _, _, contributors = build(history, plan, resolver, company["resource_id"])
    for group in contributors.values():
        for contributor in group:
            assert contributor.document_id is None
            assert [cell.label for cell in contributor.cells] == [
                "Original source cell unavailable"
            ]
            assert contributor.cells[0].coordinate is None


@pytest.mark.parametrize("change", ["source_sha256", "coordinate"])
def test_wrong_original_cell_provenance_refused(retained, change):
    history, plan, resolver, company, _ = retained
    resolver.original_cells["TR!Y2"][change] = "changed"
    with pytest.raises(WorkspaceError, match="differ from retained provenance"):
        build(history, plan, resolver, company["resource_id"])
