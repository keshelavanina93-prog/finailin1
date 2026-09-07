# SEG source chart review

NIN-49 extends the existing source account review in G8. Users select exact retained
definition versions for literal source codes, explain their applicability, and submit
up to twenty accounts through the shared proposal/review lifecycle. Nothing is
preselected. Existing LocalChartOfAccounts/LocalAccount identity derivation is reused.
No new identity store, financial metric, report formula, journal, or approval model is
introduced. A partial chart is not complete accounting configuration.

The backend rereads retained bytes and the accepted company alias, checks the source
hash and exact code/definition version, and retains company/alias/definition pins and
source-cell relationships. Existing conflicting accounts are rejected rather than
overwritten. Permissions and canonical publication validation remain shared.

Verification used a separate PostgreSQL cluster on 55440 and a retained snapshot of
horizontal state, with API 8063 and built G8 web 3063. Original source bytes were read
from the existing evidence store; no source upload, horizontal database mutation,
definition publication or financial approval was performed. The retained draft
proposal is an integration candidate, not a business decision.

Ten focused checks passed; the first invocation also applied the whole-suite coverage
threshold and therefore exited nonzero. The six new checks were subsequently run
without whole-suite coverage and passed. Targeted Ruff, mypy, frontend ESLint,
TypeScript and the dependency-ordered production build passed. Authenticated web
proxy readback returned the retained four-mutation draft after the originating test
process ended. See the adjacent machine-readable evidence.

Browser acceptance is unverified: Chrome exited with code 21, Edge exited before
exposing its debugging endpoint, and the in-app browser timed out. A combined API
restart/readback command was rejected by automatic approval review as blocked by
policy; separate read-only web-proxy verification succeeded. Restart/recovery is not
claimed. No financial report, compatible refresh, Finding, or release is accepted.

The live January 2025 SEG source still lacks an approved chart and accounting binding.
Ledger/book, functional currency, amount field, VAT treatment and mapping semantics
cannot be inferred. These are required before authentic financial computation.

Runtime fixes supporting this checkout: registered D: Git worktrees are admitted by
the storage guard with per-checkout containment; PostgreSQL supports an explicit port
and refuses an already-running cluster on a different port; starting only API/web no
longer requires installing or managing an unrelated local MinIO service.

## Reviewed interpretation applied on 2026-09-07

The user explicitly supplied the statutory/reglamented 1C book, GEL functional
currency, `Сумма` as the posted accounting amount, and as-posted VAT treatment.
`Amount` remains losslessly retained and non-authoritative. The decision is retained
as USER_ASSERTED configuration; the chart alone does not establish the Base amount
columns. No global VAT addition or removal is permitted.

In the isolated vertical database the canonical review path retained 38 exact account
identities, the accounting scope, book/ledger/period/currency, source identity mapping
and dimension-preservation policy. Financial statement and canonical analytical
classification remain unestablished. Binding f4cf95a5-9552-519c-8e59-96ee06bd4308,
version e8c68d4b-e69f-5e21-9bd5-256420146404, is approved configuration. Its first
material lifecycle event records OBSERVED / INFERRED / PROVISIONAL / AVAILABLE;
no reconciliation, authoritative financial totals or certification is claimed.

After a separately managed API stop and start, authenticated web-proxy inspection
returned HTTP 200 at 15:57:16 UTC with ELIGIBLE_FOR_GUARDED_USE. This supersedes the
historical restart limitation and unbound-meaning statements above. Each calculation
still requires its exact consumer authority checks. Base!S288 is absent and remains
quarantined; it must never inherit supplementary Amount zero. Source coverage is
595 rows with amounts out of 596 retained rows, not complete ledger coverage.

The source profile now exposes shared repeated-recorder-key findings and refuses
binding promotion with duplicate posting identities. The company projection exposes
only retained source aliases with exact company version pins; UI source selection
uses those authorized document references. Focused accounting/source/company tests:
32 passed. Full financial report, browser acceptance, refresh and Finding remain
pending at this checkpoint.
