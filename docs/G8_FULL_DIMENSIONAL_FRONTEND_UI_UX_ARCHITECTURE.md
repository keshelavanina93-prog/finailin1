# G8 by NYXCore - Full Dimensional Frontend UI/UX Architecture

Status: `TARGET FRONTEND ARCHITECTURE / IMPLEMENTATION MAPPING REQUIRED`

This document translates the full dimensional G8 architecture into the frontend
and operator experience architecture. It is not a visual mockup. It defines the
UI system, navigation model, workspace model, state model, authority indicators,
role experiences and engineering boundaries required for the G8 application.

The frontend must not behave like a dashboard shell with many disconnected
pages. It must behave like an enterprise operating surface where every visible
number, source row, graph object, decision, action and AI statement carries its
scope, evidence, authority, time and approval state.

## 0. Full dimensional frontend coordinate system

A full-dimensional frontend is not defined by how many screens exist. It is
defined by whether every surface can project the same enterprise object across
all dimensions without losing authority, evidence, time, role, scope or backend
contract.

```text
G8 frontend coordinate
|
+-- D1 Product mode
|   +-- command overview
|   +-- source intake
|   +-- transformation
|   +-- ontology
|   +-- accounting
|   +-- operations
|   +-- planning
|   +-- reporting
|   +-- investigation
|   +-- decision/action
|   +-- governance
|   +-- runtime/release
|
+-- D2 User role
|   +-- executive
|   +-- controller
|   +-- finance analyst
|   +-- operations manager
|   +-- ontology owner
|   +-- reviewer/checker
|   +-- auditor
|   +-- AI governance owner
|   +-- platform operator
|
+-- D3 Business scope
|   +-- tenant
|   +-- enterprise
|   +-- legal entity
|   +-- company
|   +-- facility
|   +-- warehouse
|   +-- tank
|   +-- station
|   +-- counterparty
|   +-- contract
|   +-- product
|   +-- movement
|
+-- D4 Financial scope
|   +-- ledger
|   +-- book
|   +-- chart of accounts
|   +-- account
|   +-- subkonto 1
|   +-- subkonto 2
|   +-- subkonto 3
|   +-- department
|   +-- region
|   +-- budget article
|   +-- period
|   +-- currency
|
+-- D5 Operational scope
|   +-- physical location
|   +-- equipment / asset
|   +-- tank / meter / dispenser
|   +-- route / carrier / truck
|   +-- inventory batch
|   +-- quantity
|   +-- unit of measure
|   +-- density / temperature basis
|   +-- loss / variance
|
+-- D6 Evidence state
|   +-- raw source
|   +-- retained source
|   +-- parsed observation
|   +-- validated observation
|   +-- rejected row
|   +-- derived candidate
|   +-- approved mapping
|   +-- canonical fact
|   +-- certified report value
|   +-- export receipt
|
+-- D7 Authority state
|   +-- source-owned
|   +-- G8-observed
|   +-- G8-derived
|   +-- proposed
|   +-- checker-reviewed
|   +-- approved
|   +-- published
|   +-- certified
|   +-- refused
|   +-- blocked
|   +-- superseded
|
+-- D8 Time state
|   +-- valid_at
|   +-- known_at
|   +-- recorded_at
|   +-- approved_at
|   +-- corrected_at
|   +-- executed_at
|   +-- readback_at
|   +-- replay_as_of
|
+-- D9 Interaction projection
|   +-- table
|   +-- graph
|   +-- timeline
|   +-- map
|   +-- form
|   +-- drawer
|   +-- comparison
|   +-- command/chat
|   +-- report/export
|
+-- D10 Runtime state
|   +-- idle
|   +-- loading
|   +-- queued
|   +-- running
|   +-- waiting for evidence
|   +-- waiting for approval
|   +-- failed
|   +-- timed out
|   +-- completed
|   +-- stale
|
+-- D11 Backend contract state
|   +-- route absent
|   +-- proxy absent
|   +-- proxy allowlisted
|   +-- FastAPI route included
|   +-- service implemented
|   +-- typed contract present
|   +-- negative authority tests present
|   +-- browser proof present
|
+-- D12 Trust zone
|   +-- browser
|   +-- Next.js proxy
|   +-- FastAPI service
|   +-- workflow worker
|   +-- model gateway
|   +-- evidence store
|   +-- database
|   +-- external source
|   +-- external action adapter
|
+-- D13 Decision state
|   +-- inspect
|   +-- explain
|   +-- propose
|   +-- review
|   +-- approve
|   +-- execute
|   +-- read back
|   +-- measure
|   +-- learn
|
+-- D14 Acceptance gate
    +-- code present
    +-- local contract pass
    +-- local integrated pass
    +-- authentic source pass
    +-- generalization pass
    +-- production runtime pass
    +-- scale pass
    +-- release accepted
```

Every visible UI unit can be described as:

```text
UI unit =
  product mode
  x role
  x business scope
  x financial/operational scope
  x evidence state
  x authority state
  x time state
  x projection type
  x runtime state
  x backend contract state
  x trust zone
  x decision state
  x acceptance gate
```

If a surface cannot expose these coordinates, it is not full-dimensional. It is
only a partial screen.

## 1. Frontend product principle

```text
G8 frontend
|
+-- Not a BI dashboard
+-- Not an ERP clone
+-- Not an AI chat wrapper
+-- Not a spreadsheet viewer
+-- Not a petroleum-only control room
+-- Not disconnected React pages
|
+-- A governed enterprise operating shell
    |
    +-- binds user identity
    +-- binds company / period / currency / dataset / version
    +-- shows source and evidence state
    +-- separates ERP truth from G8 canonical truth
    +-- separates physical truth from financial truth
    +-- exposes lineage before trust
    +-- requires review before publication
    +-- requires approval before action
    +-- makes AI reasoning inspectable and non-authoritative
```

The user's first screen after sign-in should not be marketing. It should be the
live operator environment: current scope, unresolved work, authority blockers,
trusted metrics, evidence freshness, and the next valid actions.

## 2. Top-level shell architecture

```text
G8 Operator Shell
|
+-- Auth/session boundary
|   +-- access key / SSO / tenant session
|   +-- actor identity
|   +-- role and permissions
|   +-- authorized companies
|   +-- authorized actions
|
+-- Global governed context bar
|   +-- tenant
|   +-- enterprise
|   +-- company / legal entity
|   +-- fiscal period
|   +-- currency
|   +-- dataset / package
|   +-- ontology version
|   +-- scenario / forecast version
|   +-- known_at / replay_as_of
|   +-- role mode
|
+-- Navigation rail
|   +-- Home / command overview
|   +-- Companies
|   +-- Sources and Data
|   +-- Transformation
|   +-- Ontology
|   +-- Finance
|   +-- Operations
|   +-- Planning
|   +-- Reporting
|   +-- Investigation
|   +-- Decisions and Actions
|   +-- Governance
|   +-- Runtime / Release
|
+-- Work canvas
|   +-- table-first views
|   +-- graph-first views
|   +-- timeline-first views
|   +-- bridge-first views
|   +-- comparison views
|
+-- Persistent intelligence rail
|   +-- Ask NYX
|   +-- reasoning trace
|   +-- evidence cited by answer
|   +-- missing evidence and refusal state
|   +-- recommended next checks
|
+-- Persistent drawers
    +-- Evidence drawer
    +-- Lineage drawer
    +-- Mapping drawer
    +-- Authority drawer
    +-- Approval drawer
    +-- Action drawer
    +-- Outcome drawer
```

Existing implementation anchor: the current app already centers on
`D:\FinAI\finailinear1\apps\web\app\g8-workspace.tsx`, which should remain the
integration shell rather than being replaced by standalone pages.

## 3. Dimensional context model in UI

Every major screen must carry this context model. If any required dimension is
missing, the UI should show unavailable or blocked state, not substitute a
default.

```text
FrontendContext
|
+-- identity
|   +-- tenant_id
|   +-- actor_id
|   +-- role
|   +-- permissions
|
+-- enterprise scope
|   +-- enterprise_id
|   +-- company_id
|   +-- legal_entity_id
|   +-- facility_id
|   +-- station_id
|   +-- warehouse_id
|
+-- financial scope
|   +-- fiscal_period
|   +-- ledger
|   +-- chart_of_accounts
|   +-- account
|   +-- subkonto coordinates
|   +-- currency
|   +-- statement package
|
+-- operational scope
|   +-- product
|   +-- movement
|   +-- tank / asset / route
|   +-- unit of measure
|   +-- measurement basis
|
+-- evidence scope
|   +-- source_id
|   +-- manifest_id
|   +-- retained evidence id
|   +-- source row hash
|   +-- content hash
|   +-- lineage path
|
+-- time scope
|   +-- valid_at
|   +-- known_at
|   +-- recorded_at
|   +-- approved_at
|   +-- replay_as_of
|
+-- authority scope
    +-- observed
    +-- derived
    +-- approved
    +-- certified
    +-- refused
    +-- blocked
```

UI rule: company, period, currency, dataset, evidence and version cannot be
implicit when a screen makes a financial, operational, approval or action claim.

## 4. Information architecture

```text
Home / Command Overview
|
+-- enterprise health
+-- open evidence gaps
+-- active close state
+-- reconciliation blockers
+-- pending decisions
+-- action readbacks
+-- AI/refusal alerts
+-- release/evidence gate status

Companies
|
+-- company directory
+-- legal entity graph
+-- facility/station/warehouse map
+-- company source coverage
+-- accounting setup
+-- company-specific ontology
+-- permissions and responsible owners

Sources and Data
|
+-- source connections
+-- source manifests
+-- retained files/documents
+-- source tables/registers
+-- raw row explorer
+-- evidence retention
+-- source health
+-- source history and corrections

Transformation
|
+-- schema discovery
+-- profiling
+-- mapping candidates
+-- transformation preview
+-- validation rejects
+-- retained transformation runs
+-- replay and comparison
+-- publication review

Ontology
|
+-- business objects
+-- definitions
+-- dimensions
+-- relationships
+-- source-to-object bindings
+-- version history
+-- dependency graph
+-- proposal and review

Finance
|
+-- trial balance
+-- journal lines
+-- ledger balances
+-- subledger exposure
+-- statements
+-- consolidation / FX / intercompany
+-- close workspace
+-- corrections and restatements
+-- certified report package

Operations
|
+-- movement graph
+-- tank/warehouse/station state
+-- inventory conservation
+-- sales volume to stock reduction
+-- physical losses and variance
+-- route / carrier / waybill lineage
+-- physical-to-financial bridge

Planning
|
+-- budgets
+-- forecasts
+-- scenarios
+-- liquidity
+-- margin bridge
+-- sensitivity analysis
+-- actual-versus-plan outcome

Reporting
|
+-- statement packages
+-- management reports
+-- metric definitions
+-- export eligibility
+-- immutable exports
+-- report comparison
+-- certified narrative

Investigation
|
+-- anomaly triage
+-- evidence drilldown
+-- root-cause hypotheses
+-- missing evidence
+-- Ask NYX scoped investigation
+-- workpaper generation

Decisions and Actions
|
+-- recommendation queue
+-- maker/checker approval
+-- action eligibility
+-- action simulation
+-- external action adapter
+-- readback verification
+-- outcome tracking

Governance
|
+-- policy
+-- authority model
+-- role access
+-- audit log
+-- approval receipts
+-- model governance
+-- learning candidate review

Runtime / Release
|
+-- health
+-- workers
+-- queues
+-- errors
+-- evidence gates
+-- deployments
+-- backup/restore
+-- release readiness
```

## 5. Workspace taxonomy

The frontend uses four primary workspace types. Each domain surface should be a
composition of these types, not a custom visual language.

```text
Table-first workspace
|
+-- source rows
+-- trial balance
+-- journal lines
+-- mappings
+-- queues
+-- exposures
+-- rejects
+-- evidence lists

Graph-first workspace
|
+-- ontology
+-- source lineage
+-- movement path
+-- dependency graph
+-- legal entity graph
+-- agent flow graph
+-- impact graph

Timeline-first workspace
|
+-- close progression
+-- source correction history
+-- approval history
+-- execution/readback
+-- outcome measurement
+-- replay-as-of comparison

Bridge-first workspace
|
+-- physical-to-financial reconciliation
+-- price-volume-mix-cost-margin
+-- original versus corrected
+-- source versus canonical
+-- plan versus actual
+-- AI hypothesis versus approved fact
```

## 6. Reusable UI primitives

```text
Core primitives
|
+-- ScopeSelector
+-- ContextBar
+-- AuthorityBadge
+-- EvidenceBadge
+-- FreshnessBadge
+-- ReconciliationStatus
+-- RefusalState
+-- MissingEvidenceCallout
+-- VersionPill
+-- TimeModeSwitch
+-- ReplayAsOfPicker
+-- LineageButton
+-- TraceDrawer
+-- EvidenceDrawer
+-- ReviewDecisionPanel
+-- ApprovalStepper
+-- ActionEligibilityPanel
+-- ReadbackReceiptPanel
+-- OutcomeDeltaCard
+-- ExportEligibilityPanel
+-- AgentTracePanel
+-- AIAnswerCitationList
+-- GateStatusStrip
+-- RuntimeHealthSignal
```

Existing implementation anchors include `g8-ui.tsx`, `company-period-control`,
`receipt-panel`, `canonical-trace`, `operator-trace`, `resource-authority`,
`promotion-readiness`, `work-queue`, `nyx-interaction`, `process-graph`,
`operations-map`, `finance-workspace`, and `data-workspace`.

## 7. Authority visual language

The UI must make authority impossible to miss. Styling can vary, but the state
contract cannot.

```text
Authority states
|
+-- RAW_SOURCE
|   +-- source-owned
|   +-- read-only
|   +-- no G8 truth claim yet
|
+-- RETAINED_EVIDENCE
|   +-- hash retained
|   +-- source coordinate visible
|   +-- immutable evidence available
|
+-- DERIVED_CANDIDATE
|   +-- computed from retained evidence
|   +-- not approved
|   +-- review required
|
+-- APPROVED_CANONICAL
|   +-- approved mapping/policy applied
|   +-- deterministic calculation
|   +-- lineage available
|
+-- CERTIFIED_REPORT_VALUE
|   +-- report package approved
|   +-- export eligible
|   +-- reproducible
|
+-- AI_INFERENCE
|   +-- non-authoritative
|   +-- cited evidence required
|   +-- cannot mutate truth
|
+-- ACTION_APPROVED
|   +-- maker/checker approval complete
|   +-- adapter scoped
|   +-- readback required
|
+-- BLOCKED_OR_REFUSED
    +-- missing exact scope
    +-- missing evidence
    +-- policy refusal
    +-- source unavailable
```

Every high-risk button must show its authority requirement before execution.
Examples: certify report, publish ontology, approve journal, close period,
dispatch action, export package, promote model or replay correction.

## 8. Financial dimension UI

```text
Financial Dimension Workspace
|
+-- Scope header
|   +-- company
|   +-- period
|   +-- ledger
|   +-- currency
|   +-- chart of accounts
|
+-- Dimension matrix
|   +-- account
|   +-- subkonto 1
|   +-- subkonto 2
|   +-- subkonto 3
|   +-- department
|   +-- region
|   +-- budget article
|   +-- contract
|   +-- document
|
+-- Accounting views
|   +-- trial balance
|   +-- account card
|   +-- journal movement
|   +-- subledger breakdown
|   +-- debit/credit equality
|   +-- opening/turnover/closing
|
+-- Authority views
|   +-- ERP source ownership
|   +-- retained source evidence
|   +-- approved G8 canonical binding
|   +-- certification status
|
+-- Interactions
    +-- inspect source row
    +-- trace to document
    +-- trace to counterparty/contract
    +-- compare source vs canonical
    +-- propose mapping correction
    +-- route to review
```

The UI must not let a user read a trial balance row as subledger truth unless
the underlying document/subkonto binding is present and visible.

## 9. Operational dimension UI

```text
Operational Dimension Workspace
|
+-- Physical scope
|   +-- facility / terminal / station
|   +-- warehouse / tank
|   +-- product / grade
|   +-- unit and measurement basis
|
+-- Movement graph
|   +-- terminal receipt
|   +-- tank state
|   +-- truck / carrier / route
|   +-- depot transfer
|   +-- station receipt
|   +-- retail sale
|
+-- Conservation panel
|   +-- opening stock
|   +-- receipts
|   +-- dispatches
|   +-- measured losses
|   +-- closing stock
|   +-- variance
|
+-- Financial bridge
|   +-- quantity
|   +-- valuation
|   +-- freight
|   +-- tax / excise / customs
|   +-- COGS
|   +-- revenue
|   +-- gross margin
|
+-- Interactions
    +-- trace this liter
    +-- inspect waybill
    +-- inspect tank dip
    +-- compare station sales to inventory reduction
    +-- flag unexplained variance
    +-- open margin bridge
```

Operational views must show physical conservation and financial effect together
but not confuse measured physical truth with booked accounting truth.

## 10. Bitemporal UX

Time must be visible as a first-class control, not hidden in audit metadata.

```text
Time controls
|
+-- Business effective date: valid_at
+-- Known by source/G8 date: known_at
+-- Recorded by platform date: recorded_at
+-- Approved date: approved_at
+-- Correction date: corrected_at
+-- Replay as of: replay_as_of
```

Primary UI modes:

```text
Current approved view
Historical replay view
Original close-date view
Corrected truth view
Delta comparison view
Correction impact view
```

Example: an August movement corrected in September should appear as:

```text
Original August close state
Corrected August state known in September
Delta in inventory / COGS / margin / statement package
Evidence and approval path that caused the correction
```

## 11. Ask NYX UX

Ask NYX is a contextual reasoning workspace, not the authority layer.

```text
Ask NYX panel
|
+-- inherits current scope
+-- shows cited evidence
+-- labels answer type
|   +-- explanation
|   +-- hypothesis
|   +-- forecast
|   +-- recommendation
|   +-- refusal
|
+-- exposes trace
+-- exposes missing evidence
+-- supports follow-up investigation
+-- can prepare proposals
+-- cannot silently publish facts
+-- cannot silently execute actions
```

Required response states:

```text
ANSWER_WITH_EVIDENCE
PARTIAL_ANSWER_WITH_GAPS
HYPOTHESIS_ONLY
REQUIRES_APPROVAL
REFUSED_BY_AUTHORITY
SOURCE_UNAVAILABLE
OUT_OF_SCOPE
```

The panel should default to the selected object, table row, graph node, report
value or decision card. It should not answer from broad global context when an
exact selected scope is required.

## 12. Role-specific experiences

```text
CFO / executive
|
+-- enterprise truth overview
+-- liquidity and margin
+-- open risks
+-- certified reports
+-- scenario decisions
+-- action approval queue

Controller / close owner
|
+-- close cockpit
+-- trial balance
+-- journal and subledger reconciliation
+-- correction queue
+-- report certification
+-- audit package export

Finance analyst
|
+-- account analysis
+-- variance bridge
+-- evidence drilldown
+-- forecast / scenario
+-- investigation workpaper

Operations manager
|
+-- inventory and movements
+-- tank/station/warehouse state
+-- loss and variance
+-- route/waybill graph
+-- operational action queue

Ontology owner
|
+-- definitions
+-- mappings
+-- object relationships
+-- source bindings
+-- version review

Auditor / reviewer
|
+-- evidence packages
+-- lineage graph
+-- approval receipts
+-- replay-as-of views
+-- export validation

AI/ML governance owner
|
+-- agent traces
+-- evaluations
+-- drift
+-- learning candidates
+-- promotion / rollback

Platform operator
|
+-- runtime health
+-- queues and workers
+-- connector status
+-- backup/restore
+-- release gates
```

Each role sees the same governed objects through different task priority,
density, permissions and default workspace layout. The source of truth remains
shared.

## 13. Screen state machine

Every major screen should support the same state grammar.

```text
UNSCOPED
  -> missing company / period / entity / dataset

LOADING
  -> request active

READY_OBSERVED
  -> source/evidence data available but not authoritative

READY_APPROVED
  -> approved canonical state available

PARTIAL
  -> some dimensions available, others missing

BLOCKED
  -> policy, approval, exact-scope or evidence blocker

REFUSED
  -> action/request not allowed by authority model

STALE
  -> known data is older than required freshness

SUPERSEDED
  -> later evidence/version replaced this state

FAILED
  -> runtime or request failure

EMPTY
  -> no records for exact valid scope
```

Empty is not the same as unavailable. Unavailable is not the same as zero.
Blocked is not the same as failed.

## 14. Page-to-contract mapping

```text
Frontend route/workspace
|
+-- Home
|   +-- consumes workspace summary
|   +-- consumes queues
|   +-- consumes readiness/gates
|
+-- Companies
|   +-- consumes company context
|   +-- consumes legal entity graph
|   +-- consumes source coverage
|
+-- Sources and Data
|   +-- consumes source manifests
|   +-- consumes retained evidence
|   +-- consumes source rows
|   +-- emits retention/review requests
|
+-- Transformation
|   +-- consumes schema/profile/mapping candidates
|   +-- emits transformation runs
|   +-- emits mapping review decisions
|
+-- Ontology
|   +-- consumes resources/definitions/versions
|   +-- emits proposals
|   +-- emits independent review decisions
|
+-- Finance
|   +-- consumes trial balance/journal/ledger/report packages
|   +-- emits correction proposals
|   +-- emits certification requests
|
+-- Operations
|   +-- consumes movement/inventory/measurement state
|   +-- emits investigation/action proposals
|
+-- Planning
|   +-- consumes forecasts/scenarios
|   +-- emits decision recommendations
|
+-- Reporting
|   +-- consumes certified report packages
|   +-- emits export requests
|
+-- Decisions and Actions
|   +-- consumes recommendation/action queues
|   +-- emits approvals/actions
|   +-- consumes readback and outcome
|
+-- Runtime / Release
    +-- consumes health, tests, evidence gates, release readiness
```

## 15. Frontend engineering structure

The current application is a Next.js app. The target frontend should converge
around this structure:

```text
apps/web/app
|
+-- shell
|   +-- G8Workspace
|   +-- global navigation
|   +-- context bar
|   +-- persisted layout
|   +-- responsive rail
|
+-- shared UI
|   +-- badges
|   +-- panels
|   +-- tables
|   +-- drawers
|   +-- status strips
|   +-- empty/refusal states
|
+-- domain workspaces
|   +-- company
|   +-- source/data
|   +-- transformation
|   +-- ontology
|   +-- finance
|   +-- operations
|   +-- planning
|   +-- reporting
|   +-- investigation
|   +-- actions
|   +-- governance
|   +-- runtime
|
+-- contract clients
|   +-- authenticated API proxy
|   +-- typed contracts
|   +-- exact-scope request builders
|   +-- response validators
|
+-- state modules
|   +-- context state
|   +-- workspace state
|   +-- selection state
|   +-- replay/time state
|   +-- authority state
|   +-- queue/runtime state
|
+-- tests
    +-- shell/navigation tests
    +-- contract guards
    +-- authority/refusal tests
    +-- state-machine tests
    +-- browser journey tests
```

Existing app files already point toward this structure. The missing target is
not page count; it is convergence into one dimensional operating shell.

## 16. Current implementation mapping

```text
Existing frontend anchors
|
+-- g8-workspace.tsx
|   +-- current signed-in shell and navigation
|
+-- g8-ui.tsx
|   +-- primitive Brand / Panel / Badge / Empty / Signal
|
+-- company-workspace.tsx
|   +-- company context and company graph surface
|
+-- data-workspace.tsx
|   +-- data/source workspace
|
+-- source-* components
|   +-- source accounting, documents, dimensions, inspection and adoption
|
+-- semantic-analysis-workspace.tsx
|   +-- reviewed semantic analysis and retained execution
|
+-- ontology-workspace.tsx
|   +-- ontology resource and proposal surface
|
+-- finance-workspace.tsx
|   +-- financial workspace surface
|
+-- trial-balance-review.tsx
|   +-- trial balance package review
|
+-- company-journal-explorer.tsx
|   +-- journal source exploration
|
+-- operations-map.tsx / operations-canvas.tsx
|   +-- operational graph/map surface
|
+-- process-graph.tsx
|   +-- process and agent/workflow graph surface
|
+-- action-workbench.tsx
|   +-- action model and execution workbench
|
+-- operator-trace.tsx / canonical-trace.tsx
|   +-- lineage and trace inspection
|
+-- nyx-interaction.tsx
|   +-- contextual AI interaction panel
|
+-- runtime-state-workbench.tsx
    +-- runtime and state visibility
```

## 17. Delivery phases for frontend convergence

```text
F0 - Shell integrity
|
+-- one G8Workspace owns top-level navigation
+-- all workspaces inherit exact context
+-- no standalone financial truth pages

F1 - Context and authority unification
|
+-- shared ContextBar
+-- shared AuthorityBadge
+-- shared EvidenceBadge
+-- shared RefusalState
+-- no implicit company/period/dataset

F2 - Source-to-ontology journey
|
+-- source intake
+-- retained evidence
+-- transformation
+-- mapping review
+-- ontology publication
+-- trace drawer

F3 - Accounting execution journey
|
+-- trial balance
+-- account/subkonto matrix
+-- journal line drilldown
+-- ERP authority marker
+-- G8 canonical binding marker

F4 - Operational execution journey
|
+-- inventory conservation
+-- movement graph
+-- tank/station/warehouse state
+-- physical-to-financial bridge

F5 - Report and close journey
|
+-- reconciliation blockers
+-- correction handling
+-- report certification
+-- immutable export

F6 - Investigation and NYX journey
|
+-- selected-object AI context
+-- cited evidence
+-- hypothesis/refusal distinction
+-- proposal handoff

F7 - Decision/action journey
|
+-- recommendation
+-- maker/checker approval
+-- action eligibility
+-- execution
+-- readback
+-- outcome

F8 - Runtime/release journey
|
+-- evidence gates
+-- health
+-- restart/readback
+-- backup/restore
+-- release readiness
```

## 18. UX acceptance criteria

```text
Frontend acceptance
|
+-- A user can see exact scope on every consequential screen.
+-- A user can distinguish raw, retained, derived, approved, certified and AI-inferred state.
+-- A user can trace a financial number to source evidence.
+-- A user can trace an operational movement to physical source documents.
+-- A user can compare original and corrected historical states.
+-- A user cannot approve or execute without required authority visible.
+-- A user cannot mistake unavailable evidence for zero.
+-- A user cannot mistake AI text for approved financial truth.
+-- A user can move from source row to ontology object to ledger/report impact.
+-- A user can move from inventory movement to COGS/revenue/margin impact.
+-- A user can see why an action/report/certification/export is blocked.
+-- A user can export only when evidence and approval gates are satisfied.
+-- A browser test proves the source-to-action-to-export journey.
```

## 19. Target one-sentence UI description

G8's frontend is a governed enterprise operating shell where every user action
starts from exact context, every number exposes evidence and authority, every
AI statement is separated from approved truth, and every decision can proceed
from source observation to ontology, calculation, report, approval, action,
readback, outcome and learning without leaving the product.

## 20. Frontend-to-backend wiring architecture

The frontend architecture is only complete when every surface is wired through
an explicit contract path. In this codebase, the browser does not call FastAPI
directly. It calls allowlisted Next.js proxy routes under `apps/web/app/api`,
which forward to FastAPI routes under `services/api/src/finai_api/api`.

```text
Browser UI component
  -> Next.js route handler /api/*
      -> backendBaseUrl()
          -> FastAPI /v1/*
              -> domain service
                  -> PostgreSQL / retained evidence / workflow / object store
                      -> typed response / refusal / receipt
                          -> UI state machine
```

Current proxy topology:

```text
Frontend proxy
|
+-- /api/workspace/[...path]
|   +-- forwards to /v1/workspace/*
|   +-- allowlists session, summary, intake, objects, constructions,
|       workflows, report inputs and report calculations
|
+-- /api/ontology/[...path]
|   +-- forwards to /v1/ontology/*
|   +-- allowlists ontology context, resources, proposals, source documents,
|       transformations, functions, lifecycle, event time, certifications,
|       retention, runtime observations, company journals, finance, regulation,
|       source adoption, period control and account dimension policy
|
+-- /api/operations/[...path]
|   +-- forwards to /v1/operations/*
|   +-- allowlists map, map connections and import proposal
|
+-- /api/diagnostics/[...path]
|   +-- forwards to /v1/diagnostics/*
|   +-- allowlists readiness and evidence context
|
+-- /api/hydration
|   +-- forwards to /v1/hydration/ingest
|
+-- /api/hydration/package
|   +-- forwards to /v1/hydration/trial-balance-package
|
+-- /api/readiness
    +-- checks /v1/workspace/session and FastAPI /ready
```

Backend route topology exposed to the product:

```text
FastAPI routers
|
+-- /v1/workspace
|   +-- operator session
|   +-- summary
|   +-- evidence intake
|   +-- constructions
|   +-- object workspace
|   +-- report calculations
|   +-- workflows
|
+-- /v1/hydration
|   +-- source ingest
|   +-- historical trial balance package
|
+-- /v1/ontology
|   +-- context / catalog / graph / resources / proposals
|   +-- model definitions and fact runs
|   +-- source documents and source adoption
|   +-- transformations and retained builds
|   +-- analysis / functions / object sets
|   +-- lifecycle / certifications / retention
|   +-- event-time replay
|   +-- company context and company journals
|   +-- finance contracts, dimensions, candidates and TB draft
|   +-- period control and account dimension policy
|   +-- regulation and runtime observations
|   +-- operator trace and resource inspection
|
+-- /v1/operations
|   +-- operations map
|   +-- map connections
|   +-- import proposal
|
+-- /v1/diagnostics
    +-- readiness
    +-- evidence context
```

## 21. Surface wiring matrix

```text
UI surface
|
+-- Sign-in / session
|   +-- frontend: g8-workspace.tsx
|   +-- proxy: /api/workspace/session
|   +-- backend: /v1/workspace/session
|   +-- required UI states: unauthenticated, authenticated, denied, unavailable
|
+-- Home / command overview
|   +-- frontend: g8-workspace.tsx, executive-overview.tsx, work-queue.tsx
|   +-- proxy: /api/workspace/summary, /api/workspace/intake,
|       /api/ontology/proposal-queue, /api/readiness
|   +-- backend: /v1/workspace/summary, /v1/workspace/intake,
|       /v1/ontology/proposal-queue, /ready
|   +-- required UI states: ready, partial, blocked, stale, service unavailable
|
+-- Company context
|   +-- frontend: company-picker.tsx, company-workspace.tsx,
|       company-period-control.tsx
|   +-- proxy: /api/ontology/company-context, /api/ontology/context,
|       /api/ontology/resources/*
|   +-- backend: /v1/ontology/company-context, /v1/ontology/context,
|       /v1/ontology/resources/*
|   +-- required UI states: unscoped, scoped, no authority, source coverage gap
|
+-- Source intake and retained evidence
|   +-- frontend: evidence-intake.tsx, source-documents.tsx,
|       source-inspection.tsx, receipt-panel.tsx
|   +-- proxy: /api/hydration, /api/ontology/source-documents/*,
|       /api/workspace/constructions/*
|   +-- backend: /v1/hydration/ingest, /v1/ontology/source-documents/*,
|       /v1/workspace/constructions/*
|   +-- required UI states: retained, hash verified, rejected, unavailable,
|       source too large, scope mismatch
|
+-- 1C accounting setup and dimensions
|   +-- frontend: source-accounting-setup.tsx, source-accounting-context.tsx,
|       source-account-bindings.tsx, account-dimension-policy-workbench.tsx
|   +-- proxy: /api/ontology/source-documents/*/accounting-context/*,
|       /api/ontology/account-dimension-policy
|   +-- backend: /v1/ontology/source-documents/*/accounting-context/*,
|       /v1/ontology/account-dimension-policy
|   +-- required UI states: observed 1C source, proposed setup,
|       binding candidate, approved policy, refused publication
|
+-- Trial balance and finance authority
|   +-- frontend: trial-balance-review.tsx, finance-workspace.tsx,
|       finance-analysis.tsx, accounting-facts.tsx
|   +-- proxy: /api/hydration/package, /api/ontology/finance/*,
|       /api/ontology/company-journals/*
|   +-- backend: /v1/hydration/trial-balance-package,
|       /v1/ontology/finance/*, /v1/ontology/company-journals/*
|   +-- required UI states: source trial balance, draft, reconciled,
|       canonical candidate, approved, exportable, refused
|
+-- Transformation and semantic analysis
|   +-- frontend: semantic-analysis-workspace.tsx, builds-workbench.tsx,
|       saved-analysis-workbench.tsx, worksheet-analysis-result.tsx
|   +-- proxy: /api/ontology/analysis/*, /api/ontology/functions/*,
|       /api/ontology/transformations/*
|   +-- backend: /v1/ontology/analysis/*, /v1/ontology/functions/*,
|       /v1/ontology/transformations/*
|   +-- required UI states: queued, running, completed, retained, replayed,
|       failed, cancelled, publication pending
|
+-- Ontology model and review
|   +-- frontend: ontology-workspace.tsx, ontology-definition-editor.tsx,
|       ontology-connections.tsx, proposal-impact.tsx, promotion-readiness.tsx
|   +-- proxy: /api/ontology/model/*, /api/ontology/resources/*,
|       /api/ontology/proposals/*
|   +-- backend: /v1/ontology/model/*, /v1/ontology/resources/*,
|       /v1/ontology/proposals/*
|   +-- required UI states: definition draft, preview, proposal,
|       checker review, approved, rejected, superseded, rollback proposed
|
+-- Lineage, trace and historical replay
|   +-- frontend: canonical-trace.tsx, operator-trace.tsx,
|       history-explorer.tsx, operator-history.tsx, identity-history.tsx
|   +-- proxy: /api/ontology/operator/trace/*,
|       /api/ontology/operator/resources/*, /api/ontology/history-search,
|       /api/ontology/event-time/*
|   +-- backend: /v1/ontology/operator/trace/*,
|       /v1/ontology/operator/resources/*, /v1/ontology/history-search,
|       /v1/ontology/event-time/*
|   +-- required UI states: selected version, known_at restored,
|       replay available, replay unavailable, dependency hidden by policy
|
+-- Operations graph and physical execution
|   +-- frontend: operations-map.tsx, operations-canvas.tsx,
|       operating-report.tsx, posted-movement-report.tsx
|   +-- proxy: /api/operations/map, /api/operations/map/*/connections,
|       /api/ontology/operations/*
|   +-- backend: /v1/operations/map, /v1/operations/map/*/connections,
|       /v1/ontology/operations/*
|   +-- required UI states: physical source observed, movement linked,
|       conservation passed, variance, import proposal, refused action
|
+-- Regulation and external control
|   +-- frontend: regulation-workspace.tsx, regulatory-sources.tsx,
|       regulatory-monitors.tsx, regulatory-investigation.tsx
|   +-- proxy: /api/ontology/regulation/*
|   +-- backend: /v1/ontology/regulation/*
|   +-- required UI states: captured, monitored, assessed, impact calculated,
|       proposal pending, externally unavailable
|
+-- Actions and workflows
|   +-- frontend: action-workbench.tsx, work-queue.tsx, process-graph.tsx
|   +-- proxy: /api/workspace/workflows/*, /api/ontology/operations/*
|   +-- backend: /v1/workspace/workflows/*, /v1/ontology/operations/*
|   +-- required UI states: recommended, approval required, approved,
|       executing, readback verified, outcome measured, rolled back
|
+-- Runtime and release
|   +-- frontend: runtime-state-workbench.tsx, workspace health panels
|   +-- proxy: /api/readiness, /api/diagnostics/readiness,
|       /api/ontology/runtime-observations/*
|   +-- backend: /ready, /v1/diagnostics/readiness,
|       /v1/ontology/runtime-observations/*
|   +-- required UI states: healthy, degraded, blocked, stale, release gate open
```

## 22. Typed contract boundary

The frontend should not hand-code financial object shapes when contracts already
exist. The contract boundary is:

```text
packages/contracts
|
+-- ontology.ts
+-- ontology-wire.ts
+-- object-sets.ts
+-- lifecycle.ts
+-- certification.ts
+-- company-journals.ts
+-- account-dimension-policy.ts
+-- semantic-analysis.ts
+-- source-event.ts
+-- period-control.ts
+-- proposal-queue.ts
+-- source-authority.schema.json
+-- canonical-journal-line.schema.json
+-- fact-envelope.schema.json
+-- ontology-catalog.schema.json
```

Frontend rule: every consequential request should have one of these:

```text
typed TypeScript contract
JSON schema contract
OpenAPI-derived response shape
explicit local parser/validator
```

If none exists, the surface is not fully wired. It is only visually connected.

## 23. Wiring completeness gates

A frontend surface is `FULLY_WIRED` only when all checks pass:

```text
1. UI route exists in the G8 shell.
2. UI surface inherits exact FrontendContext.
3. Next.js proxy allowlists the required route.
4. FastAPI route exists and is included in main.py.
5. Backend route calls a real domain service.
6. Request carries exact tenant/company/period/currency/version/evidence scope.
7. Response has a typed contract or validator.
8. UI renders ready, loading, partial, blocked, refused, stale and unavailable.
9. Authority state is visible at the point of decision.
10. Evidence or lineage drawer can open from the object/value.
11. Mutating actions require maker/checker or explicit approval.
12. Negative authority tests prove missing scope does not fall back.
13. Browser test proves the mounted surface against the backend.
14. Restart/readback proves persisted state where persistence is claimed.
```

These gates are intentionally stricter than "component exists" or "route
exists." A screen is not fully wired until the refusal, authority and evidence
states are wired too.

## 24. Current truthful wiring status

```text
Implemented wiring visible in this checkout
|
+-- Strongly anchored
|   +-- signed-in G8 shell
|   +-- workspace summary/intake/constructions/objects
|   +-- ontology context/resources/proposals
|   +-- source documents and source accounting workbenches
|   +-- transformation/functions/semantic analysis surfaces
|   +-- trial balance package and finance/TB route families
|   +-- company journals and account dimension policy
|   +-- operations map route family
|   +-- trace/history/event-time route families
|   +-- readiness/diagnostics/runtime observation route families
|
+-- Architecturally required but not proven by this document alone
|   +-- complete Planning workspace backend wiring
|   +-- complete Reporting workspace backend wiring beyond report calculations
|   +-- full decision/action external adapter readback
|   +-- full outcome measurement and learning promotion UX
|   +-- full petroleum physical-to-financial cockpit in the unified shell
|   +-- full AI reasoning execution with governed citations and refusal testing
|   +-- end-to-end source-to-action-to-export browser proof
|   +-- production/runtime/scale/release acceptance
```

Therefore the correct claim is:

```text
The frontend architecture is now dimensionally specified and mapped to the
existing backend/proxy topology. It is not yet proven fully wired end-to-end
until every surface passes the wiring completeness gates above.
```

## 25. Full dimensional frontend execution matrix

This matrix is the practical definition of "full dimensional frontend." Each
row is a product dimension. Each row must have UI projection, backend contract,
authority rule and test evidence.

```text
Dimension: identity and access
|
+-- UI projection: sign-in, active actor, role badges, permission-gated actions
+-- frontend state: session, principal, permissions, authorized scopes
+-- backend route: /v1/workspace/session
+-- proxy route: /api/workspace/session
+-- authority rule: no data or action without identity
+-- failure UI: unauthenticated, denied, service unavailable
+-- test proof: missing/invalid token refuses; valid token scopes surfaces

Dimension: company and enterprise scope
|
+-- UI projection: company picker, company graph, legal entity context
+-- frontend state: selected company, entity, facility, period
+-- backend route: /v1/ontology/company-context, /v1/ontology/context
+-- proxy route: /api/ontology/company-context, /api/ontology/context
+-- authority rule: no financial interpretation without exact company scope
+-- failure UI: unscoped, no company access, source coverage gap
+-- test proof: route refuses unauthorized company and no fallback company appears

Dimension: source evidence
|
+-- UI projection: source document list, retained file, source row inspector
+-- frontend state: source id, document id, row coordinate, hash, source class
+-- backend route: /v1/hydration/ingest, /v1/ontology/source-documents/*
+-- proxy route: /api/hydration, /api/ontology/source-documents/*
+-- authority rule: source observation is not canonical financial truth
+-- failure UI: retained unavailable, hash mismatch, unsupported source, too large
+-- test proof: hash verified before evidence display or export

Dimension: 1C/SAP accounting dimensions
|
+-- UI projection: account, subkonto, contract, counterparty, document matrix
+-- frontend state: account code, subkonto coordinates, source document binding
+-- backend route: /v1/ontology/source-documents/*/accounting-context/*
+-- proxy route: /api/ontology/source-documents/*/accounting-context/*
+-- authority rule: trial balance row cannot become posting authority by itself
+-- failure UI: missing subkonto, unmapped account, duplicate/ambiguous account
+-- test proof: account binding refuses missing source or wrong company scope

Dimension: canonical ontology
|
+-- UI projection: object panel, graph, definition editor, proposal review
+-- frontend state: resource id, version id, definition version, known_at
+-- backend route: /v1/ontology/resources/*, /v1/ontology/model/*, /v1/ontology/proposals/*
+-- proxy route: /api/ontology/resources/*, /api/ontology/model/*, /api/ontology/proposals/*
+-- authority rule: ontology changes require proposal and independent review
+-- failure UI: proposal pending, checker conflict, superseded, rollback required
+-- test proof: same actor cannot silently approve own consequential proposal

Dimension: transformation and semantic execution
|
+-- UI projection: build graph, transformation run, saved analysis, replay
+-- frontend state: run id, invocation id, step state, retained input references
+-- backend route: /v1/ontology/transformations/*, /v1/ontology/analysis/*, /v1/ontology/functions/*
+-- proxy route: /api/ontology/transformations/*, /api/ontology/analysis/*, /api/ontology/functions/*
+-- authority rule: retained execution result does not grant financial authority
+-- failure UI: queued, running, failed, cancelled, missing retained input
+-- test proof: replay uses exact retained input and does not read latest fallback

Dimension: finance and ledger
|
+-- UI projection: trial balance, journals, account explorer, facts, TB package
+-- frontend state: period, ledger, account, journal id, fact run id, package id
+-- backend route: /v1/hydration/trial-balance-package, /v1/ontology/finance/*, /v1/ontology/company-journals/*
+-- proxy route: /api/hydration/package, /api/ontology/finance/*, /api/ontology/company-journals/*
+-- authority rule: deterministic calculations only; AI cannot create ledger truth
+-- failure UI: unreconciled, missing source, certification refused, export blocked
+-- test proof: debit/credit and source lineage errors block certification

Dimension: physical operations
|
+-- UI projection: operations map, movement graph, tank/warehouse/station state
+-- frontend state: facility, asset, product, movement id, unit, measurement basis
+-- backend route: /v1/operations/*, /v1/ontology/operations/*
+-- proxy route: /api/operations/*, /api/ontology/operations/*
+-- authority rule: physical measurement is distinct from booked accounting truth
+-- failure UI: conservation variance, missing waybill, missing tank dip
+-- test proof: movement graph refuses unbound source/destination or missing unit

Dimension: physical-to-financial bridge
|
+-- UI projection: margin bridge, quantity/value reconciliation, variance panel
+-- frontend state: quantity, unit, valuation method, COGS, revenue, tax/freight
+-- backend route: finance, operations and fact reconciliation route families
+-- proxy route: /api/ontology/finance/*, /api/operations/*
+-- authority rule: margin is certified only when both physical and financial evidence bind
+-- failure UI: bridge incomplete, valuation missing, operational evidence missing
+-- test proof: report blocks when quantity and ledger evidence cannot reconcile

Dimension: bitemporal replay
|
+-- UI projection: replay picker, original/corrected comparison, history graph
+-- frontend state: valid_at, known_at, recorded_at, corrected_at, replay_as_of
+-- backend route: /v1/ontology/event-time/*, /v1/ontology/history-search, /v1/ontology/operator/resources/*
+-- proxy route: /api/ontology/event-time/*, /api/ontology/history-search, /api/ontology/operator/resources/*
+-- authority rule: corrections do not erase original known state
+-- failure UI: replay unavailable, hidden dependency, stale version, superseded
+-- test proof: same object renders different valid/known/replay states correctly

Dimension: reporting and export
|
+-- UI projection: report package, certification status, export eligibility
+-- frontend state: report id, package id, certification id, content hash
+-- backend route: /v1/workspace/report-calculations/*, finance/report route families
+-- proxy route: /api/workspace/report-calculations/*, /api/ontology/finance/*
+-- authority rule: export only after required evidence and approvals
+-- failure UI: export blocked, statement package incomplete, evidence missing
+-- test proof: export refuses uncertified or stale package

Dimension: NYX reasoning
|
+-- UI projection: Ask NYX rail, cited answer, trace, refusal, proposal handoff
+-- frontend state: selected object, current scope, answer type, cited evidence
+-- backend route: governed reasoning route family when implemented
+-- proxy route: explicit allowlisted proxy required
+-- authority rule: answer is non-authoritative unless promoted through approval
+-- failure UI: hypothesis only, missing evidence, out of scope, refused
+-- test proof: AI answer cannot mutate truth or hide missing evidence

Dimension: decisions and actions
|
+-- UI projection: recommendation card, approval drawer, action workbench, readback
+-- frontend state: decision id, approval id, action id, execution id, readback id
+-- backend route: /v1/workspace/workflows/*, /v1/ontology/operations/*
+-- proxy route: /api/workspace/workflows/*, /api/ontology/operations/*
+-- authority rule: consequential action requires maker/checker and adapter scope
+-- failure UI: approval required, blocked by policy, execution failed, readback missing
+-- test proof: action cannot execute without approval and exact scope

Dimension: outcomes and learning
|
+-- UI projection: outcome timeline, actual vs expected, learning candidate review
+-- frontend state: outcome id, measurement window, evaluation id, candidate id
+-- backend route: outcome and learning route families when implemented
+-- proxy route: explicit allowlisted proxy required
+-- authority rule: learning is candidate until evaluated and promoted
+-- failure UI: no measurement, insufficient sample, drift, promotion refused
+-- test proof: learning candidate cannot silently change production policy/model

Dimension: runtime and release
|
+-- UI projection: runtime health, workers, gates, release readiness
+-- frontend state: service health, queue health, gate state, build/release id
+-- backend route: /ready, /v1/diagnostics/*, /v1/ontology/runtime-observations/*
+-- proxy route: /api/readiness, /api/diagnostics/*, /api/ontology/runtime-observations/*
+-- authority rule: local runtime is not production or release acceptance
+-- failure UI: degraded, stale, blocked, gate open
+-- test proof: gate display keeps code/local/authentic/production/scale/release separate
```

## 26. Full dimensional component ownership tree

The frontend should converge toward this ownership tree. A component belongs to
one layer only; domain workspaces compose shared primitives rather than
reimplementing authority, evidence, time or refusal behavior.

```text
apps/web/app
|
+-- shell/
|   +-- G8Workspace
|   +-- AuthBoundary
|   +-- GlobalContextBar
|   +-- NavigationRail
|   +-- WorkspaceViewport
|   +-- PersistentNyxRail
|   +-- DrawerHost
|   +-- ToastAndRefusalHost
|
+-- context/
|   +-- useFrontendContext
|   +-- useCompanyScope
|   +-- useFinancialScope
|   +-- useOperationalScope
|   +-- useTimeScope
|   +-- useAuthorityScope
|   +-- exactScopeRequestBuilder
|
+-- contracts/
|   +-- workspaceClient
|   +-- ontologyClient
|   +-- operationsClient
|   +-- diagnosticsClient
|   +-- financeClient
|   +-- transformationClient
|   +-- actionClient
|   +-- responseValidators
|
+-- primitives/
|   +-- AuthorityBadge
|   +-- EvidenceBadge
|   +-- TimeBadge
|   +-- ScopeChip
|   +-- VersionPill
|   +-- GateBadge
|   +-- RefusalState
|   +-- MissingEvidence
|   +-- DataTable
|   +-- GraphCanvas
|   +-- Timeline
|   +-- ComparisonPanel
|   +-- ApprovalPanel
|
+-- drawers/
|   +-- EvidenceDrawer
|   +-- LineageDrawer
|   +-- AuthorityDrawer
|   +-- MappingDrawer
|   +-- ApprovalDrawer
|   +-- ActionDrawer
|   +-- OutcomeDrawer
|   +-- RuntimeDrawer
|
+-- workspaces/
|   +-- home
|   +-- companies
|   +-- sources
|   +-- transformations
|   +-- ontology
|   +-- finance
|   +-- operations
|   +-- planning
|   +-- reporting
|   +-- investigation
|   +-- decisions
|   +-- governance
|   +-- runtime
|
+-- state-machines/
|   +-- sourceState
|   +-- mappingState
|   +-- canonicalFactState
|   +-- reportState
|   +-- nyxAnswerState
|   +-- actionState
|   +-- outcomeState
|   +-- runtimeGateState
|
+-- tests/
    +-- shell-context.test
    +-- proxy-allowlist.test
    +-- authority-refusal.test
    +-- source-to-ontology.browser
    +-- finance-certification.browser
    +-- physical-bridge.browser
    +-- source-to-action-to-export.browser
```

## 27. Required dimensional state machines

```text
Source evidence state
UNSELECTED
  -> SELECTED_SOURCE
  -> UPLOADING_OR_CONNECTING
  -> RETAINED
  -> PROFILED
  -> VALIDATED
  -> REJECTED
  -> REVIEW_REQUIRED
  -> APPROVED_FOR_USE
  -> SUPERSEDED

Mapping and ontology state
NO_MAPPING
  -> CANDIDATE
  -> PREVIEWED
  -> SUBMITTED
  -> CHECKER_REVIEW
  -> APPROVED
  -> PUBLISHED
  -> REJECTED
  -> ROLLBACK_PROPOSED

Financial fact state
NO_FACT
  -> SOURCE_OBSERVED
  -> DERIVED
  -> RECONCILED
  -> CANONICAL_CANDIDATE
  -> APPROVED_CANONICAL
  -> REPORT_INCLUDED
  -> CERTIFIED
  -> EXPORTED
  -> RESTATED

Operational movement state
NO_MOVEMENT
  -> SOURCE_OBSERVED
  -> ENTITY_BOUND
  -> ROUTE_LINKED
  -> CONSERVATION_CHECKED
  -> VARIANCE_FLAGGED
  -> FINANCIAL_BRIDGED
  -> ACTION_RECOMMENDED
  -> ACTION_APPROVED
  -> READBACK_VERIFIED

AI reasoning state
NO_CONTEXT
  -> SCOPED_CONTEXT
  -> EVIDENCE_RETRIEVED
  -> ANSWER_WITH_CITATIONS
  -> HYPOTHESIS_ONLY
  -> RECOMMENDATION
  -> PROPOSAL_PREPARED
  -> REFUSED_BY_AUTHORITY

Action state
NO_ACTION
  -> RECOMMENDED
  -> ELIGIBILITY_CHECKED
  -> MAKER_APPROVED
  -> CHECKER_APPROVED
  -> QUEUED
  -> EXECUTING
  -> EXECUTED
  -> READBACK_VERIFIED
  -> OUTCOME_MEASURED
  -> ROLLED_BACK
```

Each state machine must be represented in UI, backend responses and tests. A
screen that shows only success and error is not dimensionally complete.

## 28. Full dimensional navigation rule

Navigation must not reset enterprise truth. Moving across surfaces preserves
scope and selected object identity unless the target surface explicitly cannot
support that scope.

```text
Selected source row
  -> source inspector
  -> accounting dimension binding
  -> ontology object
  -> lineage graph
  -> journal line / movement
  -> financial or operational bridge
  -> report impact
  -> NYX investigation
  -> proposal
  -> approval
  -> action / export

Selected financial number
  -> calculation detail
  -> source rows
  -> journal lines
  -> account/subkonto breakdown
  -> operational bridge where applicable
  -> report package
  -> certification receipt
  -> export receipt

Selected operational movement
  -> source document
  -> tank/warehouse state
  -> route/waybill path
  -> inventory conservation
  -> valuation/COGS
  -> revenue/margin impact
  -> variance investigation
  -> action recommendation
```

The UI must never force the user to manually rebuild the same context across
pages when the product already has enough identity to carry it.

## 29. Missing backend wiring register

This register is part of the frontend architecture because a UI surface without
an executable backend path is not full-dimensional.

```text
Backend wiring required for full frontend completion
|
+-- Planning
|   +-- scenario version API
|   +-- forecast result API
|   +-- liquidity projection API
|   +-- actual-versus-plan outcome API
|   +-- UI acceptance: scenario comparison and evidence-cited forecast
|
+-- Reporting
|   +-- certified statement package API
|   +-- immutable export eligibility API
|   +-- report comparison API
|   +-- narrative evidence API
|   +-- UI acceptance: export refuses until certification gates pass
|
+-- NYX reasoning
|   +-- scoped reasoning API
|   +-- citation/evidence packet API
|   +-- refusal classification API
|   +-- proposal handoff API
|   +-- UI acceptance: answer labels authority and cited evidence
|
+-- Decisions/actions
|   +-- recommendation API
|   +-- action eligibility API
|   +-- maker/checker approval API
|   +-- external adapter execution API
|   +-- readback API
|   +-- UI acceptance: no execution without approval and readback display
|
+-- Outcomes/learning
|   +-- outcome measurement API
|   +-- evaluation case API
|   +-- learning candidate API
|   +-- shadow replay API
|   +-- promotion/rollback API
|   +-- UI acceptance: learning cannot silently alter production behavior
|
+-- Production/release
    +-- gate evidence API
    +-- build/release id API
    +-- restore proof API
    +-- load/scale proof API
    +-- UI acceptance: local proof is separated from release acceptance
```

## 30. Final completeness definition

The frontend becomes full-dimensional only when the following equation is true:

```text
FULL_DIMENSIONAL_FRONTEND =
  global governed shell
  + exact context propagation
  + dimensional workspace projections
  + typed backend contracts
  + proxy allowlist coverage
  + authority/refusal rendering
  + source/evidence/lineage drawers
  + bitemporal replay
  + financial and operational bridge views
  + role-specific task modes
  + action/readback/outcome loops
  + NYX cited reasoning boundaries
  + browser tests for source-to-action-to-export
  + restart/readback proof
  + independent evidence gates
```

Anything less is a partial frontend architecture.
