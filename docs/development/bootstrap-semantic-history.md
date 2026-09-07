# Exact semantics for new platform installations

The installer now retains SEMANTIC field dependencies to exact approved platform
SemanticContract seed versions when creating a new SchemaDefinition. Identities,
versions, heads and dependencies share one transaction; unavailable, foreign or
incompatible semantic versions abort publication. Success is printed after commit.

Existing identities are skipped completely, including their attributes, versions,
heads and dependencies. Re-running the installer cannot restore a removed head or
silently backfill historical schemas. Historical schemas without retained semantic
edges continue to expose schema-only analysis with explicit unavailable semantics.
Repair requires a separately reviewed successor through canonical resource review.

`scripts/verify-platform-bootstrap.py` exercises the actual PostgreSQL constraints
inside a rolled-back fixture transaction. Evidence records exact edge retention,
idempotent replay, unchanged existing schema attributes, failed foreign-semantic
publication and zero retained fixture identities. It creates no company/account
facts and does not claim historical repair or release acceptance.

This branch remains isolated while NIN-61's canonical CI gate is red.
