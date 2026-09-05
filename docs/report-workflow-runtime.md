# Local durable report-source processing

This is the NIN-29/NIN-24 source-processing implementation, not financial certification.
The G8 definition and immutable PostgreSQL receipts are the user-facing authority;
Temporal executes the definition and preserves waits/retries across worker restarts.

## Start and recover

1. Install API dependencies from `services/api/pyproject.toml` in the D: environment.
2. Run `scripts/install-local-temporal.ps1` (pinned download and SHA-256 verification).
3. Load local configuration and apply migrations with `scripts/migrate.py`.
4. Run `scripts/g8-workflows.ps1 start`. Temporal listens only on loopback 7233;
   its persistent development database is `.finai/data/temporal.db` on D:.
5. Start API/web through the existing `g8-runtime.ps1` supervisor.

Use `g8-workflows.ps1 stop -Service worker` / `start -Service worker` to replace a worker.
Process mutation checks executable, command line and creation time; unrelated processes
and occupied unmanaged ports are preserved. This launcher is for the local development
runtime. A production Temporal deployment, TLS/identity, backup/restore and HA remain
deployment acceptance work.

## Operator path

Retain source files → save a report-source assessment → start durable processing.
The process executes hierarchy → coverage → human review. Reopen it after restart,
inspect the immutable attempts and output references, pause/resume, or retry after a
failure. Retry does not grant financial authority. A different authorized reviewer can
acknowledge the assessment. January 2026 facts must not be inferred from filenames or
substituted historical sources.

Temporal payloads contain scoped identifiers and small output references; source files,
financial proofs and credentials are not copied into orchestration payloads. Each activity
resolves current server-owned permissions. Every result pins source receipts and function
versions. v1 histories remain replayable after deployment of the v2 hierarchy step.

## Focused verification

`FINAI_TEMPORAL_TEST_SERVER=127.0.0.1:7233` enables the opt-in runtime invariant in
`test_report_workflow_runtime.py`. It injects pre-effect failure, exhausts automatic retries,
resumes through an explicit retry, suppresses duplicate signals and cancels the process.
The authentic-source verification additionally covers all twelve SGP TB sources and
actual server+worker restart while paused. No external economic writes are implemented.
