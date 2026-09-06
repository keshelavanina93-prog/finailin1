# Current-effective accounting readiness

Source review now resolves scope, chart and reviewed accounting selection at the current effective time, matching its company and candidate-resource reads. A future-only chart cannot establish readiness, and a scheduled selection cannot replace today's displayed selection. Revoked temporal winners remain visible to validation and cannot expose approved predecessors.

Publication remains a separate guarded operation. Scope creation checks publication heads and refuses an existing or scheduled identity. Selection proposals refuse when either scope or binding has a newer/scheduled publication than the effective read; a form showing an older current selection cannot silently supersede that schedule. Normal current selection proposals retain their expected-version check.

Focused verification: `test_source_accounting_readiness_time.py` passed all eight checks (12.74 seconds), including native PostgreSQL/private-store source evidence, reviewed synthetic company/Alias, a future-only chart, a current source scope and STRUCTURAL_REFERENCE selection followed by a scheduled successor. No ledger, currency interpretation or accounting activation was created. Eighteen existing source-accounting-context checks also passed. Ruff and targeted mypy passed.

The restarted API and production web proxy reopened the authentic retained SEG source successfully. The accepted company/Alias versions stayed unchanged and the accepted source chart remained missing. Evidence: `nin26-effective-readiness-runtime.json`; reproduction: `scripts/verify-effective-source-company.py --output docs/development/evidence/nin26-effective-readiness-runtime.json`.

This is source-readiness correctness, not financial source activation, NIN-26 completion or full product/release acceptance.
