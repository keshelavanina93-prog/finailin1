/** Server-observed source membership; no amounts, materiality or posting authority. */
import type { AnalysisPin } from "./semantic-analysis.js";
import type { VersionReference } from "./lifecycle.js";

export type SourceExceptionRequest = {
  company_id: string;
  invocation_id: string;
  journal_snapshot_at: string;
  expected_reconciliation_receipt_hash: string;
  coordinate: string;
};

export type SourceExceptionObservation = {
  contract: "source-reconciliation-exception/1";
  detector: "source-reconciliation-exceptions/1";
  company: AnalysisPin;
  selection: Record<string, VersionReference>;
  context_versions: AnalysisPin[];
  binding: AnalysisPin;
  source_function: AnalysisPin;
  source: {
    invocation_id: string;
    invocation_receipt_hash: string;
    source_receipt_hash: string;
    sha256: string;
    evidence: AnalysisPin;
    document_id: string;
    sheet: string;
    row: number;
    coordinate: string;
  };
  source_valid_at: string;
  source_known_at: string;
  journal_observed_at: string;
  reconciliation: { receipt_hash: string; status: "UNAVAILABLE" | "PARTIAL" | "RECONCILED" };
  financial_impact: null;
  materiality: "UNASSESSED";
  automatic_resolution: false;
  current_use_authorized: false;
  business_effect_authorized: false;
  receipt_hash: string;
} & (
  | { state: "UNMATCHED_AT_SNAPSHOT"; finding_eligible: true; exclusion_reason: null; matched_journals: [] }
  | { state: "MATCHED_AT_SNAPSHOT"; finding_eligible: false; exclusion_reason: null; matched_journals: VersionReference[] }
  | { state: "EXCLUDED_SOURCE_VALUE"; finding_eligible: false; exclusion_reason: string; matched_journals: [] }
);

export type RetainedSourceException = SourceExceptionObservation & {
  run_id: string;
  scope: Record<string, unknown>;
  calculation_runtime: "source-reconciliation-exceptions/1";
  read_permissions: string[];
};

export type InvestigationActionRequest = {
  request_id: string;
  exception_run_id: string;
  rationale: string;
} & (
  | { expected_finding_version_id?: null; expected_investigation_version_id?: null }
  | { expected_finding_version_id: string; expected_investigation_version_id: string }
);

/** Readback from the existing shared Action/proposal authority. */
export type InvestigationOperation = {
  operation_id: string;
  intent_id: string | null;
  intent_request: InvestigationActionRequest | null;
  state: "PREPARED" | "PENDING_REVIEW" | "REJECTED" | "PUBLISHED" | "PUBLICATION_UNAVAILABLE";
  proposal: Record<string, unknown> | null;
  prepared_proposal_id: string;
  definition: Record<string, unknown>;
  events: Record<string, unknown>[];
  finding_id: string;
  investigation_id: string;
  frozen_rationale: string;
  publication: { finding: AnalysisPin; investigation: AnalysisPin } | null;
  publication_limitation: string | null;
  current_use_authorized: false;
  business_effect_authorized: false;
};
