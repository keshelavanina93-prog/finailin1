# FinAI / NYX Core

FinAI / NYX Core is an evidence-native Financial and Industrial Decision Intelligence Operating System.

This repository is the implementation repository for the Linear program **FinAI / NYX Core — Platform Reconstruction & Authority**.

## Binding local-development rule

Local Windows development is **D:-only**.

Canonical workspace:

```text
D:\FinAI\finailinear1
```

Do not clone, build, cache, create worktrees, databases, virtual environments, Node package stores, generated artifacts, temporary execution data, or test fixtures for this project on `C:`.

The local bootstrap script enforces this rule.

## Product architecture

The platform is built as one shared substrate:

```text
Evidence
→ Source Authority Contract
→ discovery / parsing / transformation
→ ontology / domain-pack hydration
→ deterministic validation and reconciliation
→ governed canonical enterprise state
→ finance / planning / operations / NYX
→ governed Actions
→ external confirmation / readback
→ outcome / evaluation
```

The initial implementation program includes:

- shared resource/version/security/lineage kernel;
- universal data transformation and enterprise hydration compiler;
- ontology, Functions, Metrics, Actions and workflow runtime;
- deterministic financial authority, modules and subledgers;
- consolidation, FX, intercompany and eliminations;
- semantic metric registry and deterministic MR compiler;
- modern operator dashboards, dense drill-down workspaces and graph canvases;
- 1C metadata-aware ingestion and governed SAP interoperability;
- NYX agents/evaluations;
- production/runtime acceptance.

## Local bootstrap

From PowerShell on `D:`:

```powershell
D:
mkdir D:\FinAI -Force
cd D:\FinAI
git clone https://github.com/Nina932/finailinear1.git
cd .\finailinear1
.\scripts\bootstrap-local.ps1
```

The repository must remain the source of truth. Linear defines scope and acceptance; GitHub stores implementation and review evidence.

## Repository foundation

```text
apps/web              unified Next.js operator environment
services/api          FastAPI and deterministic domain/application logic
packages/contracts    shared JSON Schema and TypeScript contracts
docs/architecture     architectural decisions and authority invariants
scripts               D:-only bootstrap, guard, and verification
```

The initial compiler preview classifies client-declared fields, without proving
source retention or executing rules. Its fields are never authoritative.
The persisted ingestion path now accepts UTF-8 CSV, with server-owned source
contracts and exact tenant/entity/period/currency authorization. It retains the
submitted UTF-8 bytes, executes bounded decimal TB derivations, and writes a
deterministic construction receipt to PostgreSQL. Unknown schemas produce only
source-record candidates. Epistemic states remain distinct from business authority:

- `OBSERVED` — directly supported by retained evidence;
- `DERIVED` — deterministically produced by a versioned rule over observed inputs;
- `INFERRED` — reviewable and explicitly non-authoritative;
- `UNAVAILABLE` — not supported by the current evidence.

Compiler output is always `CANDIDATE_ONLY`. Canonical promotion will be a separate,
governed operation requiring validation, reconciliation, policy, approval, and
persistence receipts.

## Develop and verify

From the canonical Windows checkout:

```powershell
.\scripts\bootstrap-local.ps1
.\scripts\start-local-postgres.ps1 -PostgresBin D:\PG18\pgsql\bin
.\scripts\verify-local.ps1
```

Run the services directly:

```powershell
.\scripts\load-local.ps1
.\.venv\Scripts\python.exe -m uvicorn finai_api.main:app --app-dir services\api\src --host 127.0.0.1 --port 8000
pnpm --filter @finai/web dev
```

The local PostgreSQL cluster binds to `127.0.0.1:55439`, uses SCRAM credentials,
and stores all data beneath `.finai/data/postgres-native`. Configuration and the
generated exact-scope access token are in ignored `.finai/local.json`. Use its
token and scope in the operator form. Tokens are kept in browser memory only.
This is bootstrap authentication; enterprise identity and approval remain open.

The container topology requires explicit database migration and a restricted
runtime DSN plus access-token configuration. On Windows, do not build/run Docker
until its engine image, build-cache and volume storage have been verified on D:;
the bind mount alone does not prove the engine's storage location.

```powershell
docker compose up --build
```

- Operator environment: `http://127.0.0.1:3000`
- API documentation: `http://127.0.0.1:8000/docs`
- API health: `http://127.0.0.1:8000/health`

## Acceptance boundary

This implementation adds CSV parsing, deterministic TB balance checks, immutable
PostgreSQL evidence/receipt retention, restricted-role tenant isolation, exact-scope
read denial, idempotent replay, and a connected ingestion workspace. The compiler
and database produce candidates only. Row observations do not prove source authenticity.

NIN-24 remains unaccepted: semantic memory, configurable ontology registries,
durable workflow DAG execution, reviewed promotion and canonical object workspaces
remain open. Enterprise identity, authentic 1C/SAP integrations, financial reporting,
scale and production release acceptance also remain open. See
`docs/architecture/0002-retained-hydration.md` for the binding issue mapping.
