"""Versioned Metric selectors over completed shared Function evidence, never formulas."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Pin(Model):
    resource_id: UUID
    version_id: UUID
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class CountUnit(Model):
    kind: Literal["COUNT"] = "COUNT"
    symbol: Literal["objects"] = "objects"


class CurrencyUnit(Model):
    kind: Literal["CURRENCY"]
    reference: Pin


Unit = Annotated[CountUnit | CurrencyUnit, Field(discriminator="kind")]


class ObjectCount(Model):
    kind: Literal["OBJECT_COUNT"]
    company_field: str | None = Field(default=None, pattern=r"^[a-zA-Z][a-zA-Z0-9_]{0,127}$")


class Measure(Model):
    kind: Literal["MEASURE"]
    key: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]{0,127}$")


class MetricDefinition(Model):
    """Select one retained scalar; never aggregate across observations or grains."""

    contract: Literal["metric-definition/1"]
    selector: Annotated[ObjectCount | Measure, Field(discriminator="kind")]
    unit: Unit
    grain: str = Field(min_length=1, max_length=128)
    dimensions: list[str] = Field(max_length=20)
    aggregation: Literal["non_additive"] = "non_additive"

    @model_validator(mode="after")
    def shape(self):
        if len(self.dimensions) != len(set(self.dimensions)):
            raise ValueError("Metric dimensions must be unique")
        if isinstance(self.selector, ObjectCount) and (
            not isinstance(self.unit, CountUnit)
            or self.grain != "OBJECT_SET_SNAPSHOT"
            or self.dimensions
        ):
            raise ValueError("Object count requires object units and dimensionless snapshot grain")
        return self


class DefinitionSnapshot(Model):
    valid_at: AwareDatetime
    known_at: AwareDatetime


class ObserveRequest(Model):
    metric: Pin
    invocation_id: UUID
    expected_receipt_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    valid_at: AwareDatetime
    known_at: AwareDatetime
    definition_snapshot: DefinitionSnapshot | None = None


class MetricOutput(Model):
    key: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]{0,127}$")
    state: Literal["VALUE", "UNAVAILABLE"]
    value: str | None = Field(pattern=r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$", max_length=128)
    unit: Unit
    grain: str = Field(min_length=1, max_length=128)
    dimensions: list[str] = Field(max_length=20)
    company: Pin | None
    valid_at: AwareDatetime
    known_at: AwareDatetime
    coverage: Literal["COMPLETE", "PARTIAL"]
    contributors: list[Pin] = Field(max_length=1000)

    @model_validator(mode="after")
    def shape(self):
        if (self.state == "VALUE") != (self.value is not None):
            raise ValueError("Unavailable value must be null; zero remains a value")
        ids = [p.resource_id for p in self.contributors]
        if len(ids) != len(set(ids)) or len(self.dimensions) != len(set(self.dimensions)):
            raise ValueError("Contributors and dimensions must be unique")
        return self
