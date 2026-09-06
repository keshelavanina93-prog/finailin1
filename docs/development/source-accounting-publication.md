# Authentic company account bindings and source facts

The retained SGP annual trial balance and Sakorggazi November procurement journal
now supply account usage to the shared ontology. Source account codes resolve to
exact accepted versions of the retained 1C account definitions. Company charts
represent the observed subset; they do not assert chart completeness, ledger
identity, statutory classification or mandatory dimension rules.

SGP has 93 distinct observed account codes and 23 source control groups. Sakorggazi's
November journal uses four codes. All 97 company-specific LocalAccount identities
were reviewed and published. Their chart references, definition-version dependencies
and source-cell relationships are persisted canonically. Account `3340.10` was stored
as the numeric value `3340.1` with Excel format `0.00`; the binding reader preserves
the displayed identity. It rejects number formats that would round or guess a code.

## Separate source grains

`SourceJournalMovement` retains one original movement row, its debit and credit
account references, source document, date, amount and original cell values/types.
It does not create two copies of the monetary measure or synthetic ledger postings.

`SourceTrialBalanceRow` retains each original nonempty data row, period bounds,
source outline ancestry and separate opening, turnover and closing debit/credit
measures. Blank measures remain absent. Source account summaries, analytical rows,
control groups and unresolved rows remain distinguishable.

The SGP source contains 5,532 nonempty data rows: 97 account-summary rows, 5,403
analytical rows, 23 control groups and nine unresolved rows. Repeated account rows
for 3370, 7310.01, 7410 and 7410.01 are preserved and flagged for reconciliation.
They are not additional authoritative balances by default. Sakorggazi TR contains
246 movements dated November 2025. The May `Data SOG` sheet is a different source
profile and period and is not silently combined into this publication.

Source observation schemas deliberately leave currency and ledger authority
unestablished. Both definition validation and aggregation execution reject their
direct use as financial fact contracts. Subsequent reviewed ledger, unit,
representation and analytical bindings must produce the authoritative financial
representation. Source publication alone does not complete NIN-17/18, reporting,
consolidation, EBITDA or SGG regulatory reporting.

## Operator and publication paths

Data → Original source documents → source format and worksheet → Inspect account
usage → reviewed company → account-page proposal or typed accounting-row inspection.
Each fact row displays its current publication state separately from source row count.
All proposals use the existing independent review and exact version validation path.

`scripts/publish-source-accounting.py` supports resumable bulk publication with
explicit author, reviewer, source, company and `--approve`. It verifies existing
canonical rows rather than trusting a local progress counter. Progress files are
written atomically beneath `.finai/artifacts`. Failed transactions cannot partially
publish a page. Canonical original-source and company/account versions remain the
authority; progress JSON is operational evidence only.

Current head lookups are batched, avoiding one connection plus history expansion
per source row. Workbook parsing alone has a two-entry cache, keyed by immutable
bytes and profile. Returned fields are copied; current authorization and canonical
version resolution are never cached. Original bytes are scope-authorized and
integrity-verified before reuse of parsed content.

## Persistence work exposed by authentic loading

Migrations 027–030 retain existing review, visibility and version-pin invariants:

- Validate one approved dependency pin instead of repeatedly projecting the entire
  proposal for every inserted edge. The helper checks tenant and source visibility.
- Traverse the union of required proposal lineages once, including restoration and
  historical-impact dependencies. Missing versions still deny access.
- Fast-path schemas without field-specific policies; restricted or malformed policy
  definitions retain the previous checks.
- Index proposal recency and canonical type; push immutable object-type filtering
  before temporal version selection in typed resource inventories.

The existing and updated proposal predicates agreed across 18 retained-proposal
permission cases, including protected-field histories. The field predicate agreed
across 20 cases including absent, restricted and malformed policies. Temporary
comparison functions were rolled back; no new demo resources were published.
An actual forged dependency was rejected and rolled back; unrelated company and
tenant probes were denied. These checks substantiate the changed persistence path,
not a production-scale certification.

Local publication evidence: `.finai/artifacts/company-account-publication.json`,
`.finai/artifacts/source-accounting-publication.json`, and
`.finai/artifacts/sgp-source-facts-publication.json`. Consult the canonical inventory
and completed job state before claiming the full source load is published.
