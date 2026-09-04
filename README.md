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

The first implemented vertical slice is the generic Enterprise Hydration / Source
Authority compiler. It accepts a versioned source authority contract with exact
tenant, legal-entity, period, and currency scope, then emits a deterministic,
content-addressed construction receipt. Each requested field is classified as:

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
.\scripts\verify-local.ps1
```

Run the services directly:

```powershell
.\.venv\Scripts\python.exe -m uvicorn finai_api.main:app --app-dir services\api\src --reload
pnpm --filter @finai/web dev
```

Or run the container topology after bootstrap has created the D:-local data root:

```powershell
docker compose up --build
```

- Operator environment: `http://127.0.0.1:3000`
- API documentation: `http://127.0.0.1:8000/docs`
- API health: `http://127.0.0.1:8000/health`

## Acceptance boundary

This foundation proves local structure, exact-scope authority classification,
deterministic receipts, shared frontend contracts, an operator shell, automated
tests, and production builds. It does not yet prove source parsing, immutable object
storage, database persistence, canonical promotion, reconciliation, approval,
external-system delivery, authentic-source acceptance, scale, or production release.
