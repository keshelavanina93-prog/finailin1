export type OperationalMeasurementGrain =
  | "ONE_FORECOURT_SALE_LINE"
  | "ONE_METER_MEASUREMENT_AT_ONE_TIME"
  | "ONE_CASH_REGISTER_SHIFT_CLOSE"
  | "ONE_PHYSICAL_MOVEMENT_DOCUMENT_LINE";

export type OperationalValidationStage = "STRUCTURAL_GRAIN" | "SEMANTIC_BINDING";

export type OperationalBindingRow = {
  source_row: number;
  status: "VALIDATED" | "REVIEW_REQUIRED";
  bindings: Record<string, boolean>;
  reasons: string[];
  promotion_eligible: boolean;
};

export type OperationalBindingValidation = {
  contract: "operational-binding-validation/1";
  receipt_id: string;
  profile: string;
  source_system: string;
  grain: OperationalMeasurementGrain;
  validation_stage: "SEMANTIC_BINDING";
  rows: OperationalBindingRow[];
  status: "VALIDATED" | "REVIEW_REQUIRED";
  promotion_eligible: boolean;
  canonical_promotion: "GOVERNED_REVIEW_REQUIRED";
  accounting_authorized: false;
  business_effect_authorized: false;
};

export type OperationalPromotionPreview = {
  contract: "operational-promotion-preview/1";
  receipt_id: string;
  profile: string;
  source_system: string;
  grain: OperationalMeasurementGrain;
  status: "READY_FOR_GOVERNED_PROPOSAL" | "NO_ELIGIBLE_ROWS";
  proposal_required: true;
  canonical_mutation: false;
  accounting_authorized: false;
  business_effect_authorized: false;
  candidates: Array<{
    object_type: string;
    identity_key: string;
    source_row: number;
    values: Record<string, unknown>;
    bindings: Record<string, {resource_id: string; version_id: string}>;
    evidence: {receipt_id: string; source_record_id: string; source_hash: string; valid_at: string};
  }>;
};
