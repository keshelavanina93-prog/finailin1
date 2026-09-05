"""Validated executable ontology definitions, stored as canonical resource versions."""

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from finai_api.domain.object_sets import ObjectSetQuery

Name = Annotated[str, Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]{0,127}$")]
TypeName = Annotated[str, Field(pattern=r"^[A-Z][A-Za-z0-9]{1,63}$")]


class Definition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Expression(Definition):
    op: Literal["field", "literal", "add", "subtract", "multiply", "divide", "concat", "coalesce"]
    field: Name | None = None
    value: str | None = Field(default=None, max_length=2000)
    args: list["Expression"] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def shape(self) -> "Expression":
        if self.op == "field":
            if self.field is None or self.value is not None or self.args:
                raise ValueError("Field expression requires only a field name")
        elif self.op == "literal":
            if self.value is None or self.field is not None or self.args:
                raise ValueError("Literal expression requires only a value")
        elif self.field is not None or self.value is not None or len(self.args) < 2:
            raise ValueError("Operator requires at least two arguments and no field/value")
        elif self.op in {"subtract", "divide"} and len(self.args) != 2:
            raise ValueError("Subtract/divide require exactly two arguments")
        return self


class DerivedDefinition(Definition):
    name: Name
    result_kind: Literal["decimal", "text"]
    expression: Expression


class InterfaceField(Definition):
    kind: Literal[
        "text",
        "identifier",
        "integer",
        "decimal",
        "boolean",
        "reference",
        "date",
        "datetime",
        "money",
        "quantity",
    ]
    required: bool = True


class InterfaceDefinition(Definition):
    fields: dict[Name, InterfaceField] = Field(min_length=1, max_length=100)


class ImplementationDefinition(Definition):
    fields: dict[Name, Name] = Field(min_length=1, max_length=100)


class TypeGroupDefinition(Definition):
    types: list[TypeName] = Field(min_length=1, max_length=100)


class BindingField(Definition):
    source_field: str = Field(min_length=1, max_length=128)
    target_field: Name


class BindingDefinition(Definition):
    identity_field: str = Field(min_length=1, max_length=128)
    display_field: str = Field(min_length=1, max_length=128)
    fields: list[BindingField] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_targets(self) -> "BindingDefinition":
        if len({field.target_field for field in self.fields}) != len(self.fields):
            raise ValueError("Binding target fields must be unique")
        return self


class FactContract(Definition):
    """One authoritative representation at one declared grain; never a cross-fact join."""

    grain: list[Name] = Field(min_length=1, max_length=20)
    dimensions: list[Name] = Field(default_factory=list, max_length=20)
    measure: Name
    aggregation: Literal["flow_sum", "closing_balance", "non_additive"]
    time_field: Name
    unit_field: Name
    source_family: str = Field(min_length=1, max_length=128)
    source_family_field: Name
    authority_basis: str = Field(min_length=10, max_length=2000)

    @model_validator(mode="after")
    def valid_grain(self) -> "FactContract":
        if len(set(self.grain)) != len(self.grain) or len(set(self.dimensions)) != len(
            self.dimensions
        ):
            raise ValueError("Grain and dimension fields must be unique")
        if self.time_field not in self.grain or self.unit_field not in self.grain:
            raise ValueError("Grain must include time and currency/unit identity")
        if not set(self.dimensions).issubset(self.grain):
            raise ValueError("Aggregation dimensions must belong to the fact grain")
        if self.measure in self.grain:
            raise ValueError("The measure cannot be a grain key")
        return self


DEFINITION_MODELS: dict[str, type[BaseModel]] = {
    "ObjectSetDefinition": ObjectSetQuery,
    "ObjectInterface": InterfaceDefinition,
    "ObjectTypeImplementation": ImplementationDefinition,
    "ObjectTypeGroup": TypeGroupDefinition,
    "DerivedProperty": DerivedDefinition,
    "ObjectBinding": BindingDefinition,
    "FactContract": FactContract,
}


class DefinitionWrite(Definition):
    resource_id: UUID | None = None
    expected_version_id: UUID | None = None
    kind: Literal[
        "ObjectSetDefinition",
        "ObjectInterface",
        "ObjectTypeImplementation",
        "ObjectTypeGroup",
        "DerivedProperty",
        "ObjectBinding",
        "FactContract",
    ]
    name: str = Field(min_length=1, max_length=200)
    key: str = Field(min_length=1, max_length=256)
    rationale: str = Field(min_length=10, max_length=2000)
    attributes: dict[str, Any]
