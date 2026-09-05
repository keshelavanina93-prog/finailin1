"use client";

import { useState, type FormEvent } from "react";
import type { Principal } from "@finai/contracts";
import ReportWorkflow from "./report-workflow";

type Assessment = { assessment_id: string; explanation: string; target: { period: string; company_label: string; currency: string; receipt_ids: string[] }; lines: Array<{ line: string; reason: string; required_source_types: string[]; source_candidates: Array<{ sheet: string; excluded_reasons: string[] }> }> };

export default function ReportInputs({ token, principal }: { token: string; principal: Principal }) {
  const [result, setResult] = useState<Assessment | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function call(path: string, body?: unknown) {
    const response = await fetch(`/api/workspace/${path}`, { method: body ? "POST" : "GET", cache: "no-store", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, ...(body ? { body: JSON.stringify(body) } : {}) });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Assessment unavailable");
    return data;
  }
  async function assess(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const fields = new FormData(event.currentTarget); setBusy(true); setError("");
    try {
      const sources = await call("intake") as Array<{ receipt_id: string }>;
      if (!sources.length) throw new Error("Retain source examples or current facts first.");
      setResult(await call("report-inputs", { period: fields.get("period"), company_label: fields.get("company"), currency: fields.get("currency"), receipt_ids: sources.map(source => source.receipt_id) }) as Assessment);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Assessment failed"); }
    finally { setBusy(false); }
  }
  async function reopen() {
    setBusy(true); setError("");
    try { const history = await call("report-inputs") as Assessment[]; setResult(history[0] ?? null); if (!history.length) setError("No saved assessment in this scope."); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "History unavailable"); }
    finally { setBusy(false); }
  }
  return <section className="data-panel" aria-label="Report source coverage">
    <h3>Can these sources support my report?</h3><p>Assess the latest retained uploads in this authorized scope. Historical examples and templates remain separate from report facts.</p>
    <form onSubmit={assess} className="upload-strip"><label>Requested month<input name="period" type="month" defaultValue={principal.scope.period} required /></label><label>Source company label<input name="company" defaultValue={principal.scope.legal_entity_id} maxLength={256} required /></label><label>Report currency<input name="currency" defaultValue={principal.scope.currency} pattern="[A-Z]{3}" required /></label><button disabled={busy}>Assess and save coverage</button><button type="button" className="quiet" disabled={busy} onClick={() => void reopen()}>Reopen latest assessment</button></form>
    {error && <p role="alert">{error}</p>}
    {result && <><h4>{result.target.company_label} · {result.target.period}</h4><p>{result.explanation}</p><div className="data-scroll"><table><thead><tr><th>Report output</th><th>Required evidence</th><th>Current gap</th></tr></thead><tbody>{result.lines.map(line => <tr key={line.line}><td>{line.line}</td><td>{line.required_source_types.join(" or ")}</td><td>{line.source_candidates.length ? line.source_candidates.map((source, index) => <p key={index}>{source.sheet}: {source.excluded_reasons.join(", ")}</p>) : "Required source type missing"}</td></tr>)}</tbody></table></div><small>Saved assessment {result.assessment_id}</small><ReportWorkflow token={token} report={result.target} /></>}
  </section>;
}
