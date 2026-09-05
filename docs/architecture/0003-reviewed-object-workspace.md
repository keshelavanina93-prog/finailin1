# Reviewed construction and object workspace

The full product requires a reusable enterprise substrate, deterministic domain
logic, governed intelligence/actions and a unified operator application. This
change connects the existing hydration engine to review, accepted versions,
object navigation, lineage and exports. It is part of NIN-24/NIN-27/NIN-28, not
completion of those epics or the full platform.

## Implemented behavior

- Server-issued Principal binds actor, display name, exact scope and permissions.
  Local operator and reviewer keys are separate. Existing keys preserve their
  actor fingerprint and gain no review permission. Enterprise SSO is still needed.
- Ingest retains the submitter identity. Intake and history query durable records
  by tenant and full scope with pagination. No static example counts are displayed.
- Review shows source contract, compilation stages, candidate values, rejects,
  deterministic functions and added/changed/removed/unchanged object counts against
  the accepted construction. Account identity uses account code; unfamiliar source
  records use row position, explicitly not semantic business identity.
- Decisions require an identified submitter and a different reviewer, a meaningful
  reason, and a UUID idempotency key. Approval also requires candidates, zero rejects,
  passed TB reconciliation and a matching expected current version. The transaction
  serializes competing decisions within the exact scope.
- Review decisions and accepted objects are append-only. Approval atomically writes
  accepted objects and advances the current construction pointer. PostgreSQL guards
  enforce same-scope approval and candidate-content preservation. Earlier versions
  remain accessible by receipt ID. Rejection does not create accepted objects.
- The object workspace supports type and value filters, paging, current versions,
  pinned historical versions, and source-row inspection with approver/rationale.
- Export retains the original UTF-8 CSV or produces an evidence JSON bundle with
  scope, source hash, receipt, decision and explicit NOT_CERTIFIED status.

Approval means reviewed construction, not financial certification or ERP posting.
The current pointer is one construction per source class and exact scope. A new
approval replaces that class's current view; it does not append monetary values
from different snapshots. Multiple independent source collections, dimensional TB
identities and multi-resource promotion must use the future shared schema/identity
and proposal registries before broader aggregation is introduced.

## Dependency order for the full software

1. Shared versioned schemas, semantic contracts, identities, policies and resource
   dependencies (NIN-26/27/28). Reuse these across source collections and domain packs.
2. Semantic mapping proposals and approved mapping reuse, generic pack activation,
   durable pipelines, drift handling and incremental enterprise hydration (NIN-24).
3. Canonical finance modules, exact decimal Functions, account mappings, statements,
   reconciliation, group journals and deterministic reporting (NIN-17 through NIN-23).
4. Operator metric/table/graph applications consuming those shared versions, plus
   NYX explanations and proposals with governed Action execution and readback.
5. Release/runtime administration, enterprise identity, external connectors and
   independent production acceptance across authentic data and operational failures.

The mounted workspace must grow along that dependency chain. Finance-local hidden
state, hardcoded financial reports and authority inferred from a model response
would bypass the architecture and are not acceptable shortcuts.

## Delivery evidence for this change

Migrations 002 and 003 applied to the D:-local PostgreSQL cluster. Python strict
type checking and the TypeScript/Next.js production build passed. The API and web
runtime were launched locally. No tests were added or executed, and no browser
acceptance or financial certification is claimed, per the requested build focus.
