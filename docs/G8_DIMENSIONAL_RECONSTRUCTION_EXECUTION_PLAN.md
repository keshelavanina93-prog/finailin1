# G8 by NYXCore - Dimensional Reconstruction Execution Plan

Status: `ACTIVE CONVERGENCE PLAN`

This plan turns the two governing architecture documents into executable
software reconstruction work:

- `docs/G8_FULL_DIMENSIONAL_ARCHITECTURE.md`
- `docs/G8_FULL_DIMENSIONAL_FRONTEND_UI_UX_ARCHITECTURE.md`

The product must converge into one coherent source-to-action-to-export system.
The current distributed worktree state is useful as implementation evidence,
but it is not the final product structure. Branch-local product dimensions must
be integrated into the canonical application with explicit contracts, tests and
browser/runtime proof.

## 1. Current structural problem

```text
D:\FinAI
|
+-- finailinear1                         canonical convergence repo
+-- g8-finance-ontology-live              finance ontology dimension
+-- g8-petroleum-command                  petroleum/operations dimension
+-- g8-retained-reporting                 reporting/export dimension
+-- g8-product-convergence                cross-product workspace dimension
+-- g8-investigation-resolution-product   investigation/resolution dimension
+-- g8-semantic-workspace                 semantic workspace dimension
+-- g8-source-adoption                    recurring source authority dimension
+-- g8-execution-recovery                 workflow/runtime recovery dimension
+-- many additional implementation lanes
```

This is not wrong as a development method, but it is wrong as the final product
state. The final product cannot require a financial analyst to mentally assemble
features from many Git worktrees. The final product must present one G8 shell,
one governed context model, one evidence model, one authority model and one
source-to-action-to-export journey.

## 2. Target software structure

```text
G8 unified product
|
+-- apps/web
|   +-- one dimensional operator shell
|   +-- role-specific workspaces
|   +-- typed contract clients
|   +-- shared authority/evidence/time primitives
|   +-- browser-tested source-to-action-to-export journeys
|
+-- services/api
|   +-- source intake and evidence retention
|   +-- transformation and semantic analysis
|   +-- ontology and canonical resource graph
|   +-- finance and ledger contracts
|   +-- operations and physical movement graph
|   +-- reporting/export/certification
|   +-- decisions/actions/readback/outcomes
|   +-- runtime/release evidence gates
|
+-- packages/contracts
|   +-- TypeScript contracts
|   +-- JSON schemas
|   +-- route/request/response envelopes
|   +-- authority and evidence state enums
|
+-- docs
|   +-- architecture
|   +-- implementation packets
|   +-- test evidence
|   +-- convergence handoffs
```

## 3. Reconstruction work packages

```text
R0 - Dimensional frontend contract baseline
|
+-- Add machine-readable frontend dimensional axes.
+-- Add surface-to-backend wiring registry.
+-- Add tests proving partial versus fully wired status.
+-- Status: started in this checkout.

R1 - Canonical shell context propagation
|
+-- Implement shared FrontendContext from the dimensional contract.
+-- Bind company, period, currency, evidence, time and role into one context.
+-- Replace ad hoc per-screen scope handling where possible.
+-- Acceptance: screen state tests plus mounted browser proof.

R2 - Massive evidence catalog and asset registry
|
+-- Unify 1C, ORPAK/POS, gas-network and register intake display.
+-- Show source hash, company, valid_at, known_at, source type and status.
+-- Add slide-over inspector for bitemporal scope and downstream unlocks.
+-- Acceptance: source evidence browser journey and hash/refusal tests.

R3 - Accounting dimension workbench
|
+-- Expose account/subkonto/document/counterparty/contract matrix.
+-- Wire source accounting setup, account bindings and dimension policy.
+-- Show ERP source authority versus G8 canonical binding.
+-- Acceptance: missing subkonto/company/period refuses without fallback.

R4 - Physical operations and petroleum bridge
|
+-- Integrate petroleum/operations worktree capabilities into unified shell.
+-- Show tank/station/warehouse/movement graph.
+-- Connect physical conservation to valuation, COGS, revenue and margin.
+-- Acceptance: trace-this-liter browser journey and variance refusal tests.

R5 - Finance/report/export convergence
|
+-- Integrate trial balance, journal, report package and retained reporting.
+-- Add certification and export eligibility states.
+-- Acceptance: uncertified reports cannot export; certified package replays.

R6 - Investigation and NYX reasoning boundary
|
+-- Make NYX inherit selected object/scope/time/evidence context.
+-- Label answers as evidence-backed, hypothesis, recommendation or refusal.
+-- Route proposed changes through review, not direct mutation.
+-- Acceptance: AI cannot silently change canonical facts or actions.

R7 - Decisions, actions, readback and outcomes
|
+-- Add action eligibility and maker/checker workflow.
+-- Add external adapter boundary and readback receipt.
+-- Add outcome measurement timeline.
+-- Acceptance: no action without approval; readback shown before outcome.

R8 - Runtime and release gate cockpit
|
+-- Display code/local/authentic-source/generalization/production/scale/release gates separately.
+-- Tie browser, restart, backup/restore and scale evidence to gate state.
+-- Acceptance: local proof cannot render as release accepted.
```

## 4. Agent task structure

```text
Agent A - backend/proxy wiring auditor
|
+-- output: actual route/proxy coverage and gaps
+-- edits: none

Agent B - frontend surface auditor
|
+-- output: existing UI anchors and missing dimensional surfaces
+-- edits: none

Agent C - distributed worktree convergence auditor
|
+-- output: worktree-to-product-dimension map and integration priority
+-- edits: none

Main implementation lane
|
+-- owns canonical repo edits
+-- starts with R0
+-- integrates agent findings into R1/R2/R3 next
+-- runs focused tests after each executable slice
```

## 5. First executable slice

R0 introduces:

```text
apps/web/app/dimensional-frontend-contract.ts
apps/web/tests/dimensional-frontend-contract.test.mjs
```

The contract defines:

```text
14 governing frontend axes
14 wiring evidence gates
surface-to-backend route mappings
partial versus target-only status
no FULLY_WIRED claim without browser/restart/authority proof
```

This is intentionally not a visual feature yet. It is the software foundation
that prevents future visual work from becoming disconnected UI.

## 6. Completion rule

The reconstruction is complete only when:

```text
one canonical branch contains the required product dimensions
all user-facing surfaces inherit exact dimensional context
all consequential surfaces have backend contracts and proxy allowlists
all financial values expose evidence and authority state
all operational values expose physical and financial bridge state
all AI statements are scoped, cited and non-authoritative by default
all actions require approval and readback
browser journeys prove source-to-action-to-export
restart/readback proves persistence
evidence gates remain separate through release acceptance
```

