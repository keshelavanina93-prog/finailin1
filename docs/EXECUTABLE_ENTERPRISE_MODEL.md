# G8 by NYXCore — Executable Enterprise Model

Status: implementation target and contract for the canonical checkout

This document defines the shared computational ontology required for G8 to
answer not only what exists in an enterprise, but what can be calculated,
certified, forecast, explained, reconciled, approved, executed, and measured.
It extends the three G8 architecture documents. It does not replace the
authority boundary: a function may calculate a candidate without making that
candidate an approved accounting fact or an executed business effect.

## 1. Purpose

The canonical graph contains nouns such as `Account`, `Company`, `Asset`,
`Inventory`, `Currency`, `Product`, `Station`, and `Loan`. Those nouns are
necessary but insufficient. G8 also needs governed verbs:

```text
TranslateCurrency       EliminateIntercompany       CalculateDepreciation
CapitalizeAsset         DisposeAsset                RevalueFX
CalculateInterest       CalculateTax                AllocatePayroll
RollForwardReceivables  CalculateInventoryValuation CalculateGrossMargin
ForecastLiquidity       ConsolidateGroup            ReconcilePhysicalStock
MeasureDecisionOutcome  GenerateReport              ExplainVariance
```

An executable enterprise model is the combination of:

```text
NOUNS + VERBS + DEPENDENCY RULES + EVIDENCE + AUTHORITY + TIME + OUTCOME
```

The model must support the same target from a report, metric, scenario,
forecast, NYX question, investigation, certification request, or action.

## 2. Non-negotiable invariants

1. A schema, object, or source row is not an executable engine.
2. A function cannot consume an input outside its exact authorized tenant and
   business scope.
3. Missing data is never silently converted to zero, an inferred dimension,
   or an invented allocation.
4. Every executable definition and result is versioned and content-addressed.
5. `valid_at` describes the business state; `known_at` describes when G8 knew
   it. Later corrections append evidence and never rewrite the original fact.
6. Observed, derived, approved, certified, AI-inferred, and action-authorized
   states remain distinct.
7. Deterministic financial calculations do not depend on an LLM.
8. AI may explain a resolver result, form a hypothesis, or recommend an
   action; it cannot promote a function, alter policy, post accounting truth,
   or execute a consequential effect without the required authority.
9. A function result is reproducible from exact input pins, function version,
   policy pins, scope, time cutoffs, and calculation configuration.
10. A failed, partial, refused, or incomparable result is retained with its
    reason and missing dependency set; it is not represented as success.

## 3. First-class ontology resources

### 3.1 `ExecutableFunctionDefinition`

The current `FunctionDefinition` remains the execution resource for installed
adapters. The executable enterprise model adds the domain contract fields below
to the function definition or to a versioned companion resource referenced by
it. No private module-specific function registry is permitted.

```text
ExecutableFunctionDefinition
├── function_id
├── function_version
├── display_name
├── domain
├── verb
├── implementation_id
├── input_requirements[]
├── output_contracts[]
├── required_dimensions[]
├── optional_dimensions[]
├── required_policies[]
├── required_evidence_classes[]
├── alternative_input_groups[]
├── applicability_rules[]
├── temporal_rules
├── authority_requirements
├── determinism_class
├── calculation_method
├── failure_states[]
├── lineage_contract
├── code_sha256
├── dependency_sha256
├── schema_version
└── authority_state
```

`implementation_id` identifies an allowlisted server implementation. It never
means caller-supplied code. `code_sha256` and `dependency_sha256` bind the
runtime implementation to the retained execution plan.

### 3.2 `DependencyRequirement`

```text
DependencyRequirement
├── requirement_id
├── label
├── kind: FACT | FUNCTION | DIMENSION | POLICY | EVIDENCE | RATE_SET | APPROVAL
├── object_types[]
├── required_fields[]
├── required_dimensions[]
├── grain
├── unit
├── currency
├── time_rule
├── authority_rule
├── freshness_rule
├── alternative_group
├── condition
├── cardinality
├── guidance
└── evidence_contract
```

Requirements are evaluated with explicit boolean composition:

```text
ALL_OF       every child must be satisfied
ANY_OF       one or more valid alternatives must be satisfied
ONE_OF       exactly one alternative must be selected
OPTIONAL     absence is allowed and is recorded as not applicable
CONDITIONAL  applies only when its predicate is true
```

An alternative path is not a fallback that hides missing data. The resolver
retains the selected path, rejected alternatives, and the reason each path was
or was not eligible.

### 3.3 `PlanningSnapshot`

Scenario and baseline are separate concepts. Scenario describes the kind of
state; baseline identifies the exact state used for comparison.

```text
PlanningSnapshot
├── snapshot_id
├── scenario_type: ACTUAL | BUDGET | FORECAST | TARGET | LONG_TERM |
│                  OPERATIONAL | WHAT_IF | STRESS | PREDICTION |
│                  DECISION_CASE | CORRECTED_ACTUAL
├── scenario_id
├── version_id
├── forecast_vintage
├── forecast_horizon
├── company_scope
├── applicable_dimensions[]
├── fiscal_period
├── horizon
├── cutover_date
├── currency
├── unit
├── valid_at
├── known_at
├── approved_at
├── model_version
├── assumption_set_id
├── evidence_set_id
├── source_pins[]
└── authority_state
```

Snapshots are immutable. “Latest forecast” is a resolver-selected label over
versioned snapshots, never a mutable column that destroys prior vintages.

### 3.4 `BaselineReference` and `ComparisonSet`

```text
BaselineReference
├── baseline_id
├── snapshot_id
├── baseline_type
├── comparison_purpose
├── hierarchy_priority
├── horizon_at_prediction
└── locked_at

ComparisonSet
├── comparison_set_id
├── observed_snapshot_id
├── baseline_refs[]
├── alignment_policy
├── time_mode
├── materiality_policy_id
└── reproducibility_hash
```

Supported baseline types include original/latest budget, prior/latest
forecast, forecast at horizon, prior year/period actual, target, machine
prediction, scenario, decision expectation, original close actual, and
corrected actual.

### 3.5 `OutcomeMeasurement` and `OutcomeComparison`

```text
OutcomeMeasurement
├── outcome_id
├── subject: metric + exact scope + period
├── observation: actual snapshot + value + authority + evidence
├── comparisons[]
├── materiality
├── diagnosis
├── decision_links[]
├── action_links[]
├── forecast_evaluations[]
├── explanation_state
├── review_state
└── learning_state

OutcomeComparison
├── comparison_id
├── baseline_snapshot_id
├── baseline_value
├── actual_value
├── absolute_variance
├── percentage_variance
├── favorable_unfavorable
├── materiality
├── alignment_result
├── decomposition_id
├── explanation_id
└── confidence_and_completeness
```

## 4. Executable edge taxonomy

Edges are directed, version-pinned, scope-checked, and retained as lineage.

```text
REQUIRES_FUNCTION       target requires a function version
REQUIRES_FACT           function requires an observed/derived fact
REQUIRES_DIMENSION      function requires a bound identity or dimension member
REQUIRES_POLICY         function requires an approved policy version
REQUIRES_RATE_SET       function requires an approved rate set
REQUIRES_EVIDENCE       function requires a retained evidence class
REQUIRES_APPROVAL       function requires an authority decision
PRODUCES_FACT           function output is a derived candidate or fact
DERIVES_FROM            output preserves exact input lineage
ROLLS_FORWARD           period state carries into a later period
ALLOCATES_FROM          output uses an explicit approved allocation rule
TRANSLATES_FROM         currency or unit translation edge
ELIMINATES              intercompany or duplicate elimination edge
RECONCILES_WITH         deterministic reconciliation edge
MEASURES                outcome measures an action/decision expectation
INVALIDATED_BY          later evidence or policy invalidates a result
```

An ordinary object relationship is not automatically an executable
dependency. A `Company` edge to a `Currency` does not prove that a closing FX
rate or translation policy exists.

## 5. Universal dependency resolver

The resolver accepts any governed target:

```text
resolve(target_pin, exact_scope, valid_at, known_at, purpose, policy)
```

It returns a retained `DependencyResolution` containing:

```text
DependencyResolution
├── resolution_id
├── target_pin
├── function_pin
├── exact_scope
├── valid_at / known_at
├── state
├── selected_paths[]
├── rejected_paths[]
├── nodes[]
├── edges[]
├── missing[]
├── incompatible[]
├── stale[]
├── authority_refusals[]
├── reproducibility_hash
└── next_actions[]
```

### 5.1 Resolution algorithm

1. Resolve the target to an authorized exact version at the requested
   `known_at` cutoff. Hidden resources are reported only as unavailable; their
   identifiers are never leaked.
2. Resolve the applicable function version and verify its implementation
   manifest, code hash, dependency hash, and authority state.
3. Evaluate predicates and construct the requirement graph. Conditional
   requirements that do not apply are retained as `NOT_APPLICABLE`.
4. Recursively resolve function, fact, dimension, policy, rate, evidence, and
   approval requirements.
5. For each candidate, verify tenant/company/entity scope, authority, evidence
   chain, valid time, known time, freshness, unit, currency, and grain.
6. Evaluate alternative groups. Rank eligible alternatives using the declared
   hierarchy; never rank by an LLM or by an implicit “latest” shortcut.
7. Detect cycles with a bounded depth and node/edge budget. A cycle or budget
   overflow is `STALE_OR_INCOMPATIBLE`, not partial success.
8. Calculate the minimum missing set and the first actionable remediation for
   each blocked path.
9. Return one of the states below and persist the exact resolution packet.

### 5.2 Resolution states

```text
READY
SATISFIED_BY_AGGREGATION
SATISFIED_BY_APPROVED_ALLOCATION
PARTIAL
MISSING
INCOMPATIBLE_GRAIN
INCOMPATIBLE_TIME
UNAPPROVED
STALE
NOT_APPLICABLE
INCOMPARABLE
BLOCKED
REFUSED
```

`READY` means the function may execute within its authority boundary. It does
not mean the output is certified or posted. `REFUSED` means the requested
operation itself is outside authority; `BLOCKED` means it could become valid
after a missing dependency or approval is supplied.

## 6. Grain and sparse dimensional alignment

Facts need only the dimensions applicable to their declared contract. They may
not be silently expanded to the maximum enterprise grain.

```text
GrainAlignmentContract
├── left_snapshot
├── right_snapshot
├── shared_dimensions[]
├── left_extra_dimensions[]
├── right_extra_dimensions[]
├── aggregation_rules[]
├── allocation_rules[]
├── unit_conversion
├── currency_conversion
├── temporal_alignment
├── comparability_status
└── lineage
```

Allowed alignment results are `EXACT`, `AGGREGATED`,
`APPROVED_ALLOCATION`, `TEMPORALLY_ALIGNED`, `PARTIAL`, and `INCOMPARABLE`.

Example: actual `Company × Station × Product × Day` and budget `Company ×
Region × Product × Month` may compare only after deterministic aggregation of
actuals to `Company × Region × Product × Month`. G8 must not manufacture
station budgets.

## 7. Time, cutover, and authority semantics

Every comparison and resolution carries:

```text
valid_at       business-effective state
known_at       knowledge cutoff used by the resolver
recorded_at    retention timestamp
approved_at    authority timestamp, when applicable
corrected_at   later correction timestamp, when applicable
replay_as_of   explicit historical replay cutoff
cutover_date   actual/forecast switchover, when applicable
```

Forecast evaluation uses the forecast’s vintage and horizon. A forecast made
90 days before a target is not evaluated as if it were made seven days before
the target. Original close actual and corrected actual remain separately
addressable.

Authority eligibility is evaluated in this order:

```text
RAW_SOURCE
→ RETAINED_EVIDENCE
→ PARSED_OBSERVATION
→ VALIDATED_OBSERVATION
→ MAPPING_CANDIDATE
→ APPROVED_MAPPING
→ DERIVED_CANDIDATE
→ APPROVED_CANONICAL
→ CERTIFIED_REPORT_VALUE
```

AI inference and action states are separate overlays. A physical variance or
planning candidate cannot mutate accounting truth merely because a function
returned a number.

## 8. Domain verb packs

Each domain registers function definitions through the shared ontology and
resolver.

### Consolidation

```text
MapToGroupCOA
MatchIntercompany
EliminateIntercompany
TranslateCurrency
CalculateCTA
ApplyOwnershipMethod
ConsolidateStatement
```

`ConsolidateStatement` requires company statements, group COA mapping,
intercompany matching/elimination, ownership policy, closing and average rate
sets where applicable, and an approved consolidation policy. A missing EUR
closing rate or unmapped counterparty blocks certification with a precise
remediation, rather than producing a partial statement as complete.

### Fixed assets

```text
CapitalizeAsset  CalculateDepreciation  ImpairAsset
TransferAsset    DisposeAsset            RollForwardPPE
```

The function graph requires asset identity, class, useful life, method,
location, cost center, in-service date, and approved capitalization policy.

### Treasury and FX

```text
RemeasureMonetaryItems  CalculateRealizedFX  CalculateUnrealizedFX
TranslateFinancialStatement  ForecastCash    CalculateInterest
```

Rate sets, instrument terms, currency classification, bank/loan identity, and
approved treasury policy are explicit dependencies.

### Tax and payroll

```text
CalculateVAT  CalculateCurrentTax  CalculateDeferredTax
ReconcileTaxLedger  PrepareReturn

CalculateGrossPay  CalculateEmployerCost  AllocateLabor
AccrueBonus       CalculateLeaveProvision
```

Jurisdiction, tax code, period, source evidence, rate/policy versions, worker
identity, time records, salary basis, and allocation rules are not inferred.

### Industrial and petroleum operations

```text
ReconcilePhysicalStock  CalculateInventoryValuation
CalculateGrossMargin    ReconcileMovementToSale
MeasureDecisionOutcome
```

The physical evidence set may include inventory balances, movements, receipts,
dispatches, tank dips, meter/dispenser readings, station shifts, POS sales,
waybills, stock counts, density/temperature, quality measurements, and gas
telemetry. No single evidence type is treated as the whole physical authority.

## 9. Planning, outcome, and forecast intelligence

The planning engine must support:

1. Immutable scenario/version/vintage snapshots.
2. Multi-baseline comparison sets.
3. Sparse grain alignment and explicit aggregation/allocation lineage.
4. Actual/forecast cutover and rolling reforecast logic.
5. Deterministic price, volume, mix, FX, cost, freight, tax, timing, physical
   loss, and residual decomposition where applicable.
6. Metric-aware favorability, materiality, zero-baseline, sign, and rounding
   policies.
7. Forecast horizon, accuracy, bias, tolerance, and confidence-range results.
8. Deterministic sensitivity runs over the same calculation graph.
9. Forecast revision bridges from prior vintage to current vintage.
10. Decision expectations linked to approved scenarios and measured decision
    outcomes linked to readback evidence.

### Deterministic decomposition

```text
sum(driver_effects) + residual = absolute_variance
```

The equality is checked with exact Decimal arithmetic under a declared
rounding policy. A residual is visible and classified; it is not silently
discarded.

### Three explainability layers

```text
Layer 1  deterministic decomposition and alignment artifacts
Layer 2  model version, inputs, trend/seasonality, confidence and accuracy
Layer 3  citation-grounded NYX explanation or hypothesis
```

NYX receives the retained resolution/result packet and may explain it. It may
not replace layer 1 or layer 2 with narrative.

## 10. Persistence and invalidation

The current PostgreSQL resource/version and dependency tables remain the
canonical persistence boundary. The implementation must retain, in the same
tenant-scoped transaction:

```text
executable_function_versions
dependency_requirements
dependency_edges
planning_snapshots
baseline_references
comparison_sets
dependency_resolutions
outcome_measurements
forecast_evaluations
sensitivity_runs
```

If a new retained evidence item, policy version, source correction, or
function build changes eligibility, G8 appends an invalidation/recalculation
event keyed by the affected exact version pins. It does not rewrite the old
resolution or result. Recalculation is bounded, idempotent, and replayable.

## 11. API contract

All consumers use typed contracts through the Next proxy to FastAPI. The
minimum shared endpoints are:

```text
POST /v1/ontology/executable/resolve
GET  /v1/ontology/executable/resolutions/{resolution_id}
GET  /v1/ontology/executable/functions
POST /v1/ontology/planning/snapshots
POST /v1/ontology/planning/comparison-sets
POST /v1/ontology/planning/outcomes/measure
POST /v1/ontology/planning/sensitivity-runs
GET  /v1/ontology/planning/forecast-evaluations
```

Every response includes exact scope, time cutoffs, authority state, status,
selected/rejected paths, missing dependencies, evidence pins, and a
reproducibility hash. A response that cannot establish those fields is not a
successful executable-model response.

## 12. Frontend UX

The universal resolver is exposed consistently from:

```text
Report / KPI / Metric / Forecast / Scenario / NYX question / Investigation / Action
                                  ↓
                         “What is required?”
                                  ↓
                         Resolver result drawer
```

The drawer has four layers:

1. Business answer: ready, blocked, partial, refused, or incomparable.
2. Missing/failed requirements in business language.
3. Exact scope, grain, time, authority, evidence, and selected alternative
   path.
4. Technical lineage and reproducibility metadata under progressive
   disclosure.

Example:

```text
ROIC cannot yet be calculated authoritatively.
EBIT is approved and Invested Capital is available at the selected scope.
Missing: approved effective-tax function for 2025-04.
Available alternative: pre-tax return metric, clearly labeled non-ROIC.
Accounting impact: none. Action: none permitted.
```

## 13. State machines

### Function lifecycle

```text
DRAFT → VALIDATED → REVIEW_REQUIRED → APPROVED → INSTALLED → RETIRED
```

### Resolution lifecycle

```text
REQUESTED → RESOLVING → READY | PARTIAL | BLOCKED | REFUSED | INCOMPARABLE
```

### Result lifecycle

```text
DERIVED_CANDIDATE → REVIEW_REQUIRED → APPROVED_CANONICAL → CERTIFIED
```

### Decision/outcome lifecycle

```text
RECOMMENDED → ELIGIBILITY_CHECKED → MAKER_APPROVED → CHECKER_APPROVED
→ QUEUED → EXECUTING → EXECUTED → READBACK_VERIFIED → OUTCOME_MEASURED
```

Every state appears in backend responses, typed frontend contracts, UI
rendering, and negative-path tests.

## 14. Migration from the current implementation

The current checkout already provides reusable foundations:

```text
domain/function_execution.py          installed FunctionDefinition/runtime pins
services/function_execution.py       bounded deterministic execution
services/enterprise_diagnostics.py   exact dependency traversal and cycle checks
services/derived_property_graph.py   bounded dependency validation
services/finance_execution.py        fact/grain/time/currency preflight
services/operational_source_validation.py
                                      source grain and evidence validation
services/petroleum_reconciliation.py physical conservation and bridge
services/retained_analyses.py         retained result references
```

The convergence sequence is:

1. Define typed executable-model resources and requirement composition.
2. Adapt existing `FunctionDefinition` metadata into the shared registry.
3. Extract grain, time, authority, evidence, and alternative-path checks into
   one resolver service; retain existing domain checks as adapters during
   migration.
4. Add persistence and exact-scope API/proxy contracts.
5. Replace planning-specific actual/plan preflight with the universal resolver
   and multi-baseline comparison engine.
6. Connect reporting, NYX, certification, operations, decisions, and outcomes
   to the same resolver packet.
7. Add browser and restart proof for the complete target-to-outcome journey.

No migration step may weaken current accounting authority, source retention,
or refusal behavior.

## 15. Acceptance requirements

### Contract and deterministic tests

- function versions reject missing implementation hashes and unsupported code;
- `ALL_OF`, `ANY_OF`, `ONE_OF`, `OPTIONAL`, and `CONDITIONAL` resolve correctly;
- cycles, duplicate dependencies, conflicting versions, and bounds refuse;
- wrong tenant/company/entity scope refuses;
- incompatible grain/time/unit/currency are explicit states;
- approved allocation and aggregation retain exact lineage;
- missing evidence is not zero;
- original and corrected actual snapshots coexist;
- forecast vintages and horizons remain independently evaluable;
- decomposition sums to variance under the declared Decimal policy;
- favorability and materiality follow metric policy;
- sensitivity uses the same function/version graph;
- a physical result cannot mutate accounting truth;
- an unapproved action cannot execute;
- a missing readback prevents outcome completion;
- repeated resolution is idempotent and reproducible.

### Integration and UI tests

- report, metric, scenario, forecast, NYX, investigation, certification, and
  action targets return the same resolver contract;
- proxy allowlists match every FastAPI endpoint;
- selected context is preserved across resolver, evidence, lineage, and action
  panes;
- UI renders ready, partial, blocked, refused, stale, incomparable, and
  unavailable states;
- business language appears before technical hashes and raw JSON;
- restart preserves resolution, result, decision, readback, and outcome state;
- authenticated browser proof demonstrates target → dependencies → variance →
  explanation → scenario → decision → action → readback → outcome.

### Evidence gates

Keep these claims separate:

```text
CODE_PRESENT
LOCAL_CONTRACT_PASS
LOCAL_INTEGRATED_PASS
AUTHENTIC_SOURCE_PASS
PRODUCTION_RUNTIME_PASS
GENERALIZATION_PASS
SCALE_PASS
RELEASE_ACCEPTED
```

Passing a resolver unit test or mounting a UI panel is not evidence for the
later gates.

## 16. Completion definition

The executable enterprise model is complete only when a user can select any
supported governed target and G8 can produce a reproducible, exact-scope
answer to all of these questions:

```text
Which executable verb applies?
Which exact function version will run?
Which inputs, dimensions, policies, rates, evidence, and approvals are needed?
Which alternatives are valid?
Are the available facts compatible in grain, unit, currency, and time?
What is ready, partial, blocked, refused, stale, or incomparable?
What deterministic result was produced?
What proves it?
What authority does it have?
What can happen next, and what remains prohibited?
What changed after later evidence, action, readback, or outcome?
```

Until those answers are available through one retained resolver contract and
the authenticated source-to-outcome journey is independently accepted, G8 is
an advancing implementation and not a fully completed executable enterprise
operating model.
