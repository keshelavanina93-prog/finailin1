# Observed temporal extent from retained Function inputs

A reviewed Function may declare `temporal_extent` with an exact schema and a date or datetime field. The result describes earliest and latest observed values over a complete bounded ObjectSet. Every tied boundary witness retains its canonical object/version, content hash and original value. Missing and null counts remain explicit. This does not establish an accounting period, source completeness outside the selected query, or financial authority.

The authentic cohort is SourceJournalMovement from SourceEvidence `71f45f39-35fb-56c1-b4b7-61e7edc56368` and source family `1c_journal:45011b3a149ecfd09a21c7d90c6119830fac1f04352a089c5c5fbe28e3691e1d:TR`, filtered to `[2025-11-01, 2025-11-08)`. Read-only assessment found 23 observations across six distinct dates, with two earliest witnesses on November 1 and six latest witnesses on November 7. The schema declares `posting_date` as a required date. The full retained month exceeds the adapter's 200-object bound, so this proof makes no whole-month coverage claim.

`scripts/verify-temporal-extent-runtime.py` prepares the governed ObjectSet and extent Function under `sog-source-dates:temporal-extent:v1`, with a separate source-read Function and a two-node Transformation. Both nodes have limit 23; the reviewed budget allows 46 returned rows across both results and no derived-property evaluations. The second node consumes the first node's retained original objects, not a reused aggregate value. It must preserve the exact receipt reference, query time and object versions.

The helper separates preparation from starting or adopting a browser build. Read-only restart verification preserves the original request, retained invocations and publication. It asserts the complete cohort, exact normalized extrema, all tied witness pins/hashes, original source coordinates and the exact SourceEvidence versions behind the boundary observations.

## Verified authentic execution

[Runtime evidence](evidence/nin47-temporal-extent-runtime.json) records `TEMPORAL_EXTENT_VERIFIED`. Browser-started request `8a12d1ba-59fb-413c-9633-c6dc0a64f306` froze valid and known time at `2026-09-07T14:03:15.269000Z`. Transformation `470667e9-dc43-5f67-866c-8ecd4b1a82ee` / `3f7b9c77-820e-5f9f-b5c2-75ca9927f1ff` executed both steps and retained one publication, `pub_13d7ba3b3967e8a7a5c628f9e6bc05774ef15ef7d557a7000add1e3f0bdb2cf8`.

The extent Function `49249816-935f-5ddf-a792-b971fe19837f` / `54b81090-994c-5182-8b75-9f4f67988028` produced invocation `2e004b56-b347-50a3-bff1-e356468517e2`, receipt `21a47061a962599e45a50bd8e6b35da2aacaa4d06044b1d1d3922e15e6f48c5c`. It consumed the exact upstream object receipt and returned 23 valid values, zero missing/null values, earliest November 1 with two witnesses and latest November 7 with six witnesses. The helper checked every boundary witness against the original object version, source coordinate, content hash and exact SourceEvidence dependency.

After an API and worker restart, `--read-only` preserved the complete retained invocation and build evidence. The [browser evidence](evidence/nin6-temporal-extent-browser.json) and [inspected capture](evidence/nin6-temporal-extent.png) record the live temporal extent, original observation inspection and exact source graph trace. After restart, the browser reopened the exact retained build and downstream result successfully; the browser evidence records this checkpoint at `2026-09-07T14:13:35.753Z`.

Eleven focused tests passed, including normalization parity and forgery checks. Scoped static verification and the production web build passed. These establish the bounded temporal-observation calculation and source-backed inspection path; completed-result restart readback does not establish arbitrary mid-step recovery.

The result authority remains `OBSERVATION_EXTENT_ONLY`; current-use and business-effect authorization remain false. No accounting-period completeness or financial authority is implied. Full NIN-47, UI/product and release acceptance remain open.
