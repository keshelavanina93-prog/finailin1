# NIN-17 source movement candidate

Base: `development/enterprise-hydration-foundation@30a6948c4b6c5cbe90e18ebfca10d3c316c2654c`.
Isolated worktree: `D:/FinAI/g8-finance-journal`; branch `development/nin17-entity-journal`.

The candidate extends the existing `accounting.retained-posted-movements/v1` Function with an opt-in `entity_movement_review` declaration. Existing definitions omit this field and retain their previous result shape. The new result records source posting-pair candidates, exact debit/credit/net account movements, exclusion coverage, and a content-hashed reconciliation receipt. The existing semantic analysis endpoint provides the paired movement table and original-cell drill through `semantic-analysis/2`: debit, credit and net movements are exact decimal attributes with `aggregation=NONE`, `measure=null`, `visual=NONE`, and `row_noun=objects`. This introduces no approved measure, frontend changes or second registry.

## Authentic evidence and limits

`evidence/nin17-entity-movement-review.json` records a **read-only local compiler proof**, using ordinary operator access, exact historical Function dependencies and SHA-verified retained original bytes. It is not a newly published Function result or live integrated API proof.

- SEG source SHA: `d7c7e67c093b40b6f9209b301ca8fab7e4febc85c27d735babb95fa2028a8f0a`.
- Retained input invocation: `c631bb9c-f92e-5dd9-a693-233c1b3b7925`.
- 596 retained rows; 595 included source pairs; 37 movement accounts.
- Exact source, debit-pair and credit-pair controls: `12502967.2300000000006576` GEL.
- Sole missing-literal exclusion: `Base!S288`, `MISSING_LITERAL_POSTED_AMOUNT`. Original row, supplementary AD amount and formula evidence are preserved. No substitute amount, zero filling or VAT transformation occurs.
- All 595 rows encounter the existing canonical publication profile gate (`seg_expense_base` is not `1c_journal`). All 1,190 sides lack a reviewed SEG account-dimension policy. Additionally, 52 source rows do not satisfy the existing strictly-positive, maximum-six-fractional-digit journal amount contract. The compiler preserves their original precision/sign; it does not weaken those guards.

**There are zero newly accepted canonical JournalEntry/JournalLine resources.** Pair IDs are proposed locators derived from company, ledger, book, recorder and recorder-line, not published identities or invented source documents. The journal trial balance and journal control totals are null. Source movement totals are clearly separate. This is the strongest supported fallback required by the NIN-17 instruction, not completion of NIN-17's accepted-journal journey.

Posting dates, ledger/book/period/currency relationships and exact account/chart versions use the existing validation contracts. Missing dimension authority is explicit, never an inferred empty policy. An existing policy alone does not establish reviewed side-specific assignments. Opening/closing balances, subledger drill, financial statement mapping and certification remain unavailable.

## Builder verification

Focused kernel and existing semantic-workspace tests cover exact Decimal values, source exclusions, no inferred journal acceptance, profile/policy/precision blockers, company/book/currency/period/chart/version mismatches, duplicate recorder identity, schema-compatible existing behavior, paired workspace values, original-cell selection, stale descriptor, wrong company and tampered reconciliation refusal.

Run the selected tests with repository dependencies and `PYTHONPATH=services/api/src`:

```powershell
python -m pytest services/api/tests/test_entity_movement_review.py services/api/tests/test_semantic_entity_movements.py services/api/tests/test_posted_movements_function.py services/api/tests/test_semantic_analysis.py -o addopts='' -p no:cacheprovider -q
```

Frozen builder verification: **42 tests passed**, Ruff passed on all changed Python files, and focused mypy (`--follow-imports=skip --check-untyped-defs`) passed on the five compiler/adapter/helper files. The preparation helper help command and `git diff --check` also passed. The new Function has not been applied to native data.

This focused command intentionally does not claim the repository-wide CI coverage gate; NIN-61 owns that gate. No CI configuration or frontend file changed.

## Integration sequence

1. Integrator waits for canonical CI green and merges the frozen candidate in the established NIN-59/NIN-17 sequence. Preserve historical manifests and results.
2. Restart API/worker from one exact integrated package. Do not mix manifests from the isolated worktree and mounted API.
3. Run `scripts/prepare-seg-entity-movements.py` read-only to inspect the new Function declaration. `--apply` uses existing separate-actor review and normal operator execution, with version-keyed idempotent invocation. It creates no journal, binding, schema or policy.
4. Open the returned invocation through `/v1/ontology/analysis/project` with SEG company `365aa5d9-c2ec-52e1-867a-50fe3415f486`. Verify 37 account rows, exact source-side controls, net movement, exclusions, original-cell drill and preserved history. Shared Function result storage retains the reconciliation with the result.
5. Independent NIN-50 assesses only the integrated candidate after canonical CI green. API/worker/browser/restart and domain acceptance remain open.
6. A successor must resolve the governed SEG journal source adapter, exact amount representation and source-supported account-dimension rules/assignments before it can publish any journal or claim a journal-derived trial balance. Do not mark the broader finance journey complete from this fallback.

## Integration review repair

The first frozen candidate `2f0ce4a` mixed `/1` with ATTRIBUTE fields and was correctly rejected by the frontend SDK. The replacement uses the existing `/2` table-only contract for all three movement attributes, with no measures or chart. NIN-59 confirmed its presentation branch preserves this contract and needs no extension.

`python scripts/verify-nin17-projection-sdk.py` (Node 22+ and repository Python test dependencies) produces actual backend initial, contributor-selected and filtered/grouped projections, then calls the unchanged frontend `assertProjection` directly. All three pass. Three negative checks reject the original mixed `/1` regression and forbidden measure/chart claims. The SDK source SHA-256 is `5628c90ecd831b8833ee2e0c53194042cc2a85daec87405d5e1b10c3ba3a9536`. All 42 focused Python tests still pass. This is local backend/frontend SDK compatibility evidence; it is not mounted browser/runtime or independent acceptance.
