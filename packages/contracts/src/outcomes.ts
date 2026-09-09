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
