# Derived decimal execution bound

Ontology DerivedProperty arithmetic retains the existing decimal context precision of
38 and its existing rounding behavior. It does not introduce accounting rounding or
currency interpretation.

Each arithmetic node may emit at most 4,096 characters in fixed decimal notation,
including a sign and decimal point. The evaluator computes the required length from
the Decimal coefficient and exponent before allocating the fixed-format string.
Oversized output becomes an explicit per-value `UNAVAILABLE` result. Decimal arithmetic
range exceptions, including overflow, also become per-value `UNAVAILABLE` results;
other objects in the same response continue evaluating. No clipped or fabricated
numeric value is substituted.

Literal and field observations retain their original representation. This bound
applies when arithmetic produces fixed-format output; it does not reinterpret source
values. Existing immutable object, schema and definition references remain intact.
Coalesce evaluates only through its first non-null value, so an unused oversized or
overflowing fallback cannot invalidate an available observation, including zero.

## Focused acceptance

The decimal-bound and coalesce regressions passed 23 checks (0.41 seconds), with
Ruff and targeted mypy passing. Tests cover overflow, finite large positive and
negative exponent expansion, sign/zero boundary lengths, unaffected sibling
values and exact immutable references. These are synthetic arithmetic fixtures.

After API restart, the production web proxy calculated five labels from retained
source account definitions. All remained available with exact definition/object
versions, and the saved run reopened identically. Reproduction:
`scripts/verify-derived-range-runtime.py`; evidence:
`docs/development/evidence/nin26-derived-range-runtime.json`.
This is source-label derivation and bounded execution proof, not financial
certification, full ontology completion or release acceptance.
