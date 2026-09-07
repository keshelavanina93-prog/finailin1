# Exact semantics for new platform installations

The isolated integration candidate also passed a separate committed-install and
database-restart proof. `scripts/verify-platform-bootstrap-restart.py create`
creates a synthetic platform tenant only on the explicitly guarded disposable
CI database at port 55441. After an owned `pg_ctl restart` of that cluster,
`verify` checks unchanged hashes of identities, versions, heads and dependencies,
then verifies replay creates nothing. The mounted product database is excluded
by exact data-directory and port checks. The retained fixture and outcome are in
`evidence/nin60-bootstrap-commit-restart.json`; this proves local PostgreSQL
persistence, not whole-system recovery or release acceptance.

The installer now retains SEMANTIC field dependencies to exact approved platform
SemanticContract seed versions when creating a new SchemaDefinition. Identities,
versions, heads and dependencies share one transaction; unavailable, foreign or
incompatible semantic versions abort publication. Success is printed after commit.

New schema publication acquires the existing canonical tenant lock and applies
the shared `upstream_authority` guard to its exact dependencies. An immutable seed
row marked APPROVED is insufficient if its effective version has changed or its
canonical lifecycle declares withdrawal or unavailability. The installer refuses
the new schema; it never substitutes a newer semantic version or editing head.

Existing identities are skipped completely, including their attributes, versions,
heads and dependencies. Re-running the installer cannot restore a removed head or
silently backfill historical schemas. Historical schemas without retained semantic
edges continue to expose schema-only analysis with explicit unavailable semantics.
Repair requires a separately reviewed successor through canonical resource review.

`scripts/verify-platform-bootstrap.py` is restricted to the disposable CI database
on loopback port 55441 and a D: data directory. It exercises all 142 platform
definitions (18 semantics, 96 schemas, 28 link types) and all 438 semantic edges
against the actual PostgreSQL constraints in a rolled-back fixture transaction.
It compares complete retained rows before and after replay, including a separately
reviewed semantic successor and a deliberately removed fixture head.

The proof uses the actual canonical proposal and independent lifecycle review
services. Only their connection ownership is adapted to the encompassing rollback
transaction. New schema publication is refused after semantic supersession,
UNAVAILABLE lifecycle state, REVOKED lifecycle state, or a foreign semantic identity;
each failure leaves no partial identity, version, head, or dependency. Existing
identities still replay unchanged even after semantic withdrawal. Both fixture
tenants retain zero rows after rollback; no company or account facts are created.

Recorded evidence is a native rollback contract pass. A committed installation,
restart, historical schema repair and release acceptance remain separate gates.

This branch remains isolated while NIN-61's canonical CI gate is red.
