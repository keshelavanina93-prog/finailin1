# SEG January 2025: guarded posted account movements

This implements a real, partial account-movement report over the retained January
2025 SEG Base, using the user's reviewed statutory/reglamented 1C book, GEL,
`Сумма` as posted, and posting-derived VAT. `Amount` is non-authoritative. It does
not create journals, infer financial statement classifications or certify a ledger.

The native `accounting.retained-posted-movements/v1` Function records exact direct
pins for the source, scope, binding, mapping and all38 accounts. It rereads the
retained source hash, applies the shared accounting and material-authority guards,
and sums exact decimals separately for each account and posting side. Every group
retains its original source-cell contributors; exclusions preserve complete source
rows. This is one shared Functions/Transformation implementation, not a separate
report formula or private identity registry.

## Authentic retained result

- Original source hash: d7c7e67c093b40b6f9209b301ca8fab7e4febc85c27d735babb95fa2028a8f0a.
- Scope:23558068-046d-5fed-8582-3211ea2f2199.
- Reviewed binding:f4cf95a5-9552-519c-8e59-96ee06bd4308 / e8c68d4b-e69f-5e21-9bd5-256420146404.
- Function:94c26511-53bf-5dd4-97e8-b89a11334bd3 / aa17de9f-16a8-5b1a-b2c7-a6ae33baedea.
- Native DAG:transformation:6dd2188a-72eb-4550-ae8e-e98004a91493.
- Invocation:c3f68247-7e04-5934-9e27-041754bd9168.
- Publication:pub_7d7e10adf9a5174a5d11009db4ab72bb6287efbab091e35655641501c0486477.
- Coverage:596 retained rows;595 included amounts; Base!S288 excluded because no literal posted amount exists.
-59 account/side groups. Each side's exact posted control sum is12502967.2300000000006576 GEL.

The control sum is a total of the supplied postings, not revenue, profit, a balance
sheet, cash flow, or complete trial balance. Ledger completeness remains explicitly
UNESTABLISHED. The workflow retained596rows and3592612PostgreSQL JSONB UTF8bytes.
Shared activity services executed the DAG directly; an actual Temporal worker and
restart/recovery proof is still required in main integration.

## Verification

The authentic Function and DAG publication passed the native database guards.
Rollback-only negative probes rejected altered totals, currency, removed exclusions
and missing authority proof. Saved history reopened with the same receipt hash;
another company received404.47 focused tests passed, with2 opt-in database tests
skipped; the explicit authentic run supplies separate database evidence. Targeted
Ruff, mypy, frontend ESLint, TypeScript and the production build passed. Browser
verification used isolated8063/3063, with company→retained source→interpretation→
calculate→account groups→source rows/exclusion. The report displays595of596 coverage.

Full machine evidence and exact pins are in `evidence/nin49-posted-movements.json`.
The retained calculation itself remains in canonical storage, not duplicated here.

## Main integration

Apply migration062 after the main branch's061; preserve the existing061 materialized
observation guard. `scripts/replay-seg-posted-accounting.py` defaults to no writes;
with `--apply` it uses the target checkout's configured separate proposer/reviewer,
verifies the original source hash and existing company alias, and uses the same
native stable identities. Conflicting existing mappings/schema fields fail closed.
An idempotent replay on vertical retained the same binding version and guarded-use
eligibility. It never copies the isolated database or changes source bytes.

After the merged code/migrations are frozen, publish a Function against the target
runtime's manifest and exact target versions; isolated Function manifest hashes are
not portable across a different codebase. Retain only provisional OBSERVED input
availability unless stronger evidence is separately established. Publish a one-node
Transformation with1000returned-row/0derived-evaluation/16MB budgets and direct source
scope/binding pins, then execute using an existing principal with publication ingest
permission. Do not manufacture an ingest grant for the ontology steward.

`scripts/verify-posted-movement-run.py INVOCATION --probe-sql-guards` reopens the saved
result and runs rollback-only negative probes in the configured scope. A compatible
later-source refresh, persistent business Finding, independent financial acceptance,
actual worker recovery and complete milestone acceptance remain open.

Use `scripts/prepare-seg-posted-report.py --apply` after replay and the final target
runtime freeze. It publishes/reuses the same native Function and Transformation
identities, pins current target versions, records provisional input availability
through separate review and prints the exact references for the worker request.
Both replay and definition preparation were exercised against the existing vertical
state; the reviewed accounting binding and Function version were retained unchanged.
