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
