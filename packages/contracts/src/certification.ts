import type { VersionReference } from "./lifecycle.js";

/** Technical definition conformance only; this does not authorize business use. */
export interface CertificationDefinition {
  claim: "CANONICAL_DEFINITION_CONFORMANCE";
  evaluator: "canonical-structural-contract/v1";
  subject_type: string;
  required_checks: Array<"schema compatibility" | "identity cycles" | "dependency version pins" | "impact">;
  meaning: string;
  limitations: string;
}

export interface CertificationContract {
  definition: CertificationDefinition;
  subject_schema_id?: string | null;
  evidence_id?: string | null;
}

export interface CertificationEvaluationRequest {
  request_id?: string;
  subject: VersionReference;
  contract: VersionReference;
}

export interface DefinitionConformanceReceipt {
  receipt_id: string;
  proof_hash: string;
  recorded_at: string;
  current_use_authorized: false;
  proof: {
    purpose: "CANONICAL_DEFINITION_CONFORMANCE";
    evaluator: "canonical-structural-contract/v1";
    status: "PASS";
    subject: VersionReference;
    contract: VersionReference;
    subject_content_hash: string;
    contract_content_hash: string;
    access_entity: string;
    contract_attributes: CertificationContract;
    subject_schema: VersionReference | null;
    promotion_proposal_id: string;
    promotion_evaluation: {
      evaluator: string;
      proposal_hash: string;
      binding_hash: string;
      status: "PASS";
      expectations: Array<{name: string; status: "PASS" | "FAIL"}>;
      recorded_at: string;
      checks: string[];
      scope: string;
    };
    subject_upstream: ConformanceDependency[];
    contract_upstream: ConformanceDependency[];
  };
}

export interface ConformanceDependency extends VersionReference {
  content_hash: string;
  access_entity: string;
  event_id: string | null;
}
