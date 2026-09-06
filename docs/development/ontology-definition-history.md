# Historical ontology definitions

NIN-27 prerequisite: historical object queries must not silently use today's
definition when no definition version was explicitly selected.

The definition detail and library APIs accept `valid_at` and `known_at` with
timezone-aware timestamps. With no explicit version, detail resolves the newest
recorded version within both requested boundaries. Revocation is evaluated after
selection, so an applicable revoked version cannot reveal its older approved
predecessor. Tenant and entity visibility remain enforced by the existing
resource connection and policies.

Saved Object Set and interface/type-group execution use the same temporal
definition lookup. An explicit `version` remains an intentional replay choice:
it selects that retained definition while the query timestamps select its data.
This permits a definition saved today to reproduce older observations. Responses
retain `definition_version_id` and exact dependency pins so the distinction is
auditable. Definition lookup without time or version remains the current-head
lookup used by editing and publication conflict checks.

This adds no new history store and rewrites no accepted definitions. Product and
authenticated browser acceptance remain open independently of backend checks.

## Focused acceptance evidence, 2026-09-06

`G8_BINDING_DB_TEST=1 pytest services/api/tests/test_definition_history.py --no-cov -q`
passed all four cases using native PostgreSQL and authenticated in-process HTTP
requests. Both Object Set and type-group corrections reconstruct the original
definition and objects at the earlier knowledge time. Future-effective exclusion,
revocation without resurrection, explicit version replay, missing authentication,
tenant/company isolation and timezone validation are covered. Ruff and mypy pass
for the changed production files. Evidence is synthetic local integration only;
the browser and authentic-source gates are not established by these checks.
