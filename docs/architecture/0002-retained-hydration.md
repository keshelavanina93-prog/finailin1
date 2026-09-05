# Retained hydration foundation

Binding source: Linear project `05b708c1-68be-4490-a81a-4bb19706479d`,
NIN-24 and NIN-27, inspected 2026-09-05. The Enterprise Hydration, Authority
Compiler & Operator UX Binding Contract remains the acceptance authority.

## Implemented boundary

POST `/v1/hydration/ingest` authenticates a bearer credential mapped server-side
to one ExactScope. Source scope must equal that grant. Required fields cannot be
omitted or broadened. The server selects `tb/1` or `tabular/1` from structural
headers; the client cannot supply a more permissive authority policy. Unsupported
object requests return 403. Header recognition is structural, not authenticated
source certification. The legacy compile endpoint is an authenticated preview
whose fields are all non-authoritative.

UTF-8 CSV is bounded to one million characters, 128 columns and 10,000 rows.
Original submitted UTF-8 bytes (including BOM) are hashed and retained in the same
transaction as the receipt and request. No caller-provided URL is fetched.
TB accounts preserve leading zeroes; decimal calculations use a 50-digit context,
nonnegative values below 1e24 and at most six decimal places. Duplicate accounts
require dimensional review rather than aggregation. Rejects prevent reconciliation
PASS. Unfamiliar columns remain raw observed source records with no business meaning.

Receipt identity hashes the full scoped request. Identical requests replay the same
receipt. Changed filenames or scope are different requests. Source hashes remain
content-based. Source provenance, bindings, ignored fields, rejects, warnings,
function versions and the ordered compilation plan are persisted. No AI is called.
The plan is a compilation trace, not a durable workflow execution engine.

PostgreSQL stores source bytes and JSONB receipts with database hash checks, forced
tenant RLS and immutable update/delete/truncate triggers. Runtime credentials have
SELECT/INSERT only, no DDL, superuser or RLS bypass. Full scope is also applied to
reads. Database administrators remain a trust boundary; off-host WORM retention
and signed audit chains are future work. Ingested time is database-generated;
full bitemporal history and credential-level actor audit are not yet implemented.

## Acceptance mapping

| Linear requirement | Evidence or remaining work |
| --- | --- |
| NIN-24 shared source kernel | Same compiler handles TB and unfamiliar UTF-8 tabular sources |
| Runtime forbidden creation | Tests deny invoice/journal/inventory creation from TB |
| Separate inference and derivation | Executed Decimal functions; no inferred business authority |
| Receipt reconstructs candidate basis | Hash, source row, function and input values retained |
| Progressive mapping reuse | Not implemented |
| Authenticated browser journey | Ingest and inspect candidates/receipt; promotion remains absent |
| NIN-27 retention and policy | Forced tenant RLS, exact-scope reads, immutable evidence tests |
| NIN-27 complete state/time kernel | Bitemporal, revocation, policy propagation remain open |

No Linear epic is marked complete by this foundation.
