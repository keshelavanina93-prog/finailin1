# G8 local runtime

After provisioning the existing local PostgreSQL/configuration, installing dependencies with `scripts/bootstrap-local.ps1`, and building with `pnpm build`, use PowerShell 7 from `D:\FinAI\finailinear1`:

```powershell
./scripts/g8-runtime.ps1 start
./scripts/g8-runtime.ps1 status
./scripts/g8-runtime.ps1 stop
```

Start launches the API and built web server in hidden processes, checks API `/health` and the web HTTP response, and retains process ownership records and individual output/error logs under `.finai/supervisor` on D:. The default addresses are `http://127.0.0.1:8061` and `http://127.0.0.1:3061`. Use `-ApiPort 8062 -WebPort 3062` when independently started services already occupy the defaults. Status and stop use the stored ports. Start is idempotent for healthy managed services on matching ports. Failed startup rolls back only processes created by that invocation, retaining logs.

The command loads the existing `.finai/local.json` without printing configuration values and reapplies the D: storage guard. PostgreSQL and evidence storage retain their existing lifecycle and authority. It does not provision or migrate financial state. Executables may be installed outside D:; checkout, environment, runtime state, caches, temporary files, and generated artifacts remain under the canonical D: checkout.

Stop verifies process ID, creation time, executable, and command line before stopping managed processes and verified descendants. It never stops processes by port or executable name. Existing independent services are never adopted or stopped. Concurrent commands are serialized by an exclusive file lock. If ownership changed, the command refuses to stop that process. Service logs are local operational files: do not publish them without checking for application-generated sensitive content.

This is a bounded local supervision foundation. HTTP liveness does not establish database/evidence-store readiness, accounting correctness, production suitability, or release acceptance. There is no automatic crash restart yet. NIN-31 still requires persistent desired/reported release resources, immutable artifact/SBOM provenance, health/policy-gated promotion, runtime-agent history, recall and rollback. NIN-35 still governs canonical PostgreSQL state, immutable evidence storage and durable execution; this launcher creates no alternative authority.

## Focused verification

`./scripts/test-runtime.ps1` uses ports 18061/13061 and requires no existing managed runtime. On 2026-09-05 it passed real API/web HTTP startup, idempotent startup with unchanged process IDs, refusal to stop a deliberately mismatched process identity, termination of owned processes/descendants, and preservation of the independently running 8061/3061 listeners. Test processes were stopped after verification. This exercises process lifecycle safety and liveness only.
