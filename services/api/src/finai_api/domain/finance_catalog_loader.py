"""Read and validate packaged finance definitions and retained candidate constructions."""

from __future__ import annotations

import json
import re
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CATALOG_NAME = "ontology-catalog.g8-finance.v1.json"
CATALOG_RELATIVE = Path("packages/contracts/catalog") / CATALOG_NAME
Name = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_.]{0,127}$")]
PropertyName = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,127}$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CatalogProperty(_Strict):
    name: PropertyName
    value_type: str = Field(min_length=1, max_length=1024)
    required: bool = False
    pattern: str | None = None
    derived: bool = False
    description: str | None = None

    @model_validator(mode="after")
    def supported_type(self) -> CatalogProperty:
        primitives = {
            "string", "integer", "boolean", "decimal_string", "date", "datetime", "sha256",
            "identifier", "string[]", "DimensionBinding[]",
        }
        if self.value_type not in primitives and not re.fullmatch(
            r"(?:enum|const):[^\s:]+", self.value_type
        ):
            raise ValueError(f"Unsupported catalog value_type: {self.value_type}")
        if self.value_type.startswith("enum:"):
            values = self.value_type[5:].split("|")
            if not all(values) or len(set(values)) != len(values):
                raise ValueError("Enum values must be nonempty and unique")
        if self.pattern is not None:
            try:
                re.compile(self.pattern)
            except re.error as exc:
                raise ValueError("Invalid catalog property pattern") from exc
        return self


class CatalogInterface(_Strict):
    api_name: Name
    properties: list[CatalogProperty] = Field(max_length=100)

    @model_validator(mode="after")
    def unique_properties(self) -> CatalogInterface:
        _unique([item.name for item in self.properties], f"{self.api_name} properties")
        return self


class CatalogObject(CatalogInterface):
    type_group: Name
    implements: list[Name] = Field(max_length=100)
    primary_key: Literal["id"]
    title_property: PropertyName | None = None


class CatalogLink(_Strict):
    api_name: Name
    from_type: Name
    to_type: Name
    cardinality: Literal["ONE_TO_ONE", "ONE_TO_MANY", "MANY_TO_ONE", "MANY_TO_MANY"]
    constraint: str | None = None


class CatalogSet(_Strict):
    api_name: Name
    base_type: Name
    default_filters: list[str] = Field(default_factory=list, max_length=20)


class CatalogFunction(_Strict):
    api_name: Name
    input_grain: str
    output: str
    forbidden: str | None = None


class CatalogAction(_Strict):
    api_name: Name
    changes_authority: bool
    nyx_may_execute: bool = False


class CatalogDefinition(_Strict):
    """A definition that the finance catalog can compile into a platform resource."""

    api_name: Name
    schema_type: Name
    definition: dict[str, Any]


class CatalogBinding(_Strict):
    """A source-to-canonical binding template, with no company instances."""

    api_name: Name
    source_schema: Name
    target_schema: Name
    definition: dict[str, Any]


class FinanceCatalog(_Strict):
    catalog_id: Literal["g8.ontology.finance.v1"]
    catalog_version: int = Field(ge=1)
    status: Literal["SPEC_ACCEPTED", "CANDIDATE", "SUPERSEDED"]
    coa_pin_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    interfaces: list[CatalogInterface]
    object_types: list[CatalogObject] = Field(min_length=1)
    link_types: list[CatalogLink]
    object_sets: list[CatalogSet]
    derived_properties: list[CatalogDefinition] = Field(default_factory=list)
    fact_contracts: list[CatalogDefinition] = Field(default_factory=list)
    source_bindings: list[CatalogBinding] = Field(default_factory=list)
    functions: list[CatalogFunction] = Field(default_factory=list)
    actions: list[CatalogAction] = Field(default_factory=list)
    invariants: list[str]
    federation: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def references(self) -> FinanceCatalog:
        groups = (
            self.interfaces, self.object_types, self.link_types, self.object_sets,
            self.derived_properties, self.fact_contracts, self.source_bindings,
            self.functions, self.actions,
        )
        for group in groups:
            _unique([item.api_name for item in group], "catalog names")
        interface_names = {item.api_name for item in self.interfaces}
        objects = {item.api_name for item in self.object_types}
        if interface_names & objects:
            raise ValueError("Object and interface names must not overlap")
        for item in self.object_types:
            _unique(item.implements, f"{item.api_name} interfaces")
            if set(item.implements) - interface_names:
                raise ValueError(f"Unknown implemented interface on {item.api_name}")
            if not re.fullmatch(r"[A-Z][A-Za-z0-9]{1,63}", item.api_name):
                raise ValueError(f"Invalid runtime object type: {item.api_name}")
            property_names = {prop.name for prop in item.properties}
            property_names.update(
                prop.name for interface in self.interfaces
                if interface.api_name in item.implements for prop in interface.properties
            )
            if item.title_property is not None and item.title_property not in property_names:
                raise ValueError(f"Undeclared title property on {item.api_name}")
        for link in self.link_types:
            if {link.from_type, link.to_type} - objects - interface_names:
                raise ValueError(f"Unknown link endpoint: {link.api_name}")
        for query in self.object_sets:
            if query.base_type not in objects:
                raise ValueError(f"Unknown Object Set type: {query.api_name}")
        for definition in (*self.derived_properties, *self.fact_contracts):
            if definition.schema_type not in objects:
                raise ValueError(f"Unknown definition schema: {definition.api_name}")
            if not isinstance(definition.definition, dict):
                raise ValueError(f"Definition payload must be an object: {definition.api_name}")
        # Source schemas are platform observations. They are deliberately allowed to
        # live outside the business-object list, while canonical targets must be listed.
        known_source_schemas = {
            "SourceAccountDefinition", "SourceTrialBalanceRow", "SourceJournalMovement",
            "SourceRecord", "SourceEvidence", "SourceDimensionAssignment",
        }
        for binding in self.source_bindings:
            if binding.source_schema not in known_source_schemas:
                raise ValueError(f"Unknown source binding schema: {binding.api_name}")
            if binding.target_schema not in objects:
                raise ValueError(f"Unknown source binding target: {binding.api_name}")
            if not isinstance(binding.definition, dict):
                raise ValueError(f"Binding payload must be an object: {binding.api_name}")
        for action in self.actions:
            if action.changes_authority and action.nyx_may_execute:
                raise ValueError("NYX must not execute authority-changing catalog actions")
        return self


def _unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"Duplicate {label}")


def validate_finance_catalog(catalog: dict[str, Any]) -> FinanceCatalog:
    return FinanceCatalog.model_validate(catalog)


def catalog_path(repo_root: Path | None = None) -> Path:
    """Source checkout location; installed packages use importlib.resources instead."""
    root = repo_root or Path(__file__).resolve().parents[5]
    return root / CATALOG_RELATIVE


def _unique_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate JSON key: {key}")
        value[key] = item
    return value


def _read(relative: Path, package_directory: str) -> bytes:
    resource = files("finai_api").joinpath(package_directory, relative.name)
    if resource.is_file():
        return resource.read_bytes()
    source = Path(__file__).resolve().parents[5] / relative
    if not source.is_file():
        raise FileNotFoundError(f"Required finance artifact is absent: {relative.name}")
    return source.read_bytes()


def load_finance_catalog(repo_root: Path | None = None) -> dict[str, Any]:
    content = (
        catalog_path(repo_root).read_bytes() if repo_root is not None
        else _read(CATALOG_RELATIVE, "catalog")
    )
    catalog = json.loads(content, object_pairs_hook=_unique_json_pairs)
    validate_finance_catalog(catalog)
    if not isinstance(catalog, dict):
        raise ValueError("Catalog must be an object")
    return catalog


_CONSTRUCTIONS = {
    "g8.candidate.coa-406": "coa-406.candidate.json",
    "g8.candidate.seg-entities": "seg-entities.candidate.json",
}


def candidate_construction_bytes(construction_id: str) -> bytes:
    """Only known retained constructions can be selected; no caller-provided paths."""
    if construction_id not in _CONSTRUCTIONS:
        raise ValueError("Unknown candidate construction")
    return _read(Path("constructions/candidate") / _CONSTRUCTIONS[construction_id], "constructions")


def load_candidate_construction(construction_id: str) -> dict[str, Any]:
    value = json.loads(
        candidate_construction_bytes(construction_id), object_pairs_hook=_unique_json_pairs
    )
    if (
        not isinstance(value, dict)
        or value.get("construction_id") != construction_id
        or value.get("status") != "CANDIDATE"
        or value.get("not_catalog") is not True
    ):
        raise ValueError("Candidate construction identity or authority is invalid")
    return value


def object_type_names(catalog: dict[str, Any] | None = None) -> list[str]:
    model = validate_finance_catalog(load_finance_catalog() if catalog is None else catalog)
    return [item.api_name for item in model.object_types]


def link_type_names(catalog: dict[str, Any] | None = None) -> list[str]:
    model = validate_finance_catalog(load_finance_catalog() if catalog is None else catalog)
    return [item.api_name for item in model.link_types]
