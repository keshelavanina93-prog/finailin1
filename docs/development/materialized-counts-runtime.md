# Observation counts from retained materialized objects

This proof reuses the authentic SOG SourceJournalMovement cohort established by [bounded materialization](object-set-materialization-runtime.md): 246 observations with evidence `71f45f39-35fb-56c1-b4b7-61e7edc56368`, the original TR source family, and posting dates in `[2025-11-01, 2025-12-01)`. Source identities and values remain unchanged.

`scripts/verify-materialized-counts-runtime.py` prepares reviewed definitions under `sog-source-dates:materialized-counts:v1`. Two Functions bind the same exact saved ObjectSet. Each declares materialization limits of 300 objects and two pages; invocation page size is 200. The first retains original objects, and the second groups that exact receipt by the schema-declared `posting_date`. The two-node Transformation budgets 600 returned rows, zero derived evaluations and 2,000,000 result bytes.

The helper checks exact upstream/downstream manifest equality, pages of 200 and 46, all original object/version/hash pins, and one-to-one contributor conservation across every group. Counts for November 1 and November 30 must be 2 and 140 respectively; all other date groups are checked against the retained stored values. One representative observation from each boundary group is traced to its exact original SourceEvidence version. No grouping key is inferred from accounting meaning.

Preparation, start, browser request adoption and read-only restart verification are separate modes. The retained output contract is `grouped-observation-counts/1`, authority `OBSERVATION_COUNTS_ONLY`, with coverage `COMPLETE_BOUNDED_MATERIALIZATION` for the selected query. SQL/native checks separately prove enforcement and absence of downstream recollection; HTTP receipt equality alone does not prove which internal code ran.

## Verified authentic execution

[Runtime evidence](evidence/nin47-materialized-counts-runtime.json) records `MATERIALIZED_COUNTS_VERIFIED` for browser-started request `deb2c218-edef-484e-88ff-f3ae32420974`, with valid and known time `2026-09-07T15:25:39.495000Z`. The saved ObjectSet is `0f6a826d-14a2-5e46-aa32-0faf5160303e` / version `180424ab-cadf-54be-b44e-d7d835b2d4e6`; the Transformation is `db02a2e4-9158-555a-81ac-5f2dc1ee6b28` / version `06f03e2a-2923-5552-ba83-3a53bf6affc9`.

The authentic helper verified 246 source observations partitioned into 25 date groups, exact contributor conservation, counts 2 and 140 at the date boundaries, and identical retained source/consumer manifests. The browser displayed 25 groups whose counts sum to 246 alongside all 246 source observations. Inspecting TR row 4 opened NYX and its exact source graph; closing the trace preserved the expanded group.

After the API and worker restarted, helper read-only verification preserved the exact immutable outputs. A full browser reload and login, followed by Data, the Builds tab and reopening the same request, restored identical downstream group, coverage and 246-source-row text. The [browser evidence](evidence/nin47-materialized-counts-browser.json) records `restart_retained_browser_equal: true`; the [browser capture](evidence/nin47-materialized-counts-browser.png) was visually inspected. This demonstrates completed-result retention and reopening, not arbitrary mid-step crash recovery.

Three focused tests (two unit and one native) passed in 133.19 seconds. The native case used 205 synthetic source objects and a raw-input consumer calculating counts and extent. They covered retained reuse without querying again, replay and four forged SQL results. A separate bounded SQL-only check reused those fixtures and verified the precise guard messages for changed counts, duplicate or omitted contributors, and a missing materialization page. One adapted existing regression passed. Scoped typing, lint and the production web build passed. Synthetic enforcement checks remain distinct from the authentic browser evidence.

No financial sums, period certification, whole-product completion, general scale result or release acceptance are claimed.
