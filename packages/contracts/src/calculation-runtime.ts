export type CalculationCompilePlan = {
  graph_id: string;
  graph_version: string;
  selected_node_ids: string[];
  stages: string[][];
  affected_coordinates: Array<{values: Array<[string, string]>}>;
  block_ids: string[];
  state: "CALCULATION_FRESH" | "DIRTY" | "RECALCULATING" | "BLOCKED" | "STALE" | "SUPERSEDED" | "FAILED";
  plan_hash: string;
  refusal_reason: string | null;
};

export type CalculationCompileResponse = {
  contract: "calculation-compile/1";
  plan: CalculationCompilePlan;
  authority_effect: "NONE";
  execution_performed: false;
};

export type SparseCalculationCell = {
  node_id: string;
  coordinate: {values: Array<[string, string]>};
  value: string;
};

export type CalculationExecuteResponse = {
  contract: "calculation-execute/1";
  result: {
    plan: CalculationCompilePlan;
    cells: SparseCalculationCell[];
    state: CalculationCompilePlan["state"];
    target: string;
    input_pins: string[];
    valid_at: string | null;
    known_at: string | null;
    authority_state: "DERIVED_CANDIDATE";
    accounting_authorized: false;
    business_effect_authorized: false;
    reproducibility_hash: string;
    refusal_reason: string | null;
  };
  authority_effect: "NONE";
  execution_performed: boolean;
};
