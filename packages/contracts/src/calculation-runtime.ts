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
