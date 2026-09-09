# G8 by NYXCore — Full Dimensional Architecture

Status: `FULL TARGET MODEL / IMPLEMENTATION MAPPING REQUIRED`

This is the full working architecture for G8 by NYXCore. It is intentionally
multidimensional. A simple layer diagram is insufficient because the same
business object, number, decision or action is simultaneously governed by
domain, time, evidence, authority, identity, lifecycle, role, runtime and
release state.

`FinAI`, `FinAI / NYX Core` and `NYXCoreThinker` are internal and architectural
names for the G8 product.

## 1. Product coordinate system

```text
G8 product state
│
├── Product identity
│   ├── Financial AGI architecture
│   ├── Industrial Decision Intelligence OS
│   ├── Human-in-the-loop cognition
│   ├── Evidence-native enterprise model
│   └── Governed decision/action system
│
├── Business domains
│   ├── Enterprise / organization / legal entities
│   ├── Finance / accounting / close
│   ├── Planning / forecasting / treasury / liquidity
│   ├── Procurement / suppliers / contracts
│   ├── Sales / customers / revenue
│   ├── Inventory / warehouse / supply chain
│   ├── Manufacturing / production / consumption
│   ├── Assets / facilities / maintenance
│   ├── Petroleum / energy / movements / losses
│   ├── Workforce / responsibility / approvals
│   ├── Tax / risk / covenant / sustainability
│   ├── Regulation / compliance / external obligations
│   └── Market / economic / external intelligence
│
├── Architectural planes
│   ├── Experience
│   ├── Identity and authority
│   ├── Source connectivity
│   ├── Immutable evidence
│   ├── Transformation and interoperability
│   ├── Business-system understanding
│   ├── Ontology and semantic governance
│   ├── Canonical truth
│   ├── Financial and operational calculation
│   ├── Reporting and analytics
│   ├── Reasoning / prediction / optimization
│   ├── Decision and action
│   ├── Outcome and learning
│   └── Operations and release
│
├── Information states
│   ├── Raw source
│   ├── Retained evidence
│   ├── Parsed observation
│   ├── Validated observation
│   ├── Mapping candidate
│   ├── Approved mapping
│   ├── Derived fact
│   ├── Canonical fact
│   ├── Financial/physical ledger candidate
│   ├── Approved report value
│   ├── AI inference
│   ├── Hypothesis
│   ├── Recommendation
│   ├── Decision
│   ├── Action
│   ├── Readback
│   └── Outcome / learning candidate
│
├── Governance states
│   ├── Observed
│   ├── Derived
│   ├── Inferred
│   ├── Missing evidence
│   ├── Unavailable
│   ├── Proposed
│   ├── Reviewed
│   ├── Approved
│   ├── Published
│   ├── Certified
│   ├── Refused
│   ├── Blocked
│   ├── Superseded
│   └── Rolled back
│
├── Time dimensions
│   ├── Valid/business time
│   ├── Known/source-observation time
│   ├── Recorded/system time
│   ├── Event time
│   ├── Processing time
│   ├── Effective version time
│   ├── Correction time
│   ├── Approval time
│   ├── Execution time
│   ├── Readback time
│   ├── Outcome measurement window
│   └── Historical replay time
│
├── Scope dimensions
│   ├── Tenant
│   ├── Enterprise
│   ├── Legal entity
│   ├── Company / subsidiary
│   ├── Facility / station / warehouse / location
│   ├── Account / product / contract / movement
│   ├── Period / fiscal calendar
│   ├── Currency / unit / measurement basis
│   ├── Scenario / plan / forecast version
│   └── Actor / role / permission scope
│
├── Runtime dimensions
│   ├── Draft
│   ├── Queued
│   ├── Running
│   ├── Waiting for evidence
│   ├── Waiting for tool
│   ├── Waiting for approval
│   ├── Blocked by policy/scope
│   ├── Failed
│   ├── Timed out
│   ├── Completed
│   ├── Superseded
│   └── Rolled back
│
├── Human dimensions
│   ├── CFO / executive
│   ├── Controller / close owner
│   ├── Finance analyst
│   ├── Operations manager
│   ├── Procurement / commercial owner
│   ├── Auditor
│   ├── Ontology owner
│   ├── AI/ML governance owner
│   ├── Reviewer / checker
│   ├── Action executor
│   └── Platform/security operator
│
├── Trust-zone dimensions
│   ├── User interaction zone
│   ├── Application services zone
│   ├── AI/model zone
│   ├── Source connector zone
│   ├── Evidence/authority zone
│   ├── Action execution zone
│   └── Observability zone
│
└── Acceptance dimensions
    ├── CODE_PRESENT
    ├── LOCAL_CONTRACT_PASS
    ├── LOCAL_INTEGRATED_PASS
    ├── AUTHENTIC_SOURCE_PASS
    ├── GENERALIZATION_PASS
    ├── PRODUCTION_RUNTIME_PASS
    ├── SCALE_PASS
    └── RELEASE_ACCEPTED
```

## 2. Authority dimension

```text
Original external state
└── Source system authority
    └── Read-only connector observation
        └── Immutable retained evidence
            └── Approved mapping and policy
                └── Deterministic canonical fact
                    ├── Financial calculation
                    ├── Physical/industrial calculation
                    ├── Report and KPI value
                    └── Reconciliation result
                        └── AI reasoning / forecast / recommendation
                            └── Human decision and approval
                                └── Governed action adapter
                                    └── External execution
                                        └── Readback confirmation
                                            └── Outcome measurement
```

AI may classify, explain, investigate, forecast, simulate, recommend and propose.
AI may not silently create accounting truth, change canonical ontology, expand
permissions, alter policy or execute consequential action.

## 3. Lifecycle dimension

```text
CONNECT
  → DISCOVER
  → CAPTURE / RETAIN
  → PROFILE / VALIDATE
  → TRANSFORM
  → MAP / UNDERSTAND
  → RECONCILE
  → PROPOSE CANONICAL STATE
  → REVIEW / APPROVE
  → PUBLISH VERSION
  → CALCULATE
  → REPORT / EXPLAIN
  → INVESTIGATE
  → PREDICT / SIMULATE
  → RECOMMEND DECISION
  → APPROVE ACTION
  → EXECUTE
  → READ BACK
  → MEASURE OUTCOME
  → REGENERATE / COMPARE / EXPORT
  → EVALUATE LEARNING
  → PROMOTE OR ROLLBACK
```

## 4. Business-domain tree

```text
Enterprise business model
├── Organization
│   ├── Enterprise
│   ├── Legal entities
│   ├── Companies and subsidiaries
│   ├── Locations and facilities
│   ├── Responsibilities and actors
│   └── Ownership and effective relationships
│
├── Financial system
│   ├── Accounting scope
│   ├── Chart of accounts
│   ├── Dimensions and analytical assignments
│   ├── Journals and ledger
│   ├── Trial balance
│   ├── P&L / balance sheet / cash flow
│   ├── Consolidation / eliminations / FX
│   ├── Close / correction / restatement
│   ├── Tax / covenant / controls
│   └── Financial metrics and KPIs
│
├── Commercial system
│   ├── Customers
│   ├── Suppliers
│   ├── Products and services
│   ├── Contracts and obligations
│   ├── Orders / invoices / revenue
│   └── Procurement-to-pay / order-to-cash
│
├── Physical and industrial system
│   ├── Facilities and equipment
│   ├── Production and consumption
│   ├── Inventory and warehouses
│   ├── Movements and measurements
│   ├── Meters, tanks, stations and pipelines
│   ├── Maintenance and asset state
│   ├── Quantity/unit normalization
│   ├── Loss, yield and variance
│   └── Physical-to-financial bridge
│
├── Planning and decision system
│   ├── Budgets
│   ├── Forecasts
│   ├── Scenarios
│   ├── Liquidity and treasury
│   ├── Decision objects
│   ├── Risk and alternatives
│   └── Expected versus actual outcomes
│
└── External and control system
    ├── Regulation
    ├── Sustainability
    ├── Market intelligence
    ├── Audit evidence
    ├── Policy and controls
    └── ML/AI governance
```

## 5. Accounting and operational execution dimension

This is the execution bridge between classical accounting systems, operational
systems and G8. It prevents a narrow interpretation of "financial dimensions."
In G8, a financial dimension is not only an account attribute. It is a governed
coordinate that can bind money, goods, physical movement, contract, location,
counterparty, period, evidence, authority and correction history.

```text
1C / ERP raw execution
├── Accounting registers
│   ├── Account / chart of accounts
│   ├── Debit and credit movement
│   ├── Opening balance
│   ├── Period turnover
│   ├── Closing balance
│   ├── Subkonto 1: counterparty / entity / item
│   ├── Subkonto 2: contract / warehouse / batch
│   ├── Subkonto 3: document / shipment / order
│   └── Additional analytics: department / region / budget article / project
│
├── Accumulation and operational registers
│   ├── Inventory balance and turnover
│   ├── Goods movement
│   ├── Stock count / tank dip / station shift report
│   ├── Retail sales / POS receipts
│   ├── Cost calculation and overhead allocation
│   ├── Customer and supplier settlements
│   ├── VAT purchase/sales books
│   └── Fixed assets / depreciation / CAPEX registers
│
├── Source documents
│   ├── Receipt of goods/services
│   ├── Sales realization
│   ├── Transfer / movement document
│   ├── Waybill / transport note
│   ├── Bank payment order
│   ├── Reconciliation act
│   ├── Expense allocation
│   └── Inventory / stock-count document
│
└── G8 retained observation
    ├── SourceTrialBalanceRow
    ├── SourceJournalLine
    ├── SourceRegisterMovement
    ├── SourceInventoryBalanceRow
    ├── SourceGoodsMovementRow
    ├── SourceSalesRow
    ├── SourceCostLayerRow
    ├── SourceSettlementRow
    ├── SourceTaxRow
    └── SourceAssetRow
```

SAP/ERP-style accounting execution and G8 execution differ by authority:

```text
Classical SAP / ERP authority
├── Owns native posting lifecycle
├── Enforces double-entry controls
├── Stores official accounting documents
├── Owns statutory ledger state
├── Produces trial balances and subledger reports
└── Treats operational detail as module/subledger input

G8 / Enterprise Operating System authority
├── Does not silently replace ERP posting authority
├── Retains immutable source observations
├── Builds source-to-ontology mappings
├── Reconciles ledger, subledger and physical operations
├── Preserves valid_at / known_at / recorded_at corrections
├── Creates deterministic canonical facts from approved evidence
├── Explains every number through lineage and governing policy
├── Detects missing, contradictory or late source evidence
├── Simulates and recommends decisions
└── Executes only approved actions through governed adapters
```

The dimensional subsystems are:

```text
Financial and operational subsystems
├── 1. General ledger and trial balance
│   ├── 1C source: ОСВ / ОСВ по счету
│   ├── G8 object: SourceTrialBalanceRow / LedgerBalance
│   ├── Authority: ERP accounting truth until retained and approved
│   └── Control: debit/credit equality, account scope, period, currency
│
├── 2. Inventory and stock telemetry
│   ├── 1C source: Ведомость по товарам на складах / Остатки и обороты
│   ├── Documents: stock count, tank dip, station shift report
│   ├── G8 object: InventoryBalance / PhysicalMeasurement / TankState
│   ├── Control: opening + receipts - dispatches - losses = closing
│   └── Bridge: physical quantity to financial valuation and margin
│
├── 3. Logistics, supply chain and terminal dispatch
│   ├── 1C source: Ведомость движения товаров
│   ├── Documents: intake receipt, waybill, transfer, dispatch
│   ├── G8 object: Movement / Shipment / Route / Carrier / LineagePath
│   ├── Control: source-destination conservation and document continuity
│   └── Graph: terminal intake to truck to depot/station to final sale
│
├── 4. Station sales and retail revenue
│   ├── 1C source: Отчет о розничных продажах / ЧекККМ
│   ├── G8 object: RetailSale / PaymentSplit / ProductVolume / Shift
│   ├── Control: sold volume reduces inventory and recognizes revenue
│   └── Bridge: product, station, cashier, payment type, loyalty/fuel card
│
├── 5. Product cost and COGS
│   ├── 1C source: Себестоимость товаров / Расчет себестоимости
│   ├── Documents: freight, excise, customs, overhead allocation
│   ├── G8 object: CostLayer / CostAllocation / MarginBridge
│   ├── Control: cost method, allocation basis, tax/freight separation
│   └── Bridge: price -> volume -> mix -> cost -> margin
│
├── 6. Customer receivables and treasury exposure
│   ├── 1C source: Ведомость взаиморасчетов / задолженность покупателей
│   ├── Documents: reconciliation act, bank payment order
│   ├── G8 object: CounterpartyExposure / ARAging / CashCollection
│   ├── Control: invoice-payment-document binding and aging buckets
│   └── Bridge: credit risk, liquidity and working-capital impact
│
├── 7. Specialized subledgers and enterprise variations
│   ├── Fixed assets and CAPEX
│   ├── VAT purchase/sales books
│   ├── Intercompany reconciliation and eliminations
│   ├── FX remeasurement and translation
│   ├── Tax and statutory reporting
│   └── Covenant, risk and compliance overlays
│
└── 8. External market and planning context
    ├── Price indexes / FX / rates / benchmarks
    ├── Forecast drivers
    ├── Scenario assumptions
    ├── Read-only intelligence inputs
    └── Non-authoritative for accounting truth unless separately approved
```

The G8 ontology mapping converts raw accounting and operational dimensions into
governed business coordinates:

```text
Raw dimensional row
├── account_code
├── subkonto_1
├── subkonto_2
├── subkonto_3
├── document_ref
├── warehouse_or_tank
├── product_or_nomenclature
├── counterparty
├── contract
├── quantity
├── unit
├── amount
├── currency
├── period
├── valid_at
├── known_at
└── source_row_hash

Governed ontology object
├── LegalEntity
├── Account
├── Counterparty
├── Contract
├── Product
├── Facility / Warehouse / Tank / Station
├── Movement
├── Document
├── LedgerLine
├── InventoryState
├── CostLayer
├── TaxPosition
├── Payment / Settlement
├── ReportMetric
└── DecisionImpact
```

The bitemporal/kinetic layer is mandatory:

```text
Operational event
├── valid_at: when the business event actually happened
├── known_at: when the source system or enterprise knew it
├── recorded_at: when G8 retained the evidence
├── approved_at: when a mapping/fact/report/action became authorized
├── corrected_at: when a later correction arrived
└── replay_as_of: which historical state is being reproduced
```

Therefore an August inventory receipt corrected in September does not rewrite
August history. G8 must be able to answer both:

```text
What did we believe on August close date?
What is the corrected August truth after September evidence?
```

This is the core distinction between a report/dashboard and an enterprise
operating system: G8 maintains the changing knowledge state, the original
evidence state, the approved financial state and the operational reality state
as related but separately governed dimensions.

## 6. Data, object and graph dimension

```text
Canonical object graph
├── Identity graph
│   └── tenant → enterprise → company → entity → location → actor
├── Source graph
│   └── connector → manifest → snapshot → file/document → sheet/page → row/field
├── Semantic graph
│   └── source field → mapping → ontology object → relation → business model
├── Financial graph
│   └── account → journal line → ledger → trial balance → statement → KPI
├── Industrial graph
│   └── facility → asset → movement → measurement → inventory → loss → valuation
├── Temporal graph
│   └── valid version → known version → recorded event → correction → supersession
├── Reasoning graph
│   └── fact → derivation → rule → inference → hypothesis → missing evidence
├── Decision graph
│   └── problem → alternatives → impact → recommendation → approval → action
├── Outcome graph
│   └── execution → readback → expected result → actual result → evaluation
└── Learning graph
    └── feedback → evaluation case → candidate → replay → shadow → promotion/rollback
```

## 7. Platform and deployment dimension

```text
Deployment topology
├── Experience
│   └── Web application / operator shell
├── Application
│   ├── API services
│   ├── Domain services
│   ├── Query and projection services
│   └── Report/export services
├── Workflow
│   ├── Durable workflow workers
│   ├── Transformation workers
│   ├── Regulatory workers
│   ├── Agent/runtime workers
│   └── Action workers
├── Authority storage
│   ├── PostgreSQL transactional state
│   ├── Immutable object storage
│   ├── Append-only event records
│   └── Backup / point-in-time recovery
├── Derived retrieval
│   ├── Search index
│   ├── Vector index
│   └── Graph projections
├── Integration
│   ├── Connector workers
│   ├── Queue/event transport
│   ├── Model gateway
│   └── External action adapters
└── Operations
    ├── Logs / metrics / traces
    ├── Health and readiness
    ├── Drift and quality monitoring
    ├── Incident evidence
    └── Release and recovery control
```

Supported deployment forms are local controlled installation, on-premises,
private cloud, hybrid and restricted/disconnected environments.

## 8. Contract and event dimension

Every material contract carries:

```text
tenant_id
company_id
entity_id
actor_id
source_id
run_id
correlation_id
causation_id
schema_version
created_at
content_hash
valid_at
known_at
```

Core events:

```text
SourceConnected
MetadataCaptured
SourceSnapshotRetained
SchemaChangeDetected
UnderstandingProposed
MappingReviewed
MappingApproved
CanonicalFactsPromoted
CalculationCompleted
ReconciliationFailed
ReportGenerated
ReportApproved
ForecastProduced
DecisionProposed
ActionApproved
ActionExecuted
ActionReadbackVerified
OutcomeMeasured
LearningCandidateEvaluated
```

Consumers must be idempotent and replay-tolerant.

## 9. Intelligence and agent dimension

```text
Reasoning system
├── Symbolic reasoning
│   ├── Accounting equations
│   ├── Debit/credit controls
│   ├── Financial and physical rules
│   ├── Materiality and approval policies
│   └── Ontology constraints
├── Deterministic computation
│   ├── Decimal calculations
│   ├── Reconciliation
│   ├── Aggregation
│   ├── Valuation
│   └── Report compilation
├── ML services
│   ├── Anomaly detection
│   ├── Classification
│   ├── Entity matching
│   ├── Forecasting
│   ├── Ranking
│   └── Drift detection
├── LLM services
│   ├── Explanation
│   ├── Investigation dialogue
│   ├── Semantic candidate generation
│   ├── Hypothesis formation
│   └── Narrative generation
└── Governed runtime agents
    ├── Executive orchestrator
    ├── Evidence/source agent
    ├── Transformation agent
    ├── Semantic mapping agent
    ├── Accounting compiler agent
    ├── Reconciliation/integrity agent
    ├── Industrial operations agent
    ├── Ontology reasoning agent
    ├── Forecast/scenario agent
    ├── Causal narrative agent
    ├── Governance policy agent
    ├── Learning/evaluation agent
    └── Evidence packaging agent
```

Every agent has a declared role, tools, scope, evidence access, mutation
permissions, approval boundary, timeout, retry behavior, failure state,
evaluation hooks and rollback boundary.

## 10. Experience and interaction dimension

```text
Persistent governed shell
├── Governed context bar
│   └── company / period / package / dataset / version / role / authority
├── Status strip
│   └── freshness / completeness / confidence / reconciliation / blockers
├── Evidence drawer
├── Transformation drawer
├── Mapping drawer
├── Reasoning trace
├── Action drawer
├── Approval drawer
├── Comparison shell
├── Lineage graph
├── Ontology graph
├── Agent flow graph
├── Evaluation panel
├── Drift panel
├── Outcome timeline
├── Learning candidate review
└── Refusal state panel
```

Primary interaction patterns:

```text
Table-first  → ledgers, source review, mappings, evidence, queues, evaluations
Graph-first   → ontology, lineage, dependencies, impact, agent flows
Timeline-first→ close, actions, corrections, publication, rollback, traces
Bridge-first  → quantity/value, margin, variance, original/corrected, baseline/shadow
```

## 11. Software and repository dimension

```text
D:\FinAI
├── finailinear1
│   ├── apps/web                         ← experience plane
│   ├── services/api                     ← API + domain/application planes
│   │   ├── api                           ← route/adapters
│   │   ├── domain                        ← contracts/rules
│   │   ├── services                      ← use cases
│   │   ├── workflows                     ← durable orchestration
│   │   └── migrations                    ← authority persistence
│   ├── packages/contracts                ← cross-language contracts
│   ├── packages/ontology-client          ← ontology integration
│   ├── constructions/candidate           ← candidate state
│   ├── docs                              ← architecture/product evidence
│   ├── scripts                           ← bootstrap/runtime/verification
│   └── .finai                            ← local state/artifacts
├── g8-finance-ontology-live              ← finance/ontology implementation
├── g8-petroleum-command                  ← industrial/company implementation
├── g8-retained-reporting                 ← report/export implementation
├── g8-product-convergence                ← metrics/product integration
├── g8-investigation-resolution-product   ← investigation implementation
├── g8-accepted-financial-workspace       ← finance workspace implementation
├── g8-semantic-workspace                 ← semantic workspace implementation
├── g8-ontology-import                    ← ontology import implementation
├── g8-execution-recovery                 ← runtime recovery implementation
├── acceptance-*                          ← acceptance snapshots
└── work/*                                ← probes and evidence artifacts
```

## 12. Engineering dependency dimension

```text
P0  Constitution, authority and scope
 ↓
P1  Identity, tenancy, versions, lineage, migrations and security
 ↓
P2  Source connectors, manifests, retained evidence and readback
 ↓
P3  Universal transformation, mappings, quality, rejects and replay
 ↓
P4  Business-system understanding and ontology governance
 ↓
P5  Canonical finance and industrial truth
 ↓
P6  Deterministic calculation, reconciliation and report compiler
 ↓
P7  Investigation, explanation, forecasting, simulation and optimization
 ↓
P8  Decisions, approval, action gateway and external readback
 ↓
P9  Outcome measurement and governed learning
 ↓
P10 Production convergence: resilience, recovery, security, scale
 ↓
P11 Independent acceptance: authentic source, generalization and release
```

## 13. Test and evidence dimension

```text
Test architecture
├── Unit and deterministic calculation tests
├── API/schema contract tests
├── Database integration tests
├── Connector certification tests
├── Cross-tenant security tests
├── Accounting golden/property tests
├── Workflow/idempotency tests
├── Authenticated browser journeys
├── Backup/restoration tests
├── Failure-injection tests
├── Load/endurance tests
├── Model evaluation/drift tests
├── Unseen-source generalization tests
└── Reproducible release tests
```

```text
Evidence gates are independent:
CODE_PRESENT
→ LOCAL_CONTRACT_PASS
→ LOCAL_INTEGRATED_PASS
→ AUTHENTIC_SOURCE_PASS
→ GENERALIZATION_PASS
→ PRODUCTION_RUNTIME_PASS
→ SCALE_PASS
→ RELEASE_ACCEPTED
```

## 14. Complete acceptance journey

```text
New read-only source
→ metadata discovery
→ immutable capture
→ transformation preview/build
→ quality tests/rejects/field lineage
→ business-model proposal
→ mapping review
→ checker approval
→ canonical facts
→ journal/ledger reconciliation
→ financial report
→ operational/financial drill-down
→ natural-language investigation
→ forecast and uncertainty
→ scenario comparison
→ decision recommendation
→ maker/checker approval
→ governed action or simulation
→ external readback
→ outcome measurement
→ learning evaluation
→ corrected report regeneration
→ immutable export
→ restart persistence
→ backup restoration
→ tenant/security verification
→ load/release reproducibility
```

## 15. Current implementation boundary

The repositories contain meaningful implementations across these dimensions,
distributed among multiple worktrees. The architecture is broader than the
currently unified and independently accepted product. The correct status remains:

```text
FINANCIAL_AGI_ARCHITECTURE_UNDER_GOVERNED_IMPLEMENTATION
```

The final product claim requires the dimensions to converge in one reproducible
release candidate and pass the independent evidence gates. A green unit test,
local service, bounded browser slice or feature worktree does not by itself prove
authentic-source, generalization, production-runtime, scale or release acceptance.

### Verification snapshot — 2026-09-10

The latest implementation head is `86a93a3` on PR #9. Frontend lint,
typecheck, tests and build pass; API Ruff and mypy pass. The GitHub API test job
previously failed four tests. The packaging, cross-actor investigation action,
and investigation-resolution replay failures are fixed locally in `1e1ed74`;
the native object-set materialization path is still being verified by the
current GitHub run. The accepted ScenarioVersion/PlanningCellFact catalog and
deterministic exact-scope scenario comparison are now wired through
`/v1/ontology/planning` and the frontend Planning workspace; forecast
calculation, scenario authoring, liquidity projection and outcome measurement
are wired as bounded canonical projections. A read-only petroleum conservation
bridge is now mounted at `/v1/operations/petroleum/reconciliation`; retained
ORPAK/SCADA intake, full movement lineage and operational telemetry remain open.
A citation-first NYX refusal/explanation boundary is now wired at
`/v1/ontology/nyx/reason`; model-backed reasoning, multi-citation packets and
proposal handoff execution remain open. The previous configured coverage result was 83.93% against
a 90% gate. The protected
`development/enterprise-hydration-foundation` branch remains at `4261fcb`, so
this head is not the canonical merged release. This is a substantial converged
slice, not completion of the full architecture.
