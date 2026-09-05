# G8 local runtime

After provisioning the existing local PostgreSQL/configuration, installing dependencies with `scripts/bootstrap-local.ps1`, and building with `pnpm build`, use PowerShell 7 from `D:\FinAI\finailinear1`:

```powershell
./scripts/g8-runtime.ps1 start
./scripts/g8-runtime.ps1 status
./scripts/g8-runtime.ps1 stop
```

Start launches configured MinIO, API and built web server in dependency order in hidden processes, checks MinIO liveness, API `/ready` and the web HTTP response, and retains process ownership records and individual output/error logs under `.finai/supervisor` on D:. The default application addresses are `http://127.0.0.1:8061` and `http://127.0.0.1:3061`. Use `-ApiPort 8062 -WebPort 3062` when independently started services already occupy the defaults. Status and stop use the stored ports. Start is idempotent for healthy managed services on matching ports. Failed startup rolls back only processes created by that invocation, retaining logs. Use `-Service api`, `-Service web`, or `-Service minio` for an individual lifecycle operation; default `all` stops web/API before storage.

The command loads the existing `.finai/local.json` without printing configuration values and reapplies the D: storage guard. PostgreSQL retains its existing lifecycle and authority. It does not provision or migrate financial state. Existing language executables may be installed outside D:; checkout, environment, runtime state, caches, temporary files, generated artifacts, and built MinIO executables remain under the canonical D: checkout.

Stop verifies process ID, creation time, executable, and command line before stopping managed processes and verified descendants. It never stops processes by port or executable name. Existing independent services are never adopted or stopped. Concurrent commands are serialized by an exclusive file lock. If ownership changed, the command refuses to stop that process. Service logs are local operational files: do not publish them without checking for application-generated sensitive content.

This is a bounded local supervision foundation. HTTP liveness does not establish database/evidence-store readiness, accounting correctness, production suitability, or release acceptance. There is no automatic crash restart yet. NIN-31 still requires persistent desired/reported release resources, immutable artifact/SBOM provenance, health/policy-gated promotion, runtime-agent history, recall and rollback. NIN-35 still governs canonical PostgreSQL state, immutable evidence storage and durable execution; this launcher creates no alternative authority.

## Local S3 evidence storage

```powershell
./scripts/install-local-minio.ps1
./scripts/provision-local-minio.ps1
./scripts/load-local.ps1
& "$env:VIRTUAL_ENV\Scripts\python.exe" ./scripts/check-local-minio.py
```

The installer builds official MinIO and client source at pinned commits into `.finai/tools/minio`, recording source commits and binary SHA-256 in `provenance.json`. Go module/build caches, downloaded toolchains, and temporary files use D:. Build concurrency is limited to four workers. The supervisor binds MinIO to loopback port 9061, reserves console port 9062 with the browser disabled, and stores data under `.finai/data/minio`.

Provisioning preserves existing objects, enables bucket versioning and object-lock capability, and creates a scoped API service account. Root credentials live separately in ignored `.finai/minio-admin.json`; API credentials live in ignored `.finai/local.json`. Both credential files have access restricted to the current Windows user and SYSTEM. Root credentials are passed only to the MinIO child environment, never API launch arguments or process-state records. The service account permits read/write objects, read object versions and bucket metadata/listing for `g8-evidence`; it has no deletion or bucket-configuration permissions.

The application supplies conditional `IfNoneMatch=*` writes; retained versions remain addressable. Object-lock capability is enabled, but no default retention duration or legal hold is silently selected. IAM does not itself force every PutObject caller to include a conditional header: this is an adapter invariant, while versioning protects prior versions and scoped credentials deny deletion. The live check retains a tiny source-independent fixture, verifies exact version/hash reads, checks conditional overwrite rejection and delete denial, and can be rerun after a storage restart to prove persistence.

On 2026-09-05 the [official MinIO repository](https://github.com/minio/minio) stated that it is archived and no longer maintained, with community distribution source-only. This local build pins server `7aac2a2c5b7c882e68c1ce017d8256be2feea27f` and [official client](https://github.com/minio/mc) `77f82e18b5401a65958f1619df6ebb994634bd88`, avoiding obsolete downloaded server binaries. It supplies real local S3 integration, not a supported production deployment. Production storage vendor/maintenance and retention policy remain explicit release decisions.

## Focused verification

`./scripts/test-runtime.ps1` uses ports 18061/13061 and requires no existing managed API/web runtime; configured storage must already be ready. On 2026-09-05 the initial lifecycle verification passed real API/web HTTP startup, idempotent startup with unchanged process IDs, refusal to stop a deliberately mismatched process identity, termination of owned processes/descendants, and preservation of the independently running 8061/3061 listeners. Test processes were stopped after verification. The script now preserves separately supervised MinIO and selects API/web individually.

The live `check-local-minio.py` verification passed before and after a managed MinIO restart on 2026-09-05: same VersionId and SHA-256 read, conditional overwrite HTTP 412, and deletion with API credentials HTTP 403. This is local source-independent fixture evidence, not authentic enterprise source acceptance or production durability certification.
