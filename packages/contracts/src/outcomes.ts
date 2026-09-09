export type OutcomeDimensionRow = {
  dimension: Record<string, string>;
  planned: string;
  actual: string;
  variance: string;
};

export type OutcomeMeasurement = {
  contract: "outcome-measurement/1";
  measurement_id: string;
  observed_at: string;
  scope: {legal_entity_id: string};
  plan_scenario: Record<string, unknown>;
  actual_scenario: Record<string, unknown>;
  rows: OutcomeDimensionRow[];
  coverage: "ACCEPTED_PLANNING_CELL_FACTS";
  measurement_authorized: true;
  learning_candidate_created: false;
  policy_or_model_changed: false;
  business_effect_authorized: false;
};

export type LearningEvaluation = {
  contract: "learning-evaluation/1";
  candidate_id: string;
  measurement: OutcomeMeasurement & {
    rows: Array<OutcomeDimensionRow & {absolute_variance: string; within_tolerance: boolean}>;
  };
  status: "SHADOW_PASS" | "SHADOW_REVIEW_REQUIRED";
  tolerance: string;
  promotion_required: true;
  production_policy_changed: false;
  production_model_changed: false;
  business_effect_authorized: false;
};

export type RetainedOutcomeMeasurement = {
  measurement: OutcomeMeasurement;
  content_hash: string;
  recorded_at: string;
};

export type OutcomeMeasurementTimeline = {
  contract: "outcome-measurement-timeline/1";
  scope: {legal_entity_id: string};
  items: RetainedOutcomeMeasurement[];
  limit: number;
};

export type LearningCandidateEvent = {
  contract: "learning-candidate-event/1";
  candidate_id: string;
  event_type: "EVALUATED" | "PROMOTION_APPROVED" | "REJECTED" | "ROLLBACK_APPROVED";
  [key: string]: unknown;
};

export type LearningCandidateTimeline = {
  contract: "learning-candidate-timeline/1";
  scope: {legal_entity_id: string};
  items: Array<{event: LearningCandidateEvent; event_id: string; content_hash: string; recorded_at: string}>;
  limit: number;
};
