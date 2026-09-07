# Managed runtime observation collector

The packaged local runtime can now supervise an observation collector alongside
the API, web application and storage. It uses the existing reviewed DesiredState
and RuntimeAgent controls and existing server-owned capture endpoint. It does not
rewrite expectations, approve deployments or create a second reported-state store.

Start it with explicit reviewed references:

```powershell
.\scripts\g8-runtime.ps1 -Action start -Service observer -ApiPort 8062 -WebPort 3062 `
  -DesiredResource fcd3f90c-ef7b-579a-9fcf-3da53e795125 `
  -DesiredVersion e3553572-885b-5ca2-a48f-b8aaf568b408 `
  -ObserverActor local-steward -ObserverInterval 60
```

The same parameters can explicitly enable collection with `-Service all`. Without
these references, starting all services does not create a collector. Stop or inspect
it with `-Service observer`. The supervisor verifies process ownership before
stopping it and reports **PROCESS_LIVENESS_ONLY**, not successful collection or
release health. Authoritative outcomes remain in Workflows & Actions → Runtime
state & health.

The collector accepts a loopback API port and an actor identifier; credentials
come only from the existing environment grants. Exactly one eligible actor grant
must match. Credentials are absent from command arguments, checkpoint and logs.
Logs contain constant outcome codes. Redirects and environment proxy routing are
disabled. Requests cannot supply health measurements or a target URL.

Before sending, the collector writes and flushes a pending request UUID and exact
DesiredState pin to `.finai/runtime-observer/checkpoint.json`. A process lock prevents
concurrent collectors. After POST, it verifies the existing content-addressed
calculation receipt and exact scope/pin, then reads the receipt back independently
before acknowledging locally. A failed call or interrupted checkpoint retries the
same request. Changing configuration while a request is pending is refused. The
checkpoint is delivery progress, not business or runtime authority. Files and
their ancestor paths are checked for D: residency and reparse redirection.

Actual proof on 2026-09-07 stopped the managed API, started the collector, retained
pending request `7d3ff4af-28b2-4b08-9a5c-69e0df4d1f9e`, stopped the collector, restarted
the API, then restarted the collector with the same configuration. That same request
was acknowledged and read back. Its recorded result is **DRIFT**: the package
dependency identity differs from the reviewed expectation. The implementation
code identity still matches. The expectation remained unchanged.
Evidence: `evidence/nin31-managed-observer-recovery.json`; read-only verification:
`scripts/verify-observer-recovery.py`.

Focused transport tests additionally simulate a lost acknowledgement, interruption
after server receipt but before checkpoint replacement, changed pending configuration
and mismatched readback. They do not prove power-loss durability, disaster recovery,
release attestation, automatic deployment or full NIN-31 acceptance. The collector
is configured at a 60-second interval in the current local runtime; the existing
product observation view loads retained history on request.

Authenticated browser proof opened the recovered observation in Workflows &
Actions. It showed dependency identity **Differs**, implementation code **Matches**,
schema 47, files matching the loaded package, and ready database/evidence storage.
The viewed capture is `.finai/browser-verification/screenshots/g8-managed-observer-drift.png`.
