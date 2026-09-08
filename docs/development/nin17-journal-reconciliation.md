# NIN-17 exact source-to-journal consumer

Base: `0212bc4d8b7b23bd6f327c1b77e3a085d8b5d64e`, canonical GitHub run `34175076861` successful. Isolated worktree: `D:/FinAI/g8-journal-reconciliation`, branch `development/nin17-journal-reconciliation`. Implementation commit `ceb8641258f4d7589f0ba52ebd034be1ef8bd1a1` was pushed before this evidence document.

`GET /v1/ontology/company-journals/reconciliation/source/{invocation_id}?company_id={company_id}` adds a read-only finance consumer. It revalidates the retained source review, resolves exact source context dependencies, scans the existing bounded canonical journal readback at one timestamp, and matches complete canonical debit/credit bundles to included source cells. It checks the existing journal profile/date/binding guard, exact account versions, original amounts, evidence identity and historical dimension completeness. Duplicate journals or duplicate accepted claims to a source cell cannot be counted twice. Unresolved scan coverage is refused.

The content-hashed receipt separates source amount, matched source amount, journal debit/credit controls, missing cells, rejected journals and excluded source rows. Its movement trial balance uses only source-matched accepted lines. A subset is `PARTIAL`; no accepted journals produces `UNAVAILABLE` with null journal totals and trial balance. This is source-bound coverage, never a claim of full-ledger completeness. Opening and closing balances remain null. No publication, ERP posting, statement mapping or certification is added.

The response includes the existing `semantic-analysis/2` source projection and original-cell evidence. This remains the source-only analytical table; the journal trial-balance receipt is a separate explicitly named result, not an approved shared financial measure or new frontend screen.

## Verification

- 36 focused Python tests passed: new reconciliation tests plus existing source review and shared movement projection tests. Accepted-journal examples are explicitly synthetic and establish code behavior only.
- Ruff passed on all changed Python files; focused mypy with `--follow-imports=skip --check-untyped-defs` passed on the new service and finance route.
- Authentic read-only in-process HTTP proof: normal operator 200, no bearer 401, different company 404. No dependency overrides or native writes. This is not a mounted runtime/browser acceptance test.
- The actual unchanged frontend `assertProjection` accepted the authentic returned source projection.
- Evidence: `evidence/nin17-journal-reconciliation.json`, source invocation `60703b36-2243-568f-804b-c622b6365fc4`.

The authentic result has 596 retained source rows, 595 included literal amounts, 37 source movement accounts and exact source total `12502967.2300000000006576` GEL. `Base!S288` remains `MISSING_LITERAL_POSTED_AMOUNT`. The canonical read returned zero matching accepted journals and 595 unmatched coordinates, so journal totals and trial balance remain null. The earlier SEG profile, dimension-policy and precision/sign promotion blockers were not bypassed or repaired by this consumer.

## Integration and remaining work

Only finance service, finance route and tests changed. No NIN-59 product, NIN-62 ontology import, CI or canonical worktree edits. The integration owner can review the frozen branch and independently exercise the endpoint after loading an exact integrated package. Native runtime and independent NIN-50 acceptance remain open. A governed source-supported journal publication adapter, reviewed dimension assignments and an explicit compatible amount contract are still prerequisites for authentic SEG accepted journals. This consumer does not complete that publication journey.
