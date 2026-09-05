# Canonical resource kernel and enterprise explorer — NIN-26

The shared ontology persists business identity once and retains successive accepted versions. PostgreSQL provides transactions, row-level isolation, append-only decisions and immutable versions. The application resolves those resources through the ontology service.

## Delivered implementation

- Canonical schema, semantic and typed-link catalog; 91 explicit platform definitions. Catalog installation creates no enterprise or accounting facts.
- Typed resource proposals with dependency version pins, schema compatibility checks, immutable independent review and stale-version rejection.
- Entity policy enforcement plus explicit tenant steward permissions. Platform definitions are readable within the tenant; enterprise facts cannot use that public policy.
- Alias fingerprints, same-type identity redirects, cycle rejection and effective/historical identity resolution. A reviewed inactive redirect splits a previous merge without deleting its history.
- Effective and system timestamps, historical resource selection, reverse dependency inspection and restoration through a new reviewed version.
- Enterprise explorer, graph, resource creation, reference selectors, review queue and version inspector in the mounted application.
- An optional, explicitly hypothetical SOCAR company-first Petroleum/Gas reference proposal. It requires review and does not establish real ownership, licence, regulatory or source evidence.
- Source ingestion can pin an accepted ContextBinding and retain canonical entity, ledger, period and currency resource/version references in its receipt. No binding means the existing source-only construction flow; it does not establish canonical accounting authority.

## Local operation

Run all commands from `D:\FinAI\finailinear1`:

```powershell
. ./scripts/load-local.ps1
.venv\Scripts\python.exe scripts/migrate.py
.venv\Scripts\python.exe scripts/configure-workspace.py
. ./scripts/load-local.ps1
.venv\Scripts\python.exe scripts/install-ontology.py
pnpm build
```

Use separate terminals for `./scripts/run-workspace.ps1 -Service api` and `./scripts/run-workspace.ps1 -Service web`. Open the workspace on port 3061. Stop its web process before rebuilding because Windows locks the running standalone directory.

Use `./scripts/copy-workspace-key.ps1 -Role Steward` to obtain the local proposal identity and `-Role StewardReviewer` for independent review. Operator/reviewer identities retain their entity boundaries. Keys remain in the ignored D-only runtime directory and browser memory.

## Company-first specification update

The latest NIN-26 revision presents SOCAR Georgia Petroleum and SOCAR Georgia Gas as company/legal-entity reference structures. The proposed graph uses those company identities and attaches industry packs to them. BusinessDomain remains a semantic classification. Exact legal registration still needs authentic master data.

Migration 006 retains the previous platform link version and expands industry-pack endpoints to companies and operating structures. Additional reusable catalogue types include Licence, LegalIdentifier, LicensedServiceArea, GasDistributionSystem, PipelineSegment, TariffDecision and TariffComponent. Typed links connect companies, licences and currencies. These are contracts, not implemented gas regulatory calculations or live tariff feeds.

## Current evidence and open work

Frontend production compilation and backend static type analysis pass. The restarted API serves catalog, graph, context and proposal endpoints against native PostgreSQL; the catalog returns 91 definitions. No automated tests were run for this delivery, as requested. This is code and local runtime evidence, not security certification or release acceptance.

NIN-26 remains open. Explicit breaking-schema migrations, richer match-candidate/survivorship workflows, full identity acceptance evidence, authentic source verification and shared identities throughout journal/report/Function/Action/NYX consumers remain unfinished. Graph reads disclose their 1,000-resource bound. The current editor handles single-resource proposals; the API accepts atomic batches of up to 100 resources.

## Dependency-ordered continuation

1. Complete shared identity/schema acceptance and source-to-canonical account binding.
2. Implement the remaining M1 security, resource lifecycle and storage/workflow contracts from their current Linear acceptance criteria.
3. Build deterministic journal production over canonical entity/ledger/book/period/account references, with governed approvals and immutable lineage.
4. Mount financial statements, operational workspaces and retained exports over those same resources.
5. Add durable source connectors and workflow execution, then Functions/Actions/NYX under the same permissions and authority model.

The binding backlog remains the Linear project. This document describes implementation boundaries; it does not replace that acceptance source.
