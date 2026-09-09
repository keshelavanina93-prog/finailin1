"""Exact decimal, complete double-entry bundle contract."""

import re
from decimal import Context, Decimal, localcontext
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class JournalManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract: Literal["balanced-journal/1"]
    line_ids: list[UUID] = Field(min_length=2, max_length=99)

    @field_validator("line_ids")
    @classmethod
    def unique(cls, values: list[UUID]) -> list[UUID]:
        if len(set(values)) != len(values):
            raise ValueError("Journal membership contains duplicate lines")
        return values


def balanced_amounts(lines: list[dict]) -> dict:
    with localcontext(Context(prec=40)):
        debit = credit = Decimal(0)
        for line in lines:
            amount = line.get("amount", {}).get("amount")
            if not isinstance(amount, str) or not re.fullmatch(
                r"(?:0|[1-9][0-9]{0,19})(?:\.[0-9]{1,6})?", amount
            ):
                raise ValueError("Journal amounts require bounded exact decimal strings")
            value = Decimal(amount)
            if value <= 0:
                raise ValueError("Journal amounts must be strictly positive")
            if line.get("side") == "DEBIT":
                debit += value
            elif line.get("side") == "CREDIT":
                credit += value
            else:
                raise ValueError("Journal side must be DEBIT or CREDIT")
        if debit != credit or debit == 0:
            raise ValueError("Journal debit and credit totals must balance exactly")
        return {"debit": format(debit, "f"), "credit": format(credit, "f")}
