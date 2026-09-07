# Exact current dependency lookup

The period-control native journey exposed long dependency-impact reads while holding the shared canonical review lock. The current-consumer query joined resource heads only by tenant and version. Under the runtime role and real row-level policies, PostgreSQL planned a sequential head scan even for one isolated synthetic control.

The query now follows the retained dependency to its exact resource version, then resolves its head by tenant, resource ID and version. This provides the complete primary-key lookup without changing which dependencies are current. The existing hidden-dependent preflight, row policies, transitive traversal, cycle classification, grouping and result bounds remain in force.

Read-only EXPLAIN estimated total cost fell from 4833.64 to 38.20 for the retained synthetic control. The changed plan uses dependency_reverse, resource_versions_pkey and resource_heads_pkey. These are planner costs, not measured response times or scale evidence. Two existing native checks passed in 9.61 seconds: transitive current consumers/obsolete edges, and hidden-consumer refusal. Their elapsed time is a test-run observation, not a before/after latency comparison.

Evidence: `evidence/nin28-dependency-impact-lookup.json`.
