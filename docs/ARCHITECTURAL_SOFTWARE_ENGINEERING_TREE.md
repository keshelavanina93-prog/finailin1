# G8 by NYXCore — Architectural, Software and Engineering Trees

Status: `MULTIDIMENSIONAL TARGET ARCHITECTURE + CURRENT REPOSITORY MAP`

This document separates three things that must not be conflated:

1. the product architecture G8 is intended to become;
2. the software structure currently present in the repository/worktrees;
3. the dependency-ordered engineering path required to reach the target.

The product name is **G8 by NYXCore**. `FinAI`, `FinAI / NYX Core` and
`NYXCoreThinker` are internal or architectural names.

## 0. The dimensional model

The product is not adequately represented by a single vertical stack. Every
material object, calculation, explanation, decision and action exists at the
intersection of these dimensions:

```text
G8 object / event / conclusion / action
│
├── Authority dimension
│   ├── Source system authority
│   ├── Retained evidence
│   ├── Approved mapping / policy
│   ├── Deterministic canonical fact
│   ├── AI inference / recommendation
│   ├── Human approval
│   └── External execution and readback
│
├── Time dimension
│   ├── Valid/business time
│   ├── Known/source-observation time
│   ├── Recorded/system time
│   ├── Event time and processing time
│   ├── Version effective time
│   ├── Correction / supersession time
│   └── Historical replay time
│
├── Evidence and epistemic dimension
│   ├── OBSERVED
│   ├── DERIVED
│   ├── INFERRED
│   ├── HYPOTHESIS
│   ├── MISSING_EVIDENCE
│   ├── UNAVAILABLE
│   ├── REFUSED / BLOCKED
│   └── CERTIFIED only when independently accepted
│
├── Scope and identity dimension
│   ├── Tenant
│   ├── Enterprise / legal entity
│   ├── Company / subsidiary
│   ├── Facility / station / warehouse
│   ├── Account / product / contract / movement
│   ├── Period / currency / scenario
│   └── Actor / role / permission scope
│
├── Domain dimension
│   ├── Shared enterprise and organization
│   ├── Finance and accounting
│   ├── Planning, forecasting and treasury
│   ├── Procurement, sales and contracts
│   ├── Inventory and supply chain
│   ├── Manufacturing, assets and maintenance
│   ├── Petroleum, energy and physical operations
│   ├── Workforce and responsibility
│   ├── Risk, tax, sustainability and regulation
│   └── External market intelligence
│
├── Cognitive dimension
│   ├── Discovery
│   ├── Semantic understanding
│   ├── Reconciliation
│   ├── Deterministic calculation
│   ├── Explanation
│   ├── Forecasting and simulation
│   ├── Causal reasoning
│   ├── Recommendation
│   └── Governed learning
│
├── Lifecycle dimension
│   ├── Connect
│   ├── Retain
│   ├── Discover
│   ├── Transform
│   ├── Understand
│   ├── Reconcile
│   ├── Calculate
│   ├── Report
│   ├── Reason / predict / simulate
│   ├── Decide / approve
│   ├── Act
│   ├── Verify / read back
│   ├── Measure outcome
│   └── Learn / rollback
│
├── Runtime dimension
│   ├── Draft / proposed
│   ├── Queued
│   ├── Running
│   ├── Waiting for evidence / tool / approval
│   ├── Blocked by policy or scope
│   ├── Failed / timed out
│   ├── Completed
│   ├── Superseded
│   └── Rolled back
│
├── Experience dimension
│   ├── Executive
│   ├── Controller / finance
│   ├── Analyst
│   ├── Operations manager
│   ├── Auditor
│   ├── Ontology owner
│   ├── AI/ML governance owner
│   └── Platform/security operator
│
├── Trust-zone dimension
│   ├── User interaction zone
│   ├── Application services zone
│   ├── AI/model zone
│   ├── Connector zone
│   ├── Evidence/authority zone
│   ├── Action execution zone
│   └── Observability zone
│
└── Acceptance dimension
    ├── CODE_PRESENT
    ├── LOCAL_CONTRACT_PASS
    ├── LOCAL_INTEGRATED_PASS
    ├── AUTHENTIC_SOURCE_PASS
    ├── GENERALIZATION_PASS
    ├── PRODUCTION_RUNTIME_PASS
    ├── SCALE_PASS
    └── RELEASE_ACCEPTED
```

This means, for example, that a financial number is not just a value. It is a
value for a tenant/company/period/currency, at a business and knowledge time,
with a source and calculation lineage, an epistemic state, an authority level,
an approval state, a version, and a release-evidence status.

## 1. Product architectural tree

```text
G8 by NYXCore
└── Governed Financial AGI and Industrial Decision Intelligence Operating System
    │
    ├── 01. Experience Plane
    │   ├── Persistent governed shell
    │   ├── Executive Financial Cockpit
    │   ├── Financial Command Center
    │   ├── Controller / Close Workspace
    │   ├── Data and Source Intake
    │   ├── Transformation Studio / Mapping Workbench
    │   ├── Business-System Explorer
    │   ├── Ontology and Semantic Governance Studio
    │   ├── Analyst Investigation Workspace
    │   ├── Financial Reporting
    │   ├── Planning / Forecasting / Treasury
    │   ├── Inventory / Physical Operations / Maps
    │   ├── Evidence and Correction Workbench
    │   ├── Decision and Approval Queue
    │   ├── Operational Action Center
    │   ├── Audit and Governance Console
    │   ├── ML Ops / Evaluation Console
    │   ├── Learning Center
    │   └── Ask NYX / Contextual Reasoning Workspace
    │
    ├── 02. Identity and Authority Plane
    │   ├── Tenant, company, period and role scope
    │   ├── Actor provenance
    │   ├── Permissions and policy
    │   ├── Approval boundaries
    │   └── Refusal and no-fallback states
    │
    ├── 03. Source Connectivity Plane
    │   ├── 1C / SAP / ERP
    │   ├── Databases and warehouses
    │   ├── OData / REST / GraphQL APIs
    │   ├── XLSX / CSV / XML / JSON / PDF
    │   ├── Banking and treasury
    │   ├── WMS / production / asset systems
    │   ├── Industrial meters and movement systems
    │   ├── Contracts and documents
    │   └── Market / regulatory / external intelligence
    │
    ├── 04. Immutable Evidence Plane
    │   ├── Source manifests and capture receipts
    │   ├── Retained files, payloads and source rows
    │   ├── Validation and transformation receipts
    │   ├── Approval, calculation and export receipts
    │   ├── Action and outcome receipts
    │   └── Cryptographic hashes and immutable lineage
    │
    ├── 05. Data Transformation and Semantic Compilation Plane
    │   ├── Discovery and profiling
    │   ├── Parsing, OCR and table extraction
    │   ├── Normalize / filter / join / aggregate / temporal operations
    │   ├── Entity resolution and duplicate handling
    │   ├── Semantic and accounting mappings
    │   ├── Quality and contract validation
    │   ├── Versioned transformation DAGs
    │   ├── Exact input bindings and output contracts
    │   └── Replay, publication and readback
    │
    ├── 06. Business-System Understanding Plane
    │   ├── Structural discovery
    │   ├── Semantic induction
    │   ├── Process discovery
    │   ├── Company Business Model
    │   ├── Accounting graph
    │   ├── Physical-operation graph
    │   ├── Authority and policy graph
    │   └── Explicit hypotheses and missing evidence
    │
    ├── 07. Ontology and Knowledge Graph Plane
    │   ├── Companies, people, products, accounts and facilities
    │   ├── Contracts, movements, assets and processes
    │   ├── Financial and operational rules
    │   ├── Relations and dependency graph
    │   ├── Ontology proposals and collision detection
    │   ├── Impact preview
    │   ├── Versioned publication
    │   └── Rollback and historical reconstruction
    │
    ├── 08. Canonical Truth Plane
    │   ├── Organization and legal entities
    │   ├── Accounting scope and chart of accounts
    │   ├── Journal, ledger and financial facts
    │   ├── Customers, suppliers, products and contracts
    │   ├── Inventory, facilities and physical movements
    │   ├── Cash, banking and workforce
    │   ├── Plans, forecasts and scenarios
    │   └── Decision, action and outcome objects
    │
    ├── 09. Financial and Industrial Calculation Plane
    │   ├── Debit-credit and trial-balance controls
    │   ├── Journal and posting preparation
    │   ├── Statements, consolidation, FX and intercompany
    │   ├── Cash flow, tax, covenant and profitability
    │   ├── Inventory costing and valuation
    │   ├── Physical ledger and movement integrity
    │   ├── Quantity-to-value bridge
    │   ├── Loss, yield and consumption analysis
    │   └── Deterministic calculation receipts
    │
    ├── 10. Reporting and Analytical Plane
    │   ├── Financial statements and management accounts
    │   ├── Board, treasury and operational reports
    │   ├── KPI and metric registry
    │   ├── Version comparison and correction regeneration
    │   ├── Evidence drill-down
    │   └── Governed PDF / XLSX / structured export
    │
    ├── 11. Neuro-Symbolic Reasoning Plane
    │   ├── Deterministic rules and formulas
    │   ├── Ontology graph reasoning
    │   ├── ML classification, anomaly and forecasting
    │   ├── LLM explanation and semantic retrieval
    │   ├── Fact / derivation / inference separation
    │   ├── Hypothesis and missing-evidence handling
    │   └── Recommendation and refusal generation
    │
    ├── 12. Governed Agentic Runtime
    │   ├── Runtime-agent registry
    │   ├── Tool-policy matrix
    │   ├── Versioned workflow graph
    │   ├── Evidence retrieval and scope validation
    │   ├── Deterministic calculation and policy checks
    │   ├── Approval, execution and outcome state
    │   ├── Timeout, retry, failure and rollback
    │   └── Agent trace and evaluation hooks
    │
    ├── 13. Learning and Evaluation Plane
    │   ├── Analyst feedback
    │   ├── Evaluation cases and benchmarks
    │   ├── Drift and weakness detection
    │   ├── Offline replay
    │   ├── Shadow comparison
    │   ├── Governed promotion or rejection
    │   ├── Monitoring
    │   └── Rollback
    │
    └── 14. Operations, Security and Release Plane
        ├── Authentication, RBAC and tenancy
        ├── PostgreSQL migrations and backup/restore
        ├── Object storage and derived indexes
        ├── Runtime health and observability
        ├── Secrets and raw-leak controls
        ├── Release manifests and provenance
        ├── Scale, resilience and degraded-mode behavior
        └── Production and independent acceptance
```

## 2. Actual software tree in `D:\FinAI`

`D:\FinAI` is not one flat application folder. It is a Git worktree family. The
canonical product repository and shared source tree are:

```text
D:\FinAI
├── finailinear1                         ← base product worktree
│   ├── apps
│   │   └── web                           ← Next.js / TypeScript operator application
│   │       └── app
│   │           ├── g8-workspace.tsx       ← application shell
│   │           ├── executive-overview.tsx
│   │           ├── company-workspace.tsx
│   │           ├── finance-workspace.tsx
│   │           ├── data-workspace.tsx
│   │           ├── ontology-workspace.tsx
│   │           ├── operations-canvas.tsx
│   │           ├── operations-map.tsx
│   │           ├── regulation-workspace.tsx
│   │           ├── report-workflow.tsx
│   │           ├── action-workbench.tsx
│   │           ├── nyx-interaction.tsx
│   │           ├── source-*.tsx
│   │           ├── semantic-*.tsx
│   │           ├── trial-balance-*.tsx
│   │           ├── history-*.tsx
│   │           └── api/*                  ← Next.js API proxy routes
│   │
│   ├── services
│   │   └── api                           ← FastAPI / Python backend
│   │       └── src/finai_api
│   │           ├── main.py                ← composition root
│   │           ├── api/*                  ← HTTP routers
│   │           ├── domain/*               ← typed domain contracts and rules
│   │           ├── services/*             ← application/use-case services
│   │           ├── report_workflow.py
│   │           ├── transformation_workflow.py
│   │           ├── regulatory_workflow.py
│   │           └── workflow_worker.py
│   │
│   ├── services/api/migrations             ← PostgreSQL schema and authority state
│   ├── packages/contracts                   ← JSON Schema and TypeScript contracts
│   ├── packages/ontology-client             ← ontology integration client
│   ├── constructions/candidate              ← non-authoritative candidates
│   ├── docs/architecture                    ← architecture decisions
│   ├── docs/product                         ← product contracts
│   ├── scripts                              ← bootstrap, runtime and verification
│   ├── compose.yaml                         ← PostgreSQL + API + web
│   └── .finai                               ← local runtime/artifacts/cache
│
├── g8-finance-ontology-live                 ← finance/ontology branch
├── g8-petroleum-command                     ← industrial/company command branch
├── g8-retained-reporting                    ← reporting/export branch
├── g8-product-convergence                   ← metrics/product integration branch
├── g8-investigation-resolution-product      ← investigation/resolution branch
├── g8-accepted-financial-workspace          ← accepted finance workspace branch
├── g8-semantic-workspace                    ← semantic workspace branch
├── g8-ontology-import                       ← ontology import branch
├── g8-execution-recovery                    ← runtime recovery branch
├── g8-*                                     ← additional feature worktrees
├── acceptance-*                             ← acceptance snapshots
└── work/*                                   ← probes, source inspection and evidence
```

The worktrees are real implementation branches, not merely documentation. They
contain overlapping but divergent product slices. Therefore the software tree is
distributed and must be reconciled before claiming one unified release tree.

## 3. Engineering dependency tree

```text
E0. Product constitution and authority boundaries
└── E1. Platform control plane
    ├── Identity, tenant, company and period scope
    ├── Resource/version/lineage kernel
    ├── Permissions, actor provenance and refusal states
    └── PostgreSQL migration, backup and runtime foundations
        │
        └── E2. Source connectivity and immutable evidence
            ├── Connector SDK and read-only boundaries
            ├── Source manifests and capture receipts
            ├── Retained files, rows, documents and locators
            └── Evidence hashes and readback
                │
                └── E3. Transformation and semantic compilation
                    ├── Discovery and profiling
                    ├── Parsing and normalization
                    ├── Mapping candidates and approved bindings
                    ├── Versioned DAGs and exact inputs
                    ├── Data-quality and reconciliation checks
                    └── Replay, publication and rejects
                        │
                        └── E4. Business-system understanding and ontology
                            ├── Company Business Model
                            ├── Structural and semantic discovery
                            ├── Process and lifecycle graph
                            ├── Ontology proposals and impact preview
                            └── Versioned semantic publication and rollback
                                │
                                └── E5. Canonical truth
                                    ├── Canonical entities and relationships
                                    ├── Financial facts and accounting scope
                                    ├── Physical movements and inventory
                                    ├── Plans, forecasts and scenarios
                                    └── Decision/action/outcome objects
                                        │
                                        ├── E6. Financial core
                                        │   ├── Journal and ledger controls
                                        │   ├── Trial balance and reconciliation
                                        │   ├── Statements, FX and consolidation
                                        │   ├── Cash, tax, covenant and profitability
                                        │   └── Correction and regeneration
                                        │
                                        ├── E7. Industrial truth
                                        │   ├── Physical ledger
                                        │   ├── Movement and meter integrity
                                        │   ├── Loss and variance analysis
                                        │   ├── Quantity-to-value bridge
                                        │   └── Petroleum and energy reference journey
                                        │
                                        └── E8. Reporting and analytical compiler
                                            ├── KPI and metric registry
                                            ├── Deterministic report packages
                                            ├── Evidence drill-down
                                            ├── Comparison and correction views
                                            └── Governed export
                                                │
                                                └── E9. Neuro-symbolic reasoning
                                                    ├── Rules and deterministic derivations
                                                    ├── ML inference and forecasting
                                                    ├── LLM explanation
                                                    ├── Hypothesis and uncertainty
                                                    └── Refusal and missing-evidence logic
                                                        │
                                                        └── E10. Governed agent runtime
                                                            ├── Agent registry
                                                            ├── Tool policy and scope checks
                                                            ├── Workflow state machine
                                                            ├── Approval boundary
                                                            ├── Execution and readback
                                                            └── Trace, timeout, retry and rollback
                                                                │
                                                                └── E11. Learning and controlled improvement
                                                                    ├── Feedback and evaluation cases
                                                                    ├── Drift and weakness detection
                                                                    ├── Offline replay
                                                                    ├── Shadow comparison
                                                                    ├── Governed promotion
                                                                    └── Monitoring and rollback
                                                                        │
                                                                        └── E12. Production acceptance
                                                                            ├── Authentic source acceptance
                                                                            ├── Browser/operator journey
                                                                            ├── Security and tenancy tests
                                                                            ├── Restart and persistence proof
                                                                            ├── Scale and resilience proof
                                                                            ├── Independent review
                                                                            └── Release acceptance
```

## 4. Required end-to-end product journey

```text
Connect source
→ retain immutable evidence
→ inspect and validate
→ transform and map
→ build business-system model
→ propose canonical objects/facts
→ reconcile deterministic finance and industrial truth
→ approve and publish version
→ calculate/report/explain
→ investigate anomaly or decision
→ propose governed action
→ independently approve
→ execute and read back
→ compare outcome
→ export evidence package
→ feed measured result into evaluation and learning
```

## 5. Truthful status rule

The architecture is broader than the currently integrated software. Existing
worktrees demonstrate substantial implementation, but a complete G8 release still
requires branch reconciliation plus end-to-end proof across authentic sources,
canonical finance, industrial truth, agent runtime, persistence, security, scale,
learning and release acceptance.

The correct current claim is:

```text
FINANCIAL_AGI_ARCHITECTURE_UNDER_GOVERNED_IMPLEMENTATION
```

not:

```text
FULLY_DEVELOPED_AND_PROVEN_FINANCIAL_AGI
```

## 6. Verification snapshot — 2026-09-10

The canonical checkout is clean at `de44716`; the same implementation head is
published on the two converged implementation branches. The repository is not
fully merged or release-accepted:
the protected branch remains at `4261fcb`, and the latest API CI test job fails
previously failed four tests; three are fixed in `1e1ed74`, while the
database-backed object-set materialization path and the coverage threshold are
still under verification. Frontend
lint/typecheck/tests/build and API Ruff/mypy pass. The planning catalog,
scenario comparison, forecast, liquidity, scenario authoring, outcome
measurement, petroleum conservation and petroleum lineage projections plus
ORPAK/SCADA source-grain, semantic-binding and retained-series monotonicity
validation are now implemented as bounded governed projections; fully bound
rows expose governed-promotion eligibility without mutating canonical truth.
Retail cash-register shift-close intake is now a typed retained-review contract
with Z-report identity, fiscal-close state, Store/CashRegister semantic-binding
validation, evidence-linked promotion preview generation and the read-only
revenue/volume/COGS/margin bridge.
1C movement-register physical grain is now retained before journal reconciliation; the canonical checkout now exposes an accepted-resource movement-to-JournalLine reconciliation contract and operations panel with explicit match, missing, quantity-unavailable and mismatch states. Platform ontology seeds now include the operational entity and event schemas required by governed proposal validation. The unified hydration boundary accepts bounded structured JSON as well as CSV/workbooks and sends operational records through the same retained-evidence and grain-validation path.
Canonical operational publication still requires the independent review/promotion gate; proposal submission is now wired. Accepted physical measurements now have a typed telemetry-series projection with basis and gap states. The remaining decision/action planes
are not. The NYX citation/refusal boundary is implemented, but it is not
model-backed reasoning or consequential action execution. The worktree family and
distributed implementation history must therefore be treated as source
material converging into the canonical checkout, not as proof that every
architectural dimension is complete.
