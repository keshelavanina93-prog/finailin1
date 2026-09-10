"use client";

import { useState } from "react";
import type {LearningCandidateTimeline, LearningEvaluation, MultiBaselineOutcome, OutcomeMeasurement, OutcomeMeasurementTimeline} from "@finai/contracts";

type Outcome = OutcomeMeasurement;
type Learning = LearningEvaluation;

export default function OutcomeMeasurementPanel({ token, planScenarioId, actualScenarioId, baselineScenarioIds = [] }: { token: string; planScenarioId: string; actualScenarioId: string; baselineScenarioIds?: string[] }) {
  const [result, setResult] = useState<Outcome | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [learning, setLearning] = useState<Learning | null>(null);
  const [timeline, setTimeline] = useState<OutcomeMeasurementTimeline | null>(null);
  const [candidateTimeline, setCandidateTimeline] = useState<LearningCandidateTimeline | null>(null);
  const [multiBaseline, setMultiBaseline] = useState<MultiBaselineOutcome | null>(null);
  async function measure() {
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/ontology/outcomes/actual-vs-plan?plan_scenario_id=${encodeURIComponent(planScenarioId)}&actual_scenario_id=${encodeURIComponent(actualScenarioId)}`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
      const data = await response.json() as Outcome & { detail?: string };
      if (!response.ok) throw new Error(data.detail ?? "Outcome measurement unavailable");
      setResult(data); await retain(data); await loadTimeline();
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Outcome measurement unavailable"); }
    finally { setBusy(false); }
  }
  async function measureMultiBaseline() {
    const baselines = Array.from(new Set([planScenarioId, ...baselineScenarioIds])).filter(id => id && id !== actualScenarioId).slice(0, 12);
    if (!baselines.length) { setError("Select at least one baseline snapshot."); return; }
    setBusy(true); setError("");
    try {
      const query = new URLSearchParams({ actual_scenario_id: actualScenarioId });
      baselines.forEach(id => query.append("baseline_scenario_id", id));
      const response = await fetch(`/api/ontology/outcomes/multi-baseline?${query.toString()}`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
      const data = await response.json() as MultiBaselineOutcome & { detail?: string };
      if (!response.ok) throw new Error(data.detail ?? "Multi-baseline outcome unavailable");
      setMultiBaseline(data);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Multi-baseline outcome unavailable"); }
    finally { setBusy(false); }
  }
  async function retain(data: Outcome) {
    const response = await fetch("/api/ontology/outcomes/measurements", { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify(data), cache: "no-store" });
    const value = await response.json() as { detail?: string };
    if (!response.ok) throw new Error(value.detail ?? "Outcome retention unavailable");
  }
  async function loadTimeline() {
    const response = await fetch("/api/ontology/outcomes/measurements?limit=20", { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
    const data = await response.json() as OutcomeMeasurementTimeline & { detail?: string };
    if (!response.ok) throw new Error(data.detail ?? "Outcome timeline unavailable");
    setTimeline(data);
  }
  async function evaluateLearning() {
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/ontology/outcomes/learning-evaluation?plan_scenario_id=${encodeURIComponent(planScenarioId)}&actual_scenario_id=${encodeURIComponent(actualScenarioId)}&tolerance=0`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
      const data = await response.json() as Learning & { detail?: string };
      if (!response.ok) throw new Error(data.detail ?? "Learning evaluation unavailable");
      setLearning(data); await retainCandidate(data); await loadCandidateTimeline();
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Learning evaluation unavailable"); }
    finally { setBusy(false); }
  }
  async function retainCandidate(data: Learning) {
    const response = await fetch("/api/ontology/outcomes/learning-candidates", { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify(data), cache: "no-store" });
    const value = await response.json() as { detail?: string };
    if (!response.ok) throw new Error(value.detail ?? "Learning candidate retention unavailable");
  }
  async function loadCandidateTimeline() {
    const response = await fetch("/api/ontology/outcomes/learning-candidates?limit=20", { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
    const data = await response.json() as LearningCandidateTimeline & { detail?: string };
    if (!response.ok) throw new Error(data.detail ?? "Learning candidate timeline unavailable");
    setCandidateTimeline(data);
  }
  return <section className="g8-panel" aria-label="Actual versus plan outcome measurement"><div className="g8-panel-heading"><div><p className="overline">OUTCOME · ACCEPTED FACTS</p><h3>Measure actual versus plan</h3><p>Reads accepted PlanningCellFact values in the selected company scope. Retained measurements are immutable evidence; learning remains shadow-only.</p></div><div><button onClick={() => void measure()} disabled={busy || !planScenarioId || !actualScenarioId}>{busy ? "Measuring…" : "Measure and retain"}</button><button onClick={() => void measureMultiBaseline()} disabled={busy || !actualScenarioId || !([planScenarioId, ...baselineScenarioIds].filter(id => id && id !== actualScenarioId).length)}>Compare multiple baselines</button><button onClick={() => void evaluateLearning()} disabled={busy || !planScenarioId || !actualScenarioId}>Evaluate and retain candidate</button></div></div>{error && <p className="g8-inline-error" role="alert">{error}</p>}{multiBaseline && <section aria-label="Multi-baseline outcome comparison"><h4>Actual against immutable baselines</h4><p>{multiBaseline.comparisons.length} baselines · comparison authorized: {String(multiBaseline.comparison_authorized)} · business effect authorized: {String(multiBaseline.business_effect_authorized)}</p>{multiBaseline.comparisons.map(comparison => <details key={String(comparison.baseline.resource_id)}><summary>{String(comparison.baseline.attributes && (comparison.baseline.attributes as {code?: unknown}).code || comparison.baseline.resource_id)} · {comparison.alignment}</summary><div className="g8-table-scroll"><table><thead><tr><th>Dimension</th><th>Baseline</th><th>Actual</th><th>Variance</th></tr></thead><tbody>{comparison.rows.map(row => <tr key={JSON.stringify(row.dimension)}><td>{Object.entries(row.dimension).filter(([, value]) => value).map(([key, value]) => `${key}: ${value}`).join(" · ")}</td><td>{row.baseline}</td><td>{row.actual}</td><td>{row.variance}</td></tr>)}</tbody></table></div></details>)}</section>}{result && <><p role="status">{result.coverage} · measurement authorized: {String(result.measurement_authorized)} · retained: {timeline?.items.some(item => item.measurement.measurement_id === result.measurement_id) ? "yes" : "pending"}</p><details><summary>Exact outcome readback</summary><dl><dt>Measurement ID</dt><dd><code>{result.measurement_id}</code></dd><dt>Observed at</dt><dd>{new Date(result.observed_at).toLocaleString()}</dd><dt>Legal entity</dt><dd>{result.scope.legal_entity_id}</dd><dt>Scenario pair</dt><dd>{String(result.plan_scenario.resource_id)} → {String(result.actual_scenario.resource_id)}</dd></dl></details>{result.rows.length ? <div className="g8-table-scroll"><table><thead><tr><th>Dimension</th><th>Planned</th><th>Actual</th><th>Variance</th></tr></thead><tbody>{result.rows.map(row => <tr key={JSON.stringify(row.dimension)}><td>{Object.entries(row.dimension).filter(([, value]) => value).map(([key, value]) => `${key}: ${value}`).join(" · ")}</td><td>{row.planned}</td><td>{row.actual}</td><td>{row.variance}</td></tr>)}</tbody></table></div> : <p>No accepted plan/actual cells were found for the selected dimensions.</p>}</>}{timeline && <details><summary>Retained outcome timeline · {timeline.items.length}</summary><ol>{timeline.items.map(item => <li key={item.measurement.measurement_id}><code>{item.measurement.measurement_id}</code> · {new Date(item.recorded_at).toLocaleString()} · <code>{item.content_hash}</code></li>)}</ol></details>}{candidateTimeline && <details><summary>Governed learning candidates · {candidateTimeline.items.length}</summary><ol>{candidateTimeline.items.map(item => <li key={item.event_id}><code>{item.event.candidate_id}</code> · {item.event.event_type} · {new Date(item.recorded_at).toLocaleString()}</li>)}</ol></details>}{learning && <p role="status">Shadow evaluation {learning.status}; candidate {learning.candidate_id}. Promotion approved: no. Execution and rollback remain disabled until independent governance and a separate deployment runtime.</p>}</section>;
}
