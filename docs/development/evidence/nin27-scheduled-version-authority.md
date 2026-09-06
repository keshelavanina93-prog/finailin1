# Scheduled versions and current-use authority

Implemented under unblocked NIN-27 / NIN-28. Registry editing heads advance at publication, including future-effective publications. Current-use checks now resolve the latest recorded version effective at the current instant instead of requiring the editing head.

Migration 032 adds one RLS-invoker temporal resolver shared by the Python lifecycle/upstream checks and the database lifecycle/consumption triggers. It selects the temporal winner before checking authority state, so a revoked winner cannot expose an older approved version. Editing compare-and-swap, exact dependency pins, immutable receipts, existing isolation and material authority requirements remain in force.

## Acceptance evidence

- Native `test_resource_lifecycle.py` passed after migration 032 (27.01 seconds). The synthetic canonical consumer, schema and semantic contract received future-effective successors through normal proposal/review. The prior consumer remained usable, its retained receipt replayed unchanged, and a fresh receipt passed database insertion guards.
- Early use of the future version failed in the service and a forged direct database receipt was refused. The resolver selected the successor at its effective boundary without changing the machine clock.
- Lifecycle withdrawal, independent review, retained history and cross-company denial checks passed. A newly published, currently effective REVOKED registry version won temporal selection; neither it nor its approved predecessor passed current use. Exact historical access remained available.
- Six focused guarded-calculation/accounting-status regressions passed. Ruff and targeted mypy passed for the changed service files.
- API restarted on 8062. A retained Gas company lifecycle read through the production web proxy on 3062 returned HTTP 200 with its exact identity/version. See `nin27-effective-authority-runtime.json` and `scripts/verify-effective-authority-runtime.py`.

## Boundaries

Scheduled-version behavioral tests use synthetic definitions, not authentic financial facts. The deployed read is a read-only integration smoke check, not evidence of certified company accounting. This repair covers shared lifecycle/current consumption and transitive input checks; it does not prove that every caller independently selects an effective version instead of an editing head. Full NIN-27, NIN-28, intelligence, finance and release acceptance remain open.
