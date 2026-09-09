"use client";

import { useState } from "react";

type Outcome = {
  contract: "outcome-measurement/1";
  rows: Array<{ dimension: Record<string, string>; planned: string; actual: string; variance: string }>;
  coverage: string;
  measurement_authorized: boolean;
  learning_candidate_created: boolean;
};
type Learning = { contract: "learning-evaluation/1"; candidate_id: string; status: string; tolerance: string; promotion_required: boolean; production_policy_changed: false; production_model_changed: false };

export default function OutcomeMeasurementPanel({ token, planScenarioId, actualScenarioId }: { token: string; planScenarioId: string; actualScenarioId: string }) {
  const [result, setResult] = useState<Outcome | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [learning, setLearning] = useState<Learning | null>(null);
  async function measure() {
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/ontology/outcomes/actual-vs-plan?plan_scenario_id=${encodeURIComponent(planScenarioId)}&actual_scenario_id=${encodeURIComponent(actualScenarioId)}`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
      const data = await response.json() as Outcome & { detail?: string };
      if (!response.ok) throw new Error(data.detail ?? "Outcome measurement unavailable");
      setResult(data);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Outcome measurement unavailable"); }
    finally { setBusy(false); }
  }
  async function evaluateLearning() {
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/ontology/outcomes/learning-evaluation?plan_scenario_id=${encodeURIComponent(planScenarioId)}&actual_scenario_id=${encodeURIComponent(actualScenarioId)}&tolerance=0`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
      const data = await response.json() as Learning & { detail?: string };
      if (!response.ok) throw new Error(data.detail ?? "Learning evaluation unavailable");
      setLearning(data);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Learning evaluation unavailable"); }
    finally { setBusy(false); }
  }
  return <section className="g8-panel" aria-label="Actual versus plan outcome measurement"><div className="g8-panel-heading"><div><p className="overline">OUTCOME · ACCEPTED FACTS</p><h3>Measure actual versus plan</h3><p>Reads accepted PlanningCellFact values in the selected company scope. It creates no learning candidate and changes no policy or model.</p></div><div><button onClick={() => void measure()} disabled={busy || !planScenarioId || !actualScenarioId}>{busy ? "Measuring…" : "Measure outcome"}</button><button onClick={() => void evaluateLearning()} disabled={busy || !planScenarioId || !actualScenarioId}>Evaluate in shadow</button></div></div>{error && <p className="g8-inline-error" role="alert">{error}</p>}{result && <><p role="status">{result.coverage} · measurement authorized: {String(result.measurement_authorized)} · learning candidate created: {String(result.learning_candidate_created)}</p>{result.rows.length ? <div className="g8-table-scroll"><table><thead><tr><th>Dimension</th><th>Planned</th><th>Actual</th><th>Variance</th></tr></thead><tbody>{result.rows.map(row => <tr key={JSON.stringify(row.dimension)}><td>{Object.entries(row.dimension).filter(([, value]) => value).map(([key, value]) => `${key}: ${value}`).join(" · ")}</td><td>{row.planned}</td><td>{row.actual}</td><td>{row.variance}</td></tr>)}</tbody></table></div> : <p>No accepted plan/actual cells were found for the selected dimensions.</p>}</>}{learning && <p role="status">Shadow evaluation {learning.status}; candidate {learning.candidate_id}. Promotion required: {String(learning.promotion_required)}. Production policy/model changed: {String(learning.production_policy_changed)}/{String(learning.production_model_changed)}.</p>}</section>;
}
