# Adaptive workspace and source movement integration candidate

This candidate combines the reviewed NIN-59 worksheet and inspector changes with
the NIN-17 source movement Function on the CI-green NIN-60 bootstrap base
`5a7d9472f5c5cdaba1f86e1768a5c5b78fc355d7`. It consumes the same exact-version
semantic analysis contracts for posted groups, canonical objects and movement
attributes. No new identity registry, journal authority or chart computation is
introduced.

The worksheet now retains a keyboard entry when filtering removes the remembered
row, a column is hidden, or virtualization excludes the previous focus. Empty
results remain keyboard reachable. This presentation fallback does not select
evidence or change stored amounts. Independent read-only review found the reported
keyboard blocker resolved.

## Candidate checks

- Frozen dependency installation, repository frontend lint/typecheck/test/build:
  passed; 39 web, 16 ontology SDK and one contract test.
- Repository API Ruff and strict mypy: passed, 168 source files.
- New movement kernel and semantic adapter: 15 focused tests passed.
- Actual backend initial, contributor and filtered/grouped responses passed the
  combined frontend guard; three invalid contract variants were refused.
- Full API coverage and candidate GitHub CI are required before canonical
  promotion. The prior canonical gate passed at 90.40%; that result does not
  establish coverage for the added finance code.

## Runtime evidence boundary

The isolated frontend builder's development-server screenshots are archived in
`evidence/nin59-viewport-candidate.json`. They are not browser evidence for this
combined package. Mounted runtime verification must record the actual source
hashes (including preserved local changes), API manifest, production build ID,
reviewed Function versions and invocation receipts.

The new Function exposes 595 retained source pairs and 37 account movement rows.
It preserves the missing `Base!S288` amount and source precision. Accepted journals,
journal-derived trial balance, opening/closing balances, statements and financial
certification remain unavailable. The original historical invocations must remain
readable after the new Function is published.

NIN-50 receives the frozen integrated manifest after canonical CI passes. NIN-25,
NIN-59, NIN-60 and the complete product/release gates remain open until their own
acceptance evidence exists.
