# Compound source selection with overlapping branches

Read-only discovery of the authentic 246-observation SOG November cohort found no canonical account occurring on both debit and credit sides. The proof therefore states two distinct source conditions explicitly: debit account A **or** credit account B. It does not describe these as the same account or financial exposure.

Account A is `3ba3c8cc-51a1-5566-86f1-5457949db896` / version `02be57e2-1148-5596-bbcb-9b95cca9dd7a`; account B is `1d3bb778-9f59-5f21-ae02-34961db3a633` / version `f776f6f3-b623-516c-a1ea-896fbe0517a3`. Exact source dependency traces established these LocalAccount pins. Separate existing equality queries returned 124 debit matches and 119 credit matches, with 93 overlapping observations and 150 distinct observations in their union.

`scripts/verify-compound-filters-runtime.py` prepares a reviewed saved selection under `sog-source-accounts:compound-selection:v1`, labelled “Either selected source account condition.” Its legacy filters retain evidence `71f45f39-35fb-56c1-b4b7-61e7edc56368`, the original TR source family and `[2025-11-01, 2025-12-01)` dates. An `any` filter expression adds the two account predicates. No source identity or source value changes.

Two reviewed Functions use the same exact selection: source materialization followed by posting-date observation counts over that retained receipt. Bounds remain 300 objects, two pages, page size 200 and a Transformation budget of 600 returned rows, zero derived evaluations and 2,000,000 result bytes. The selected 150 objects fit one page; this proof tests overlapping Boolean selection, not a new multi-page scale claim.

The helper compares the exact output objects to the union of independently executed legacy equality queries at the same frozen times, proves overlap deduplication, preserves the filter expression through retained Function input, checks every count contributor and traces representative source and account references. `--prepare`, `--start`, browser `--request-id` adoption and `--read-only` restart comparison are separate modes.

## Verified authentic execution

[Runtime evidence](evidence/nin6-compound-filter-runtime.json) records the authentic browser-started request `e9b594f8-eea7-4dc5-a927-782cf3364434`, with valid and known time `2026-09-07T15:52:50.425000Z`. The reviewed ObjectSet is `6d241e6c-7151-5636-bbe3-e93fbce8616e` / version `4714b68a-bbb5-5c80-88c1-a7691e8e8ecc`. Helper readback verified the 124/119 branch sizes, 93-object overlap and exact 150-object union, original source/account pins and retained observation counts.

The [browser evidence](evidence/nin6-compound-filters-browser.json) records opening the reviewed selection, changing Any to All and back to Any, and receiving 150, 93 and 150 observations respectively. Advancing to rows 51–100 of 150 preserved the query cutoff. The [editor capture](evidence/nin6-compound-filters-editor.png) was visually inspected. After an API and worker restart, helper read-only verification preserved the exact retained outputs. A full browser reload and login restored the last ObjectSet query automatically, including offset 50 (rows 51–100), exact timestamps, expression and Any editor selection. Reopening the same build through Data and Builds restored byte-for-byte identical downstream group, coverage and 150-object text. The browser evidence records `restart_query_equal` and `restart_build_equal` as true. These checks prove completed-result retention and UI restoration, not arbitrary mid-step recovery.

Five focused backend tests passed in 15.01 seconds, covering nested ranges, conjunction with legacy filters, root and hop predicates, interfaces, groups, historical interpretation and invalid unused branches. Sixteen SDK tests passed, including two new nested-expression cases. Scoped typing, lint and the production web build passed. These checks establish the bounded query and retained observation path, not broad release acceptance.

Counts remain source observations only. No financial aggregate, account classification, accounting authority or full product/release acceptance is claimed.
