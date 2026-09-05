"use client";

import { useState } from "react";
type Metric = { id: string; amount: string | null; dependencies: string[]; reason?: string };
type Calculation = { calculation_id: string; explanation: string; metrics: Metric[]; facts: Array<{ source_sheet: string; source_row: number; label: string; metric: string; amount: string; coordinates: string[] }>; comparisons: Array<{ metric: string; coordinate: string; legacy_cached: string; calculated: string | null; difference: string | null }>; missing_requirements: string[] };
const money = (value: string | null) => value === null ? "Unavailable" : Number(value).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export default function OperatingReport({ token, receiptId }: { token: string; receiptId: string }) {
  const [result, setResult] = useState<Calculation | null>(null);
  const [selected, setSelected] = useState("revenue.total");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function download() {
    if (!result) return;
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/workspace/report-calculations/${result.calculation_id}/export`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
      if (!response.ok) throw new Error("Report download failed");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a"); link.href = url; link.download = "Operating-PL-reference.xlsx"; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Report download failed"); }
    finally { setBusy(false); }
  }
  async function calculate() {
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/workspace/report-calculations", { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ receipt_id: receiptId }) });
      const payload = await response.json();
      if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "Calculation failed");
      setResult(payload);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Calculation failed"); }
    finally { setBusy(false); }
  }
  const metric = result?.metrics.find(item => item.id === selected);
  const rows = result?.facts.filter(item => item.metric === selected) ?? [];
  return <section className="data-panel" aria-label="Operating report calculation"><div className="section-heading"><div><h3>Operating P&L reconstruction</h3><p>Calculate the supplied product rules and compare them with the original report. Reference results stay separate from approved financial statements.</p></div><button disabled={busy} onClick={() => void calculate()}>{busy ? "Calculating…" : "Calculate & compare"}</button></div>
    {error && <p role="alert">{error}</p>}
    {result && <button className="quiet" disabled={busy} onClick={() => void download()}>Download Excel with source lineage</button>}
    {result && <><p>{result.explanation}</p><div className="tb-data tb-data-selected"><div className="tb-table-wrap"><table><thead><tr><th>Report line</th><th>Source units</th><th>Trace</th></tr></thead><tbody>{result.metrics.map(item => <tr key={item.id}><td>{item.id.replaceAll(".", " / ").replaceAll("_", " ")}</td><td>{money(item.amount)}</td><td><button className="quiet" onClick={() => setSelected(item.id)}>Inspect inputs</button></td></tr>)}</tbody></table></div><aside className="tb-inspector"><h4>{selected.replaceAll(".", " / ")}</h4><p>{money(metric?.amount ?? null)}</p><p>{metric?.reason}</p><h4>Connected inputs</h4>{metric?.dependencies.filter(id => !id.startsWith("row:")).map(id => <p key={id}><button className="quiet" onClick={() => setSelected(id)}>{id} →</button></p>)}{rows.map(row => <details key={`${row.source_sheet}:${row.source_row}`}><summary>{row.label} · {money(row.amount)}</summary><p>{row.coordinates.join(", ")}</p><p>Proposed source-specific product classification</p></details>)}{!metric?.dependencies.length && <p>No eligible source connections established.</p>}</aside></div><h4>Comparison with workbook values</h4><table><thead><tr><th>Line</th><th>Workbook cell</th><th>Original cached amount</th><th>Calculated</th><th>Difference</th></tr></thead><tbody>{result.comparisons.map(item => <tr key={item.metric}><td>{item.metric}</td><td>{item.coordinate}</td><td>{money(item.legacy_cached)}</td><td>{money(item.calculated)}</td><td>{money(item.difference)}</td></tr>)}</tbody></table><details><summary>Requirements before publishing financial results</summary>{result.missing_requirements.map(item => <p key={item}>{item}</p>)}<small>Saved calculation {result.calculation_id}</small></details></>}
  </section>;
}
