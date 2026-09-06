# Authority checked ontology calculations

NIN-27 now connects deterministic fact aggregation to the existing canonical consumption guard.
`POST /v1/ontology/model/facts/{identity}/aggregate/guarded` accepts the normal aggregation query,
grouping and snapshot date plus a canonical consumer `{resource_id, version_id}`.

The consumer must already be accepted, current and effective, declare `minimum_authority_state`,
and record direct dependencies covering the exact fact contract, its pinned schema and every
selected fact version. Every direct consumer dependency is checked, including additional pins
outside the calculated subset. The request cannot weaken the accepted minimum. Over 1,000
distinct dependency pins is explicitly refused; no pins are truncated. This boundary checks
material authority and availability; it does not establish query completeness or certify finance.

Aggregation retains its existing deterministic arithmetic, grain, source-use and temporal rules.
Its result now includes the exact schema identity/version as well as the existing contract and
fact pins. Before returning any guarded result, the shared guard rechecks current versions and
lifecycle under the canonical tenant lock. The content-addressed calculation retains the
guard receipt reference, proof hash, check time and lifecycle evidence. Full input attributes
remain in the immutable consumption receipt rather than being copied into calculation metadata.
It remains `SOURCE_BOUND_ANALYSIS`
with no financial certification, including when authority checks pass. Unavailable/incomplete
calculation states remain unchanged.

Retained calculations explicitly carry `current_use_authorized: false`: they are evidence of
what was checked at that time. Subsequent correction or withdrawal cannot rewrite that proof;
a new execution must pass a new authority check. Consumption status remains available through
the existing lifecycle API. No schema migration or parallel identity/authority registry is added.

In the replacement G8 shell, a selected consumer's inspector opens Accounting contracts with
that canonical selection preserved. Aggregate execution uses the guarded endpoint automatically
for that selected consumer; results show the retained authority check and calculation reference.
Existing exploratory calculations and reconciliation remain explicitly non-certified analysis.

## Verification boundary

Focused native PostgreSQL/authenticated API coverage proves accepted minimum enforcement,
all direct dependency checks, mismatched-version refusal, retained proof integrity, withdrawal
blocking another execution and exact-company denial of retained runs. The guard integration
test supplies synthetic aggregation output; it is not authentic-source calculation acceptance.
Separate deterministic fact contract tests cover arithmetic and source-use refusal. Web
TypeScript, focused ESLint and isolated production build pass. Browser interaction and premium
visual acceptance remain unverified; this does not complete NIN-25, NIN-27 or the product.

## Current authority inspection

`GET /v1/ontology/model/fact-runs/{run_id}/authority` first checks access to the retained
calculation, validates its receipt hash and then evaluates current dependency status through
the same lifecycle service. It creates no new consumption receipt and never changes the run.
It returns `BLOCKED` or `RECHECK_REQUIRED`, always with `current_use_authorized: false`.
Exploratory calculations without a retained check cannot acquire authority through inspection.

Opening a guarded calculation in G8 shows current status, named affected resources and the
reason for each blocker. Evidence buttons open the existing canonical trace with the recorded
resource/version and company context preserved. Refresh re-inspects current state without
rerunning arithmetic. The focused PostgreSQL/API test covers before/after withdrawal,
unchanged historical evidence, no new receipt, authentication and company isolation.
