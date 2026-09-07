# Reviewed local API expectations and observed state

NIN-31 begins with a real connection between reviewed runtime intent and the running
API component. `DeploymentTarget`, `RuntimeAgent` and `DesiredState` use the existing
canonical identities, version pins and independent-review lifecycle. The industrial
`Product` resource retains its existing meaning.

The target is explicitly `LOCAL_DEVELOPMENT`, component `api`. Its observer is bound
to an existing administrator actor. Desired state pins expected package/code hashes,
required schema version and a bounded freshness interval. It grants no deployment,
promotion, rollback or business action.

The server collects safe package/startup-drift and readiness evidence for itself.
Callers cannot supply fabricated component health, arbitrary probe URLs, environment
variables or process command lines. Reported observations use the existing immutable
content-addressed evidence store, with a scoped request-to-receipt mapping. Canonical
control versions are pinned in the receipt. Reopening and replay preserve the original
observation; freshness is assessed separately at read time.

The first operator surface is read-only runtime history under Workflows & Actions.
Its target list represents retained observations, not a complete configured-target
catalog. It preserves existing administrator access requirements and does not create
new roles or bypass the evidence store's read-permission policy.

## Acceptance boundary

This is reported-state evidence for one running component. It is not an accepted
canonical Release or full ReportedState lifecycle, immutable distributable artifact,
SBOM, signed attestation, multi-component health gate, continuous controller,
candidate/canary/stable rollout, maintenance-window enforcement or rollback system.
The current integrated checkout is explicitly local development with unattested
release provenance. A Git SHA or listener is insufficient to prove a pristine release.

## Focused verification, 2026-09-07

- Three domain checks and two native persistence checks passed, covering exact
  controls, observer/scope binding, replay without recollection, history pagination,
  stale assessment and forged reconciliation rejection. Ruff and targeted mypy
  passed. Migration 047 is applied; API readiness requires schema 47.
- Canonical schemas were installed through independently reviewed proposal
  `d05198f6-d13e-47e2-bd8a-943f5171c9bc`. The actual local target, observer and
  expected-state resources were reviewed together in
  `89eac2ea-3f42-4892-8f0f-fd8f316e1674`.
- Target `b9a7e7f7-d066-56de-a57c-1eb28b944a5f`, observer
  `31afbbf7-75ea-5ab7-a2fd-10e042d936c2`, and desired state
  `fcd3f90c-ef7b-579a-9fcf-3da53e795125` are canonical resources, not module-local
  aliases. The expected-state version is `e3553572-885b-5ca2-a48f-b8aaf568b408`.
- Actual server-collected request `d4b4f4a6-443d-4868-931f-a6a86d267828` matched
  the expected loaded code/dependency digests, disk identity and contiguous schema
  47. Database, schema and evidence-store readiness were ready. Repeated capture
  returned the same immutable observation.
- After stopping/restarting only the managed API, the old receipt remained identical.
  New request `99979670-7e64-4cd9-8b7a-d7544e3f743d` again matched expectations.
  Its server instance changed from `20f8cd36-85f8-441f-a177-bce0090035b1` to
  `67a39e32-2dff-4421-b6d9-fb29c8a9123e`. These are ephemeral observed process
  instances under the same canonical RuntimeAgent, not new business identities.
- Evidence: `evidence/nin31-runtime-observation.preparation.json`,
  `evidence/nin31-runtime-observation.json`, `evidence/nin31-runtime-after-restart.json`.
  `scripts/verify-runtime-observation.py --prepare` reviews intent; default mode
  collects through the administrator API on 8062 and checks readback through the
  web proxy on 3062; `--read-only` reopens history without recollecting. The frontend
  proxy exposes GET only; capture is not a browser control.
- Existing source-account and worksheet Function/build pins were refreshed through
  normal review for the integrated package. Original source proof preparation is
  preserved; refreshed worksheet references are separately recorded in
  `evidence/nin31-refreshed-worksheet.preparation.json`.
- Frontend lint, TypeScript and production build passed. Authenticated browser
  verification opened Workflows & Actions → Runtime state & health, loaded both
  actual observations, and compared code/dependencies/schema/readiness. The older
  receipt then correctly showed **Stale at readback**, age 360 seconds against
  its reviewed 300-second limit, while preserving **Recorded outcome: match**.
  Optional provenance exposed the exact original server instance/start and resource
  pins. Selected versus unselected history rows were visually checked after a
  contrast correction. Captures under `.finai/browser-verification/screenshots/`:
  `g8-runtime-state-history.png`, `g8-runtime-observation-comparison.png`, and
  final `g8-runtime-stale-history.png`. This is a retained observation view; there
  is no claim of continuously refreshed health.

The native collector fixtures prove persistence and guard behavior. The two live
receipts above establish actual local API observation and restart history. Neither
proves PostgreSQL disaster recovery, worker restart, full-system health or release
promotion. The immutable recorded outcome and current age assessment are separate.
