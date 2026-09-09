export type SourceFamilyClassification = "anchored" | "partial" | "target-only";

export type RouteStatus = "wired" | "proxy-only" | "planned";

export type ImplementationStatus = "implemented" | "partially-implemented" | "target-only";

export type RequiredScopeDimension =
  | "tenant"
  | "legal_entity"
  | "business_unit"
  | "site"
  | "meter"
  | "asset"
  | "station"
  | "store"
  | "cash_register"
  | "warehouse"
  | "counterparty"
  | "contract"
  | "account"
  | "subaccount"
  | "cost_center"
  | "item"
  | "fuel_grade"
  | "tank"
  | "measurement_basis"
  | "quality"
  | "pump"
  | "dispenser"
  | "nozzle"
  | "shift"
  | "operator"
  | "currency"
  | "period"
  | "document"
  | "lineage";

export type EvidenceRequirement =
  | "source_file_hash"
  | "schema_hash"
  | "retained_workbook"
  | "row_count"
  | "opening_closing_balance"
  | "debit_credit_total"
  | "journal_document_number"
  | "movement_register"
  | "vendor_invoice"
  | "purchase_order"
  | "receipt_or_waybill"
  | "entity_registry"
  | "ownership_or_group_structure"
  | "station_master"
  | "pos_shift_close"
  | "fuel_grade_mapping"
  | "pump_meter_reading"
  | "tank_level_reading"
  | "cash_register_z_report"
  | "regulatory_filing"
  | "external_reference"
  | "lineage_receipt";

export type SourceFamilyRouteContract = {
  proxyRoutes: readonly string[];
  backendRoutes: readonly string[];
  status: RouteStatus;
};

export type SourceFamilyIntakePlan = {
  id: string;
  label: string;
  systems: readonly string[];
  requiredScopeDimensions: readonly RequiredScopeDimension[];
  implementedScopeDimensions: readonly RequiredScopeDimension[];
  requiredEvidence: readonly EvidenceRequirement[];
  presentEvidence: readonly EvidenceRequirement[];
  routes: SourceFamilyRouteContract;
  currentImplementationStatus: ImplementationStatus;
  blockedOrMissingContracts: readonly string[];
};

const intakeRoutes = (
  proxyRoutes: readonly string[],
  backendRoutes: readonly string[],
  status: RouteStatus,
): SourceFamilyRouteContract => ({
  proxyRoutes,
  backendRoutes,
  status,
});

export const SOURCE_FAMILY_INTAKE_PLANS: readonly SourceFamilyIntakePlan[] = [
  {
    id: "1c_trial_balance",
    label: "1C trial balance",
    systems: ["1C", "Excel trial balance export", "retained workbook"],
    requiredScopeDimensions: ["tenant", "legal_entity", "account", "subaccount", "currency", "period", "document", "lineage"],
    implementedScopeDimensions: ["tenant", "legal_entity", "account", "currency", "period", "document", "lineage"],
    requiredEvidence: [
      "source_file_hash",
      "schema_hash",
      "retained_workbook",
      "row_count",
      "opening_closing_balance",
      "debit_credit_total",
      "lineage_receipt",
    ],
    presentEvidence: ["source_file_hash", "schema_hash", "retained_workbook", "row_count", "debit_credit_total", "lineage_receipt"],
    routes: intakeRoutes(
      ["/api/hydration/package", "/api/ontology/finance/*"],
      ["/v1/hydration/trial-balance-package", "/v1/ontology/finance/*"],
      "wired",
    ),
    currentImplementationStatus: "partially-implemented",
    blockedOrMissingContracts: ["Subaccount dimensional authority is not fully bound for every source row."],
  },
  {
    id: "1c_journal_movements",
    label: "1C journal and movements",
    systems: ["1C", "posting journal", "movement registers"],
    requiredScopeDimensions: [
      "tenant",
      "legal_entity",
      "business_unit",
      "account",
      "subaccount",
      "counterparty",
      "contract",
      "period",
      "document",
      "lineage",
    ],
    implementedScopeDimensions: ["tenant", "legal_entity", "account", "period", "document", "lineage"],
    requiredEvidence: [
      "source_file_hash",
      "schema_hash",
      "row_count",
      "debit_credit_total",
      "journal_document_number",
      "movement_register",
      "lineage_receipt",
    ],
    presentEvidence: ["source_file_hash", "schema_hash", "row_count", "journal_document_number", "lineage_receipt"],
    routes: intakeRoutes(
      ["/api/ontology/company-journals/*", "/api/ontology/source-documents/*"],
      ["/v1/ontology/company-journals/*", "/v1/ontology/source-documents/*"],
      "proxy-only",
    ),
    currentImplementationStatus: "partially-implemented",
    blockedOrMissingContracts: ["Movement-register grain, movement-to-journal-line reconciliation, and governed proposal submission are wired; independent promotion and authentic connector readback remain open."],
  },
  {
    id: "seg_procurement_expense",
    label: "SEG procurement and expense",
    systems: ["SEG procurement", "expense workbooks", "vendor evidence"],
    requiredScopeDimensions: [
      "tenant",
      "legal_entity",
      "business_unit",
      "cost_center",
      "warehouse",
      "counterparty",
      "contract",
      "item",
      "currency",
      "period",
      "document",
      "lineage",
    ],
    implementedScopeDimensions: ["tenant", "legal_entity", "counterparty", "currency", "period", "document", "lineage"],
    requiredEvidence: [
      "source_file_hash",
      "schema_hash",
      "row_count",
      "vendor_invoice",
      "purchase_order",
      "receipt_or_waybill",
      "lineage_receipt",
    ],
    presentEvidence: ["source_file_hash", "schema_hash", "row_count", "vendor_invoice", "lineage_receipt"],
    routes: intakeRoutes(
      ["/api/hydration", "/api/ontology/source-documents/*"],
      ["/v1/hydration/ingest", "/v1/ontology/source-documents/*"],
      "wired",
    ),
    currentImplementationStatus: "partially-implemented",
    blockedOrMissingContracts: ["Purchase-order and goods-receipt matching is not a typed frontend contract yet."],
  },
  {
    id: "socar_sgp_seg_multi_entity",
    label: "SOCAR, SGP and SEG multi-entity structures",
    systems: ["SOCAR", "SGP", "SEG", "corporate registry", "group structure evidence"],
    requiredScopeDimensions: ["tenant", "legal_entity", "business_unit", "site", "counterparty", "currency", "period", "document", "lineage"],
    implementedScopeDimensions: ["tenant", "legal_entity", "business_unit", "period", "document", "lineage"],
    requiredEvidence: [
      "source_file_hash",
      "schema_hash",
      "entity_registry",
      "ownership_or_group_structure",
      "external_reference",
      "lineage_receipt",
    ],
    presentEvidence: ["source_file_hash", "schema_hash", "entity_registry", "ownership_or_group_structure", "lineage_receipt"],
    routes: intakeRoutes(
      ["/api/ontology/*", "/api/workspace/constructions/*"],
      ["/v1/ontology/*", "/v1/workspace/constructions/*"],
      "proxy-only",
    ),
    currentImplementationStatus: "partially-implemented",
    blockedOrMissingContracts: ["Entity hierarchy versions need explicit effective-date and source-authority contracts."],
  },
  {
    id: "orpak_forecourt_pos",
    label: "ORPAK forecourt POS",
    systems: ["ORPAK", "forecourt POS", "station controller"],
    requiredScopeDimensions: [
      "tenant",
      "legal_entity",
      "station",
      "pump",
      "fuel_grade",
      "shift",
      "operator",
      "currency",
      "period",
      "document",
      "lineage",
    ],
    implementedScopeDimensions: ["tenant", "legal_entity", "station", "dispenser", "nozzle", "fuel_grade", "shift", "currency", "period", "document", "lineage"],
    requiredEvidence: [
      "source_file_hash",
      "schema_hash",
      "station_master",
      "pos_shift_close",
      "fuel_grade_mapping",
      "pump_meter_reading",
      "lineage_receipt",
    ],
    presentEvidence: ["source_file_hash", "schema_hash", "station_master", "fuel_grade_mapping", "lineage_receipt"],
    routes: intakeRoutes(
      [
        "/api/hydration",
        "/api/operations/petroleum/intake/{receipt_id}/validation",
        "/api/operations/petroleum/intake/{receipt_id}/promotion-preview",
        "/api/operations/petroleum/intake/{receipt_id}/promotion-proposal",
      ],
      [
        "/v1/hydration/ingest",
        "/v1/operations/petroleum/intake/{receipt_id}/validation",
        "/v1/operations/petroleum/intake/{receipt_id}/promotion-preview",
        "/v1/operations/petroleum/intake/{receipt_id}/promotion-proposal",
      ],
      "wired",
    ),
    currentImplementationStatus: "partially-implemented",
    blockedOrMissingContracts: ["ORPAK sale-line, semantic binding, and governed proposal submission are wired; independent promotion and authentic connector readback remain open."],
  },
  {
    id: "gas_telemetry",
    label: "Gas telemetry",
    systems: ["gas telemetry", "metering gateway", "SCADA export"],
    requiredScopeDimensions: ["tenant", "legal_entity", "site", "meter", "asset", "tank", "measurement_basis", "quality", "period", "document", "lineage"],
    implementedScopeDimensions: ["tenant", "legal_entity", "site", "meter", "asset", "tank", "fuel_grade", "measurement_basis", "quality", "period", "document", "lineage"],
    requiredEvidence: ["source_file_hash", "schema_hash", "row_count", "tank_level_reading", "external_reference", "lineage_receipt"],
    presentEvidence: ["source_file_hash", "schema_hash", "row_count", "tank_level_reading", "lineage_receipt"],
    routes: intakeRoutes(
      [
        "/api/hydration",
        "/api/operations/petroleum/intake/{receipt_id}/validation",
        "/api/operations/petroleum/intake/{receipt_id}/promotion-preview",
        "/api/operations/petroleum/intake/{receipt_id}/promotion-proposal",
        "/api/operations/petroleum/telemetry",
        "/api/operations/petroleum/reconciliation",
      ],
      [
        "/v1/hydration/ingest",
        "/v1/operations/petroleum/intake/{receipt_id}/validation",
        "/v1/operations/petroleum/intake/{receipt_id}/promotion-preview",
        "/v1/operations/petroleum/intake/{receipt_id}/promotion-proposal",
        "/v1/operations/petroleum/telemetry",
        "/v1/operations/petroleum/reconciliation",
      ],
      "wired",
    ),
    currentImplementationStatus: "partially-implemented",
    blockedOrMissingContracts: ["Telemetry, semantic binding and retained-series monotonicity checks are wired; live connector readback remains governed review work."],
  },
  {
    id: "retail_cash_registers",
    label: "Retail cash registers",
    systems: ["cash register exports", "retail POS", "fiscal Z reports"],
    requiredScopeDimensions: [
      "tenant",
      "legal_entity",
      "store",
      "cash_register",
      "shift",
      "operator",
      "currency",
      "period",
      "document",
      "lineage",
    ],
    implementedScopeDimensions: ["tenant", "legal_entity", "store", "cash_register", "shift", "operator", "currency", "period", "document", "lineage"],
    requiredEvidence: ["source_file_hash", "schema_hash", "pos_shift_close", "cash_register_z_report", "row_count", "lineage_receipt"],
    presentEvidence: ["source_file_hash", "schema_hash", "pos_shift_close", "cash_register_z_report"],
    routes: intakeRoutes(
      [
        "/api/hydration",
        "/api/operations/petroleum/intake/{receipt_id}/validation",
        "/api/operations/petroleum/intake/{receipt_id}/promotion-preview",
        "/api/operations/petroleum/intake/{receipt_id}/promotion-proposal",
      ],
      [
        "/v1/hydration/ingest",
        "/v1/operations/petroleum/intake/{receipt_id}/validation",
        "/v1/operations/petroleum/intake/{receipt_id}/promotion-preview",
        "/v1/operations/petroleum/intake/{receipt_id}/promotion-proposal",
      ],
      "wired",
    ),
    currentImplementationStatus: "partially-implemented",
    blockedOrMissingContracts: ["Governed RetailSale proposal submission is wired; independent promotion and authentic register connector readback remain open."],
  },
  {
    id: "regulatory_external_evidence",
    label: "Regulatory and external evidence",
    systems: ["regulatory filings", "public registry", "external market/reference sources"],
    requiredScopeDimensions: ["tenant", "legal_entity", "counterparty", "currency", "period", "document", "lineage"],
    implementedScopeDimensions: ["tenant", "legal_entity", "period", "document", "lineage"],
    requiredEvidence: ["source_file_hash", "schema_hash", "regulatory_filing", "external_reference", "lineage_receipt"],
    presentEvidence: ["source_file_hash", "external_reference", "lineage_receipt"],
    routes: intakeRoutes(
      ["/api/ontology/external/*", "/api/ontology/source-documents/*"],
      ["/v1/ontology/external/*", "/v1/ontology/source-documents/*"],
      "proxy-only",
    ),
    currentImplementationStatus: "partially-implemented",
    blockedOrMissingContracts: ["External evidence remains informational until source authority and retention rules are explicit."],
  },
];

export function sourceFamilyById(id: string): SourceFamilyIntakePlan | undefined {
  return SOURCE_FAMILY_INTAKE_PLANS.find((family) => family.id === id);
}

export function missingScopeDimensions(family: SourceFamilyIntakePlan): RequiredScopeDimension[] {
  return family.requiredScopeDimensions.filter((dimension) => !family.implementedScopeDimensions.includes(dimension));
}

export function classifySourceFamily(family: SourceFamilyIntakePlan): SourceFamilyClassification {
  const missingDimensions = missingScopeDimensions(family);
  const missingEvidence = family.requiredEvidence.filter((evidence) => !family.presentEvidence.includes(evidence));
  if (
    missingDimensions.length === 0 &&
    missingEvidence.length === 0 &&
    family.routes.status === "wired" &&
    family.currentImplementationStatus === "implemented" &&
    family.blockedOrMissingContracts.length === 0
  ) {
    return "anchored";
  }
  if (
    family.implementedScopeDimensions.length > 0 &&
    family.presentEvidence.length > 0 &&
    family.routes.status !== "planned" &&
    family.currentImplementationStatus !== "target-only"
  ) {
    return "partial";
  }
  return "target-only";
}

export function missingDimensionsForAnalyst(familyId: string): RequiredScopeDimension[] {
  const family = sourceFamilyById(familyId);
  return family ? missingScopeDimensions(family) : [];
}

export function sourceFamilyIntakeSummary() {
  return {
    families: SOURCE_FAMILY_INTAKE_PLANS.length,
    anchored: SOURCE_FAMILY_INTAKE_PLANS.filter((family) => classifySourceFamily(family) === "anchored").length,
    partial: SOURCE_FAMILY_INTAKE_PLANS.filter((family) => classifySourceFamily(family) === "partial").length,
    targetOnly: SOURCE_FAMILY_INTAKE_PLANS.filter((family) => classifySourceFamily(family) === "target-only").length,
  };
}
