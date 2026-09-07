# Bounded grouped-result validation — NIN-47

Migration 051 preserves grouped-observation receipt checks while validating each retained object by its exact tenant/resource/version identity. The maximum complete input set remains 200 objects. Schema identity, type, full canonical row contents, known-time boundary, duplicate exclusion, total coverage and group partition/contributors are still checked before a terminal receipt can be inserted.

The previous join from a JSON page could choose a resource-table scan and evaluate resource visibility across the tenant. Under the actual retained source request's actor and exact scope, EXPLAIN showed a sequential resource scan with estimated cost 6068.01. The explicit point lookup uses the resource-history index with estimated cost 8.58. These are planner estimates, not measured latency or scale acceptance.

Migration 050 remains unchanged. Migration 051 replaces only the result guard and records schema version 51. Focused native verification passed (two tests, 4.78 seconds), including direct SQL refusal of fabricated counts and modified canonical source-row contents, complete-set enforcement and retained invocation evidence. No API or frontend contract changed.

Plans are retained in [before](evidence/nin47-grouped-guard-plan-before.json) and [after](evidence/nin47-grouped-guard-plan-after.json). The earlier packaged-workflow timeout remains of unproven cause: recovery had already succeeded before this migration was applied. This correction addresses an observed inefficient access plan and does not retroactively claim to explain that timeout.
