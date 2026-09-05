# Canonical field read policy

NIN-27 local contract, migrations 020–021. This is substrate acceptance evidence,
not acceptance of the complete G8 product or of downstream Finance/NYX surfaces.

Canonical SchemaDefinition fields can declare `read_permissions: ["restricted_read"]`.
The policy is pinned to the schema version that validated each resource version.
PostgreSQL applies it to the resource and every exact retained dependency. If a
reader lacks a required permission, the complete resource is withheld; this first
contract deliberately does not return partly redacted values that could change
their meaning. Derived resources cannot shed restrictions through a new schema.

The same check protects proposed mutations and external dependencies, accepted
identities, review/impact records, lifecycle evidence, consumption receipts and
stream records. `ontology_admin` does not imply `restricted_read`. Existing local
credentials receive no additional clearance. Schema evolution records additions
as semantic changes and rejects removal of existing required permissions.

The runtime supplies authenticated permissions in transaction-local database
context. A NOLOGIN policy-reader role has read-only access to the five canonical
metadata tables needed to traverse lineage without recursive RLS evaluation.
Security-definer functions fix their search path, validate tenant context, and
are executable only by the runtime and policy-reader roles. Runtime credentials
remain a trusted service boundary, not credentials for untrusted direct SQL.

Verification on the local D: PostgreSQL runtime:

- The focused derivation test proves cleared access and uncleared denial for the
  source, derived consumer, proposed mutations, identities, review metadata,
  current consumption and historical receipt/status. Retained before-values and
  downstream impact remain protected; hidden field-restricted dependents block
  incomplete impact analysis.
- A policy-compatibility check rejects weakening and unsupported permissions.
- Eight existing lifecycle, mixed-policy promotion, binding and event-time tests
  passed against the migrated database.
- The running web proxy returned HTTP 404 for a retained synthetic protected
  receipt and its status using an existing administrator without clearance.
- Contracts and web TypeScript checks passed.

These tests use explicitly synthetic records. Version-pinned field policy does
not retroactively classify unbound raw source evidence. Broader retention/deletion
contracts and real downstream product journeys remain open in Linear.
