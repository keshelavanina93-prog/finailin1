"""Versioned diagnostic contracts, separate from executable business capabilities.

These definitions describe dependency questions the resolver can ask. They do not
register ontology schemas, certify observations, or implement the named calculations.
Unregistered resource types are prospective contracts, never evidence of an engine.
Live Function/FactContract dependencies are inspected independently of this catalog.
"""

# ruff: noqa: RUF001 -- Original Cyrillic report titles are intentional source hints.

from copy import deepcopy
from typing import Any

from finai_api.domain.ontology_catalog import TYPE_FIELDS

CONTRACT_VERSION = "enterprise-diagnostic-requirements/1"
EXPORT_NOTICE = (
    "Export suggestions only: report names vary by source product, configuration and locale. "
    "A suggested report name does not establish parser support, sufficient granularity, "
    "complete coverage or canonical authority. Keep original bytes, headings, units and "
    "row coordinates; review company, period and semantic bindings before use."
)


def _requirement(
    identity: str,
    label: str,
    resource_types: list[str],
    required_fields: list[str],
    source_classes: list[str],
    dependencies: list[str],
    grain: list[str],
    guidance: str,
    examples: list[str] | None = None,
    *,
    period_required: bool = True,
    material: bool = True,
) -> dict[str, Any]:
    # Custom tenant schemas can exist beyond seeded TYPE_FIELDS. This describes
    # built-in coverage only; the live resolver must inspect tenant schema evidence.
    unregistered_types = [kind for kind in resource_types if kind not in TYPE_FIELDS]
    return {
        "id": identity,
        "label": label,
        "contract_version": CONTRACT_VERSION,
        "resource_types": resource_types,
        "schema_state": "NOT_IN_BUILTIN_CATALOG" if unregistered_types else "BUILTIN_REGISTERED",
        "unregistered_resource_types": unregistered_types,
        "required_fields": required_fields,
        "source_classes": source_classes,
        "dependencies": dependencies,
        "grain": grain,
        "scope_fields": ["company_id", "valid_at", "known_at"]
        + (["period"] if period_required else []),
        "guidance": guidance,
        "examples": examples or [],
        "example_semantics": "EXPORT_SUGGESTIONS_NOT_ADAPTER_CLAIMS",
        "material": material,
        "period_required": period_required,
    }


# Material requirements cannot be fulfilled by reference templates, approved nouns,
# a filename, or a source classification alone. Resolver authority/grain checks apply.
_REQUIREMENT_LIST = [
    _requirement(
        "ledger",
        "Company accounting ledger",
        ["Ledger"],
        ["legal_entity_id", "calendar_id", "chart_id", "currency_id"],
        [],
        [],
        ["legal_entity", "ledger", "chart", "functional_currency"],
        "Review the company's ledger, chart, fiscal calendar and functional currency links.",
        period_required=False,
        material=False,
    ),
    _requirement(
        "accounting-binding",
        "Reviewed source accounting binding",
        ["SourceAccountingBinding"],
        ["scope_id", "ledger_id", "period_id", "currency_id", "amount_semantics"],
        ["TRIAL_BALANCE", "GL_OR_JOURNAL"],
        ["ledger"],
        ["company", "ledger", "book", "period", "currency", "source_representation"],
        "Review the retained source's company, period, ledger, currency, amount meaning and "
        "row grain through a ResourceProposal. An uploaded trial balance is not a journal.",
        [
            "1C export suggestion: Оборотно-сальдовая ведомость with full Субконто detail",
            "ERP journal export with original source coordinates",
        ],
    ),
    _requirement(
        "journals",
        "Approved company journals",
        ["JournalEntry"],
        ["legal_entity_id", "ledger_id", "period_id", "reference"],
        ["GL_OR_JOURNAL", "TRIAL_BALANCE"],
        ["accounting-binding"],
        ["company", "ledger", "journal", "line", "posting_date", "currency"],
        "Supply approved balanced journal entries and source-bound lines covering the requested "
        "period. Trial-balance observations require a separate reviewed transformation; totals "
        "cannot be expanded into invented transactions.",
        ["1C export suggestion: Журнал проводок or Карточка счета", "ERP general ledger detail"],
    ),
    _requirement(
        "statement-lines",
        "Versioned statement hierarchy and account classification",
        ["ReportLineHierarchy"],
        ["ledger_id", "definition", "account_mapping_id"],
        [],
        ["ledger"],
        ["report", "line", "account_mapping_version", "effective_period"],
        "Define and approve statement lines, signs, subtotal hierarchy and local-account "
        "classification for the requested accounting basis. Generic account names cannot "
        "establish P&L, balance sheet or EBITDA treatment.",
        ["Reviewed chart-to-statement mapping with effective dates"],
    ),
    _requirement(
        "cash-flow-classification",
        "Cash flow and non-cash adjustment classification",
        ["CashFlowClassification"],
        ["definition", "ledger_id"],
        ["CASH_FLOW_FACTS"],
        ["journals", "statement-lines"],
        ["company", "journal_line", "cash_flow_category"],
        "Bind cash accounts, operating/investing/financing categories and non-cash adjustments "
        "to exact journal lines; the compiler and reconciliation rule also need implementation.",
        ["Bank/cash journal plus reviewed cash-flow mapping and non-cash adjustments"],
    ),
    _requirement(
        "group-scope",
        "Effective consolidation perimeter",
        ["ConsolidationGroup"],
        ["code", "definition"],
        [],
        [],
        ["group", "subsidiary", "ownership", "method", "effective_period"],
        "Approve the complete subsidiary perimeter, ownership, consolidation method and "
        "effective dates. A group name or one subsidiary link does not prove the perimeter.",
        ["Ownership register and approved consolidation perimeter"],
    ),
    _requirement(
        "subsidiary-journals",
        "Approved journals for every consolidation unit",
        ["ConsolidationJournalSet"],
        ["group_id", "definition", "coverage_state"],
        ["GL_OR_JOURNAL", "TRIAL_BALANCE"],
        ["group-scope", "journals"],
        ["group", "subsidiary", "ledger", "period", "functional_currency"],
        "Supply an explicit completeness manifest and exact approved journal pins for each "
        "subsidiary in the perimeter. An approved journal for one company is not group coverage.",
        ["Entity-by-entity approved journal package with completeness reconciliation"],
    ),
    _requirement(
        "fx-rates",
        "Approved FX rates and translation policy",
        ["FXRateSet"],
        ["base_currency_id", "rate_date", "definition"],
        ["APPROVED_FX_RATE_SET"],
        [],
        ["base_currency", "quote_currency", "rate_date", "rate_type", "source"],
        "Provide exact currency pairs, direction, effective dates, closing/average/historical "
        "rate basis and approved source. A dated FXRateSet shell does not contain rate values.",
        ["Approved treasury exchange-rate series and translation policy"],
    ),
    _requirement(
        "intercompany-eliminations",
        "Intercompany matching and elimination links",
        ["IntercompanyEliminationMapping"],
        ["group_id", "definition"],
        ["INTERCOMPANY_BALANCES"],
        ["group-scope", "subsidiary-journals"],
        ["group", "entity", "partner_entity", "transaction", "account", "currency"],
        "Review reciprocal balances, mismatches, elimination accounts and treatment by entity "
        "pair. A counterparty name cannot establish an intercompany elimination link.",
        ["Intercompany reconciliation matrix and approved elimination journal mapping"],
    ),
    _requirement(
        "asset-register",
        "Source-bound fixed asset register",
        ["FixedAssetRegister"],
        ["legal_entity_id", "definition"],
        ["FIXED_ASSET_REGISTER"],
        [],
        ["company", "asset", "component", "in_service_date", "currency"],
        "Supply asset and component identities, cost, capitalization and in-service dates, "
        "residual value, useful life, accumulated depreciation, impairment and disposals. "
        "AssetPortfolio identities alone do not contain these measurements.",
        ["1C export suggestion: Ведомость амортизации ОС", "ERP fixed asset register"],
    ),
    _requirement(
        "depreciation-policy",
        "Approved depreciation and capitalization policy",
        ["DepreciationPolicy"],
        ["definition", "legal_entity_id"],
        [],
        ["asset-register"],
        ["company", "asset_class", "book", "method", "effective_period"],
        "Approve accounting book, method, conventions, useful lives, residual values, "
        "capitalization and disposal rules. These are business decisions, not inferred defaults.",
        ["Approved accounting policy and asset-class depreciation rules"],
    ),
    _requirement(
        "monetary-exposures",
        "Foreign currency monetary positions",
        ["MonetaryExposure"],
        ["currency_id", "amount", "carrying_amount", "as_of"],
        ["SUBLEDGER_AGING", "GL_OR_JOURNAL"],
        ["accounting-binding"],
        ["company", "account", "open_item", "transaction_currency", "cutoff"],
        "Supply foreign-currency open items and their booked functional amounts, settlement "
        "history and one valuation cutoff; keep realized and unrealized amounts separate.",
        ["Currency subledger open-item export with original and functional amounts"],
    ),
    _requirement(
        "tax-rules",
        "Jurisdiction and effective tax calculation rules",
        ["TaxCalculationPolicy"],
        ["jurisdiction", "definition"],
        [],
        [],
        ["jurisdiction", "tax_type", "taxpayer", "rule_version", "effective_period"],
        "Review taxpayer status, jurisdiction, tax type, effective rules, exemptions and "
        "calculation basis. A regulatory document or applicability result is not a tax engine.",
        ["Approved tax policy with source law references and effective dates"],
    ),
    _requirement(
        "tax-base",
        "Reconciled taxable transactions and adjustments",
        ["TaxBaseFact"],
        ["tax_code", "tax_base", "currency_id", "source_record_id"],
        ["TAX_REGISTER", "GL_OR_JOURNAL"],
        ["journals", "tax-rules"],
        ["company", "tax_type", "source_document", "tax_point_date", "currency"],
        "Supply tax-coded transactions, deductible/non-deductible adjustments, exemptions, "
        "credits and filing-period reconciliation. Ledger totals alone cannot establish tax base.",
        ["Tax register and invoice detail with tax codes and source document references"],
    ),
    _requirement(
        "employee-time",
        "Employee contracts, time and compensation inputs",
        ["PayrollInput"],
        ["employee_id", "period_id", "definition"],
        ["PAYROLL_REGISTER", "OPERATIONAL_KPI"],
        [],
        ["company", "employee", "contract", "pay_period", "cost_center"],
        "Supply authorized compensation, effective contracts, worked time, leave, benefits "
        "and cost allocation identifiers within the user's employee-data access scope.",
        ["HR payroll register and approved timecards"],
    ),
    _requirement(
        "payroll-rules",
        "Effective payroll and labor allocation rules",
        ["PayrollPolicy"],
        ["jurisdiction", "definition"],
        [],
        ["employee-time"],
        ["company", "jurisdiction", "pay_group", "rule_version", "effective_period"],
        "Approve pay conventions, statutory deductions, employer charges and cost-center "
        "allocation rules; a generic operational KPI does not define payroll computation.",
        ["Approved payroll calculation and labor allocation policy"],
    ),
    _requirement(
        "physical-stock",
        "Product and tank stock at one cutoff",
        ["InventoryObservation"],
        ["product_id", "tank_id", "quantity", "unit", "observed_at", "measurement_basis"],
        ["INVENTORY_BALANCE", "INVENTORY_MOVEMENT"],
        [],
        ["company", "product", "tank", "cutoff", "unit", "measurement_basis"],
        "Export stock by product, warehouse and tank at one cutoff, with recorded units and "
        "measurement basis. Keep kg and liters separate; conversion needs approved density "
        "and reference conditions. A Tank resource does not prove stock quantity.",
        ["1C export suggestion: Ведомость по товарам на складах or Остатки товаров"],
    ),
    _requirement(
        "sales",
        "Station and product sales with revenue and quantity",
        ["SalesFact"],
        ["product_id", "station_id", "quantity", "unit", "net_amount", "currency_id", "sold_at"],
        ["PRODUCT_REVENUE", "SALES_REPORT"],
        [],
        ["company", "sales_document", "line", "station", "product", "channel", "date"],
        "Supply dated sales detail by station, product and channel with quantities, currency, "
        "discounts and explicit net/gross/VAT meaning. GL revenue totals do not prove liters.",
        ["1C export suggestion: Отчет о розничных продажах or Ведомость продаж"],
    ),
    _requirement(
        "cost-layers",
        "Product cost layers and recognized COGS",
        ["InventoryCostLayer"],
        ["product_id", "cost_layer_id", "amount", "currency_id", "definition"],
        ["ACCOUNT_ANALYTIC_TURNOVER", "INVENTORY_MOVEMENT", "PRODUCT_COGS"],
        ["accounting-binding"],
        ["company", "product", "cost_layer", "recognition_period", "currency"],
        "Provide purchase/cost layers, freight and import allocations, inventory valuation "
        "policy and recognized COGS links. Review the sales-to-cost join grain to prevent "
        "double-counting purchases, stock and expense.",
        ["1C export suggestion: Себестоимость товаров or Расчет себестоимости"],
    ),
    _requirement(
        "margin-binding",
        "Reviewed sales-to-cost and ledger reconciliation links",
        ["MarginReconciliationBinding"],
        ["definition", "legal_entity_id"],
        [],
        ["sales", "cost-layers", "journals"],
        ["company", "station", "product", "period", "currency", "quantity_unit"],
        "Approve matching sales, COGS and ledger coverage at one grain, currency and period. "
        "For a margin bridge, additionally bind two comparable periods and the price, volume, "
        "mix, FX, freight and loss attribution policy.",
        ["Reviewed sales/cost/GL reconciliation and bridge attribution contract"],
    ),
    _requirement(
        "demand-policy",
        "Demand horizon and stock minimum policy",
        ["StockCoverPolicy"],
        ["definition", "legal_entity_id"],
        ["APPROVED_DEMAND_PLAN"],
        ["sales"],
        ["company", "station", "product", "horizon", "quantity_unit"],
        "Review the sales-demand window, forecast basis, stock minima and treatment of zero "
        "demand. Stock cover needs this policy as well as stock; no horizon is assumed.",
        ["Approved station/product demand horizon and minimum-stock rules"],
    ),
    _requirement(
        "physical-movements",
        "Dispatch, receipt and custody measurements",
        ["PhysicalMovement"],
        ["product_id", "origin_id", "destination_id", "quantity", "unit", "event_at"],
        ["PHYSICAL_MOVEMENT", "INVENTORY_MOVEMENT"],
        [],
        ["company", "document", "line", "product", "custody_boundary", "event_time", "unit"],
        "Supply terminal receipts, depot transfers, waybills and station receipts with original "
        "dispatch/receipt times and measurement bases. Reconcile internal transfers separately "
        "from sales; movement residuals are not automatically financial losses.",
        [
            "1C export suggestion: Ведомость движения товаров or Заборные листы",
            "Terminal intake and truck waybill exports",
        ],
    ),
    _requirement(
        "tank-measurements",
        "Tank dips, calibration and measurement conditions",
        ["TankMeasurement"],
        ["tank_id", "observed_at", "quantity", "unit", "definition"],
        ["TANK_MEASUREMENT", "PHYSICAL_MOVEMENT"],
        [],
        ["company", "tank", "measurement_time", "instrument", "measurement_basis"],
        "Supply opening/closing tank measurements, calibration, density and temperature with "
        "their actual units and reference conditions. Temperature normalization is not "
        "itself loss.",
        [
            "Tank gauge or dip logs",
            "1C export suggestion: Сменный отчет АЗС or Инвентаризация товаров",
        ],
    ),
    _requirement(
        "loss-policy",
        "Effective measurement reconciliation and loss rules",
        ["LossReconciliationPolicy"],
        ["definition", "legal_entity_id"],
        [],
        ["physical-stock", "physical-movements", "tank-measurements"],
        ["company", "site", "product", "rule_version", "effective_period"],
        "Review comparable custody boundaries, quantity basis, calibration tolerances and "
        "normative loss rules. Financial valuation additionally needs cost layers and approval.",
        ["Approved product/site loss rules and measurement reconciliation policy"],
    ),
    _requirement(
        "customer-open-items",
        "Customer invoices, settlements and aging cutoff",
        ["ReceivableOpenItem"],
        ["customer_id", "invoice_id", "due_date", "outstanding_amount", "currency_id", "as_of"],
        ["SUBLEDGER_AGING"],
        [],
        ["company", "customer", "contract", "invoice", "cutoff", "currency"],
        "Supply invoice and due dates, settlements and outstanding amounts at one cutoff. "
        "Customer balances without due-date evidence cannot establish overdue exposure.",
        ["1C export suggestion: Ведомость взаиморасчетов с клиентами or Задолженность покупателей"],
    ),
    _requirement(
        "customer-credit",
        "Approved credit terms and exposure allocation",
        ["CustomerCreditPolicy"],
        ["customer_id", "definition"],
        [],
        ["customer-open-items"],
        ["company", "customer", "contract", "currency", "effective_period"],
        "Approve credit limits, payment terms and customer/product attribution. Distinguish "
        "invoice aging from a credit-limit breach; neither can be inferred from a customer name.",
        ["Customer contract terms and approved credit limits"],
    ),
    _requirement(
        "gas-topology",
        "Validated gas network connectivity and pipe properties",
        ["GasHydraulicNetwork"],
        ["system_id", "definition"],
        [],
        [],
        ["company", "network", "segment", "junction", "effective_version"],
        "Provide connected endpoints, pipe lengths/diameters/roughness, elevations, valves "
        "and regulator characteristics. GIS geometry or PipelineSegment identities alone "
        "do not establish a solvable hydraulic model.",
        ["Reviewed engineering network model and asset property register"],
        period_required=False,
    ),
    _requirement(
        "gas-boundaries",
        "Gas pressure, demand and fluid boundary conditions",
        ["GasBoundaryCondition"],
        ["system_id", "observed_at", "definition"],
        ["GAS_TELEMETRY", "OPERATIONAL_KPI"],
        ["gas-topology"],
        ["company", "network", "boundary_node", "timestamp", "unit", "reference_conditions"],
        "Supply inlet/outlet pressure, demand, temperature, gas composition and boundary "
        "conditions with timestamps and units; approve steady/transient solver assumptions.",
        ["SCADA pressure/flow observations and reviewed demand boundary conditions"],
    ),
    _requirement(
        "gas-meter-balance",
        "Gas custody meters and comparable balance boundary",
        ["GasMeterObservation"],
        ["meter_id", "observed_at", "quantity", "unit", "reference_conditions"],
        ["GAS_METER_READING", "PHYSICAL_MOVEMENT"],
        ["gas-topology"],
        ["company", "balance_zone", "meter", "interval", "standard_conditions"],
        "Supply inlet/outlet meters, linepack change and complete zone boundaries over the "
        "same interval. Standardize volumes only under approved conditions and calibration.",
        ["Custody meter interval exports, linepack evidence and zone reconciliation"],
    ),
    _requirement(
        "planning-model",
        "Versioned driver model, dimensions and formulas",
        ["DriverPlanningModel"],
        ["definition", "legal_entity_id"],
        [],
        [],
        ["model", "dimension_member", "time_bucket", "unit", "model_version"],
        "Define model dimensions, member hierarchies, units, formulas, dependencies and "
        "constraints. Validate cycles and aggregation rules before running a planning solver.",
        ["Approved driver-model definition and dimension/member mappings"],
        period_required=False,
    ),
    _requirement(
        "planning-baseline",
        "Reconciled actuals and approved planning assumptions",
        ["PlanningInputSet"],
        ["model_id", "scenario_id", "definition"],
        ["APPROVED_BUDGET", "APPROVED_DEMAND_PLAN", "GL_OR_JOURNAL"],
        ["planning-model"],
        ["company", "model", "scenario", "dimension_tuple", "time_bucket", "unit"],
        "Bind baseline actuals and separately labeled assumptions to exact model versions, "
        "dimensions and periods. Scenario assumptions never become historical financial truth; "
        "approval of a plan is separate from evaluating a scenario.",
        ["Approved budget/forecast version, driver assumptions and actuals reconciliation"],
    ),
    _requirement(
        "supplier-open-items",
        "Supplier invoices, settlements and aging cutoff",
        ["PayableOpenItem"],
        ["supplier_id", "invoice_id", "due_date", "outstanding_amount", "currency_id", "as_of"],
        ["SUBLEDGER_AGING"],
        ["accounting-binding"],
        ["company", "supplier", "contract", "invoice", "cutoff", "currency"],
        "Supply supplier invoice and due dates, settlements, disputes and remaining amounts "
        "at one cutoff; reconcile the payable subledger to the approved ledger.",
        ["1C export suggestion: Ведомость взаиморасчетов с поставщиками"],
    ),
    _requirement(
        "valuation-policy",
        "Approved inventory valuation and allocation policy",
        ["InventoryValuationPolicy"],
        ["definition", "legal_entity_id"],
        [],
        ["physical-stock", "cost-layers"],
        ["company", "product", "valuation_pool", "cost_method", "effective_period"],
        "Approve cost method, cost pools, landed-cost allocation, write-downs and reconciliation "
        "to the ledger. Quantity stock and purchase invoices alone do not establish valuation.",
        ["Approved inventory accounting policy and stock-to-GL reconciliation"],
    ),
    _requirement(
        "bank-statements",
        "Bank statement transactions and control balances",
        ["BankStatementTransaction"],
        ["bank_account_id", "transaction_id", "amount", "currency_id", "value_date"],
        ["BANK_STATEMENT"],
        ["journals"],
        ["company", "bank_account", "statement", "transaction", "value_date", "currency"],
        "Supply complete bank statement intervals, opening/closing controls and stable "
        "transaction identifiers. Review matching rules and outstanding reconciling items.",
        ["Bank statement export with control balances and ledger cash-account mapping"],
    ),
    _requirement(
        "regulatory-scope",
        "Approved regulatory applicability and obligation inputs",
        ["RegulatoryRule"],
        ["act_id", "legal_entity_id", "licence_id", "definition"],
        ["REGULATORY_PUBLICATION"],
        [],
        ["company", "jurisdiction", "licence", "act", "effective_period"],
        "Review applicability, effective rules, obligations and source publications. Existing "
        "applicability/reachability checks do not implement monetary exposure or filing.",
        ["Licensed activities, applicable obligations and approved regulatory rule definitions"],
    ),
    _requirement(
        "regulatory-exposure-facts",
        "Obligation-specific exposure facts and calculation policy",
        ["RegulatoryExposureFact"],
        ["rule_id", "definition", "source_record_id"],
        ["REGULATORY_EXPOSURE"],
        ["regulatory-scope"],
        ["company", "obligation", "activity", "period", "unit"],
        "Supply facts for the selected obligation and an approved calculation policy. "
        "Unknown rules or absent activity evidence must remain unresolved, never zero exposure.",
        ["Obligation-specific activity evidence and approved exposure calculation policy"],
    ),
    _requirement(
        "emissions-activity",
        "Energy and emissions activity measurements",
        ["EmissionsActivityFact"],
        ["facility_id", "activity_type", "quantity", "unit", "observed_at"],
        ["ENERGY_ACTIVITY", "OPERATIONAL_KPI"],
        [],
        ["company", "facility", "activity", "period", "unit", "organizational_boundary"],
        "Supply energy/fuel usage and organizational boundaries with original units, period "
        "coverage and source lineage; a mapped energy asset is not an activity measurement.",
        ["Metered energy use, fuel consumption and reviewed organizational boundary"],
    ),
    _requirement(
        "emissions-factors",
        "Approved emissions factors and calculation boundary",
        ["EmissionsFactorSet"],
        ["definition", "effective_from"],
        [],
        ["emissions-activity"],
        ["method", "activity", "geography", "factor_version", "effective_period", "unit"],
        "Approve the applicable methodology, factors, geography, scope boundary and unit "
        "conversions. Evidence collection does not establish calculation or certification.",
        ["Versioned approved emission-factor set and methodology"],
    ),
]

REQUIREMENTS: dict[str, dict[str, Any]] = {item["id"]: item for item in _REQUIREMENT_LIST}

# Reviewed business meaning is USER_ASSERTED in the canonical kernel, with approved
# source/version dependencies. Requiring SOURCE_BOUND on these declarations would
# reject legitimate bindings forever (source_accounting_context.validate_context).
_CONFIGURATION_INPUTS = {
    "accounting-binding",
    "statement-lines",
    "cash-flow-classification",
    "group-scope",
    "intercompany-eliminations",
    "depreciation-policy",
    "tax-rules",
    "payroll-rules",
    "margin-binding",
    "demand-policy",
    "loss-policy",
    "customer-credit",
    "gas-topology",
    "planning-model",
    "planning-baseline",
    "valuation-policy",
    "emissions-factors",
}
for _identity in _CONFIGURATION_INPUTS:
    REQUIREMENTS[_identity]["material"] = False
    REQUIREMENTS[_identity]["evidence_semantics"] = "REVIEWED_CONFIGURATION_WITH_DEPENDENCIES"

# journal_production publishes journals as USER_ASSERTED and SourceRecord as SOURCE_BOUND.
# Approval, exact line/source pins and ledger reconciliation still need inspection.
REQUIREMENTS["journals"]["material"] = False
REQUIREMENTS["journals"]["evidence_semantics"] = "GOVERNED_JOURNAL_WITH_SOURCE_PINS"


def _target(
    identity: str,
    label: str,
    domain: str,
    requirements: list[str],
    aliases: list[str],
    engine_reason: str,
    evidence: list[str],
) -> dict[str, Any]:
    return {
        "id": identity,
        "label": label,
        "domain": domain,
        "contract_version": CONTRACT_VERSION,
        "requirements": requirements,
        "aliases": aliases,
        "engine_state": "ENGINE_NOT_IMPLEMENTED",
        "engine_reason": engine_reason,
        "implementation_evidence": evidence,
        "coverage": "DECLARED_DIAGNOSTIC_REQUIREMENTS_ONLY",
    }


_FUNCTION_EVIDENCE = ["services/function_execution.py:manifest", "services/fact_aggregation.py"]
_PETROLEUM_EVIDENCE = ["services/petroleum_command.py:missing", "services/petroleum_intake.py"]
_NO_DOMAIN_ENGINE = (
    "No installed execution adapter for this named target is registered in the Function "
    "runtime. This catalog can diagnose declared inputs; a reviewed executable domain "
    "contract and verified producer are still required. An installed generic Function or "
    "FactContract can be diagnosed separately by its exact canonical resource ID."
)
_NO_PETROLEUM_ENGINE = (
    "The petroleum command producer explicitly reports NOT_IMPLEMENTED. Operational report "
    "intake adapters and approved measurement bindings remain required; uploading these "
    "exports alone will not calculate the cockpit. Legacy workbook reconstruction is "
    "reference-only."
)
_NO_STATEMENT_ENGINE = (
    "Installed journal-movement adapters explicitly exclude financial statements and "
    "statement classification. A reviewed statement compiler and complete account-line "
    "coverage are required in addition to approved journals."
)

_TARGET_LIST = [
    _target(
        "petroleum-margin",
        "Petroleum gross margin",
        "Petroleum",
        ["margin-binding"],
        [
            "petroleum margin",
            "station gross margin",
            "fuel margin",
            "margin per liter",
            "petroleum gross margins",
            "station gross margins",
        ],
        _NO_PETROLEUM_ENGINE,
        _PETROLEUM_EVIDENCE,
    ),
    _target(
        "petroleum-inventory",
        "Petroleum inventory and stock cover",
        "Petroleum",
        ["physical-stock", "demand-policy"],
        ["stock cover", "days of cover", "tank stock", "inventory truth"],
        _NO_PETROLEUM_ENGINE,
        _PETROLEUM_EVIDENCE,
    ),
    _target(
        "petroleum-flow",
        "Physical fuel flow and dispatch",
        "Petroleum",
        ["physical-movements"],
        ["physical fuel flow", "fuel dispatch", "trace this liter", "fuel movements"],
        _NO_PETROLEUM_ENGINE,
        _PETROLEUM_EVIDENCE,
    ),
    _target(
        "petroleum-loss",
        "Petroleum loss and variance",
        "Petroleum",
        ["loss-policy", "cost-layers"],
        ["petroleum loss", "loss and variance", "tank loss", "fuel variance"],
        _NO_PETROLEUM_ENGINE,
        _PETROLEUM_EVIDENCE,
    ),
    _target(
        "petroleum-ar",
        "Wholesale receivables and credit exposure",
        "Receivables",
        ["customer-open-items", "customer-credit"],
        ["wholesale ar", "customer aging", "receivables aging", "customer credit exposure"],
        _NO_PETROLEUM_ENGINE,
        _PETROLEUM_EVIDENCE,
    ),
    _target(
        "financial-statements",
        "Company P&L and balance sheet",
        "Financial statements",
        ["journals", "statement-lines"],
        ["profit and loss", "company balance sheet", "company pnl", "financial statements"],
        _NO_STATEMENT_ENGINE,
        _FUNCTION_EVIDENCE,
    ),
    _target(
        "cash-flow",
        "Company cash flow statement",
        "Cash flow",
        ["cash-flow-classification"],
        ["cash flow statement", "cashflow statement", "cash flow and non cash adjustments"],
        _NO_STATEMENT_ENGINE,
        _FUNCTION_EVIDENCE,
    ),
    _target(
        "consolidated-ebitda",
        "Consolidated group EBITDA and statements",
        "Consolidation",
        ["subsidiary-journals", "fx-rates", "intercompany-eliminations", "statement-lines"],
        [
            "consolidated group ebitda",
            "consolidated ebitda",
            "group ebitda",
            "consolidated balance sheet",
            "consolidated statements",
        ],
        _NO_DOMAIN_ENGINE,
        _FUNCTION_EVIDENCE,
    ),
    _target(
        "asset-depreciation",
        "Fixed asset depreciation",
        "Fixed assets",
        ["asset-register", "depreciation-policy", "journals"],
        ["asset depreciation", "depreciation", "fixed assets", "capitalization"],
        _NO_DOMAIN_ENGINE,
        _FUNCTION_EVIDENCE,
    ),
    _target(
        "treasury-fx",
        "Treasury FX revaluation",
        "Treasury",
        ["monetary-exposures", "fx-rates"],
        [
            "fx revaluation",
            "foreign exchange exposure",
            "treasury fx",
            "realized unrealized fx",
            "currency revaluation",
        ],
        _NO_DOMAIN_ENGINE,
        _FUNCTION_EVIDENCE,
    ),
    _target(
        "tax-exposure",
        "Tax exposure",
        "Tax",
        ["tax-rules", "tax-base"],
        ["tax exposure", "tax liability", "calculate tax", "vat exposure"],
        _NO_DOMAIN_ENGINE,
        _FUNCTION_EVIDENCE,
    ),
    _target(
        "payroll-cost",
        "Payroll and labor cost",
        "HR and payroll",
        ["employee-time", "payroll-rules", "journals"],
        ["payroll", "labor cost", "labour cost", "employee costs"],
        _NO_DOMAIN_ENGINE,
        _FUNCTION_EVIDENCE,
    ),
    _target(
        "gas-hydraulics",
        "Gas network hydraulic exposure",
        "Gas operations",
        ["gas-topology", "gas-boundaries"],
        [
            "gas network hydraulic exposure",
            "gas hydraulics",
            "hydraulic exposure",
            "network pressure",
        ],
        _NO_DOMAIN_ENGINE,
        _FUNCTION_EVIDENCE,
    ),
    _target(
        "gas-balance",
        "Gas network balance and unaccounted gas",
        "Gas operations",
        ["gas-meter-balance"],
        ["gas balance", "unaccounted gas", "gas network balance"],
        _NO_DOMAIN_ENGINE,
        _FUNCTION_EVIDENCE,
    ),
    _target(
        "driver-planning",
        "Multidimensional driver planning",
        "Planning",
        ["planning-model", "planning-baseline"],
        [
            "driver planning",
            "multidimensional planning",
            "driver based forecast",
            "scenario planning",
            "budget forecast",
        ],
        _NO_DOMAIN_ENGINE,
        _FUNCTION_EVIDENCE,
    ),
    _target(
        "ap-aging",
        "Accounts payable aging",
        "Procurement and payables",
        ["supplier-open-items"],
        ["accounts payable aging", "supplier aging", "ap aging", "supplier exposure"],
        _NO_DOMAIN_ENGINE,
        _FUNCTION_EVIDENCE,
    ),
    _target(
        "inventory-valuation",
        "Inventory valuation",
        "Inventory accounting",
        ["valuation-policy", "journals"],
        ["inventory valuation", "stock valuation", "inventory cost"],
        _NO_DOMAIN_ENGINE,
        _FUNCTION_EVIDENCE,
    ),
    _target(
        "bank-reconciliation",
        "Bank reconciliation",
        "Banking",
        ["bank-statements"],
        ["bank reconciliation", "reconcile bank", "cash reconciliation"],
        _NO_DOMAIN_ENGINE,
        _FUNCTION_EVIDENCE,
    ),
    _target(
        "regulatory-exposure",
        "Regulatory monetary exposure",
        "Regulatory",
        ["regulatory-exposure-facts"],
        ["regulatory exposure", "regulatory monetary exposure", "compliance exposure"],
        "Regulatory applicability and reachability evaluation are implemented separately. "
        "They do not implement this monetary exposure calculation or filing target.",
        ["services/regulatory_impact.py", *_FUNCTION_EVIDENCE],
    ),
    _target(
        "emissions-exposure",
        "Energy and emissions footprint",
        "Sustainability",
        ["emissions-activity", "emissions-factors"],
        ["emissions footprint", "carbon footprint", "energy emissions", "emissions exposure"],
        _NO_DOMAIN_ENGINE,
        _FUNCTION_EVIDENCE,
    ),
]

TARGETS: dict[str, dict[str, Any]] = {item["id"]: item for item in _TARGET_LIST}


def catalog() -> dict[str, Any]:
    """Return isolated descriptive definitions; no query, mutation or calculation occurs."""
    return {
        "contract_version": CONTRACT_VERSION,
        "targets": deepcopy(list(TARGETS.values())),
        "requirements": deepcopy(list(REQUIREMENTS.values())),
        "export_notice": EXPORT_NOTICE,
        "coverage": "DECLARED_TARGETS_AND_CANONICAL_RESOURCE_DEPENDENCIES",
        "unknown_target_policy": "UNKNOWN_TARGET_REQUIREMENTS_NOT_DEFINED",
        "canonical_resource_policy": "INSPECT_PINNED_GRAPH_INDEPENDENTLY_OF_TARGET_CATALOG",
        "read_only": True,
    }
