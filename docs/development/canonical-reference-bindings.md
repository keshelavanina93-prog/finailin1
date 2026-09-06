# Binding sources to existing canonical identities

NIN-26 shared-identity prerequisite. An ObjectBinding definition may set
`identity_mode` to `CANONICAL_REFERENCE`. Its `identity_field` must then be a
required source reference with the same endpoint type as the target schema.
An untyped vendor code is not a canonical identity.

Preparation resolves that visible, accepted master identity and builds an update
using its existing resource ID, identity key and expected version. It never
creates a replacement when the target is missing. A mismatched type, changed
effective version or redirected identity is rejected. Multiple selected source
rows resolving to one target remain an explicit conflict; no automatic
survivorship winner is invented.

The prepared update retains exact source-object, binding and target-schema
versions through the existing ResourceProposal. Review/promotion still checks
dependency changes and expected target versions atomically. The shared validator
also rejects creation through a canonical-reference binding and rejects target
redirects introduced after preparation, including redirects in the same proposal.
Existing source-key bindings keep their previous identity derivation behavior.

Impact analysis includes all retained source edges and continues enforcing hidden
consumer, entity, depth and size boundaries. Its live-topology cycle check separates
immutable `BOUND_SOURCE` provenance from live dependencies: an updated company can
derive from a source row that retained the old company version. Ordinary field
dependencies and source dependencies created together in the proposal remain cycle
checked. This does not change the exact versions stored in lineage.

This contract is available through the existing binding proposal and durable
Object Binding Action paths; neither directly modifies accepted objects. A
reviewed binding must provide all required target fields, and the ordinary
source-evidence and tenant/entity authority checks still apply. It does not
authorize financial posting, infer matches from names, or claim authentic-source
acceptance. Current engineering definition access remains internal; this is not
acceptance of the G8 product shell.

## Focused acceptance evidence, 2026-09-06

`G8_BINDING_DB_TEST=1 pytest services/api/tests/test_canonical_binding_identity.py
services/api/tests/test_dependency_impact.py::test_depth_size_and_real_cycle_fail_closed
--no-cov -q` passed 14 cases. The actual MinIO/PostgreSQL path retains and reads
synthetic document bytes, publishes its source evidence and chart observation,
prepares and reviews two distinct bindings, and verifies one company identity with
three immutable versions and exact source/binding/schema lineage. A newly added
co-proposed lineage cycle regression also passed in the focused integration case.

Redirects, future inactive revisions, target expiration, duplicate source targets,
invalid references and legacy source-key identity behavior are covered. The
existing live-cycle, depth and size refusals still pass. Independent code review
confirmed retained provenance remains in impact and visibility checks.

Ruff passes for changed production files and tests. Mypy passes for definition,
validation and impact modules; including `resources.py` reports five pre-existing
untyped domain-validation calls. The same diagnostics were reproduced from its
HEAD baseline under D:; no new mypy diagnostics were introduced. These results are
local contract/integration evidence, not authentic-source or browser acceptance.
