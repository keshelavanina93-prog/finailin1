/** Exact retained evidence. Values are decimal strings; no client-side aggregation. */
import type { AnalysisPin } from "./semantic-analysis.js";
export type MetricPin = AnalysisPin;
export type MetricUnit = { kind: "COUNT"; symbol: "objects" } | { kind: "CURRENCY"; reference: MetricPin };
export type MetricSelector = { kind: "OBJECT_COUNT"; company_field?: string | null } | { kind: "MEASURE"; key: string };
export type MetricDefinition = {
  contract: "metric-definition/1"; selector: MetricSelector; unit: MetricUnit;
  grain: string; dimensions: string[]; aggregation: "non_additive";
};
export type MetricOutput = {
  key: string; unit: MetricUnit; grain: string; dimensions: string[];
  company: MetricPin | null; valid_at: string; known_at: string;
  coverage: "COMPLETE" | "PARTIAL"; contributors: MetricPin[];
} & ({ state: "VALUE"; value: string } | { state: "UNAVAILABLE"; value: null });
export type MetricObservationRequest = {
  metric: MetricPin; invocation_id: string; expected_receipt_hash: string;
  valid_at: string; known_at: string;
};
export type MetricObservation = {
  contract: "metric-observation/1"; calculation_runtime: "metric-observations/1";
  run_id: string; metric: MetricPin; function: MetricPin; invocation_id: string;
  input_run_id: string; input_receipt_hash: string; input_plan_hash: string;
  definition: MetricDefinition; observation: MetricOutput; source_result: Record<string, unknown>;
  current_use_authorized: false; business_effect_authorized: false;
};
