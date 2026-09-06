# Canonical interface property meaning

NIN-26 prerequisite implementation; this is not NIN-25 product acceptance.

An ObjectInterface property can declare `semantic_id` (a canonical SemanticContract
identity) and, for reference properties, `target_type` (a canonical ontology type).
For example, a company reference can require the CanonicalReference semantic and
the LegalEntity endpoint. An account reference cannot satisfy that property merely
because both values are UUIDs. Identifier properties can distinguish AccountCode
from CurrencyCode even though both use the same physical kind.

The existing definition preview, proposal and promotion APIs validate these
constraints. Interface publication resolves semantic and endpoint schema versions
through the common dependency resolver, so review impact and retained lineage use
exact shared versions. An implementation must match each declared constraint and
the existing kind/required-field contract. Different source field names remain
valid when their canonical meaning agrees.

Existing interfaces without the optional constraints remain readable and usable.
They do not gain a semantic guarantee automatically. Tightening an interface uses
a new reviewed version; existing implementations retain their old interface pins
and must be reviewed against the new version before participating in it.

No new persistence store, business identity namespace or role system is introduced.
The current production shell and browser acceptance remain separately governed by
NIN-25. The tests use explicitly synthetic data, never authentic company evidence.

## Focused acceptance evidence, 2026-09-06

`G8_BINDING_DB_TEST=1 pytest services/api/tests/test_interface_semantics.py --no-cov -q`
passed all nine cases against the native PostgreSQL runtime. The integration case
publishes an interface and implementation, retains exact semantic/schema pins,
and projects a synthetic company's canonical identity through `run_group` with
the exact interface/implementation/schema versions. An account endpoint offered
as a company is rejected. Ruff and mypy passed for the changed production files;
Ruff passed for the test file. These are local contract/integration results, not
authentic-source or browser evidence.
