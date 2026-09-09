"use client";

import { useState } from "react";

export default function ScenarioProposalPanel({ token, companyId, enabled }: { token: string; companyId: string; enabled: boolean }) {
  const [code, setCode] = useState("");
  const [kind, setKind] = useState<"BUDGET" | "FORECAST" | "ADJUSTMENT">("FORECAST");
  const [amount, setAmount] = useState("");
  const [article, setArticle] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    const today = new Date().toISOString().slice(0, 10);
    try {
      const response = await fetch("/api/ontology/planning/proposals", { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ code, kind, valid_from: new Date().toISOString(), rationale: `Create reviewed ${kind.toLowerCase()} scenario ${code} for controlled planning analysis.`, cells: [{ budget_article_id: article, period_id: today.slice(0, 7), period_starts_on: `${today.slice(0, 7)}-01`, period_ends_on: today, department_id: companyId, measure: "GEL", source_family: "MANUAL_PLANNING", amount, currency_id: "GEL", scale: 2 }] }) });
      const data = await response.json() as { detail?: string; proposal?: { proposal_id?: string } };
      if (!response.ok) throw new Error(data.detail ?? "Scenario proposal unavailable");
      setMessage(`Proposal ${data.proposal?.proposal_id ?? "recorded"} submitted for independent review.`);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Scenario proposal unavailable"); }
    finally { setBusy(false); }
  }
  return <section className="g8-panel" aria-label="Scenario proposal editor"><div className="g8-panel-heading"><div><p className="overline">PLANNING · GOVERNED AUTHORING</p><h3>Propose a scenario</h3><p>Creates a pending ScenarioVersion and PlanningCellFact change set. A second reviewer must approve it before it becomes accepted planning truth.</p></div></div><form onSubmit={submit} className="g8-actionbar"><label>Code<input value={code} onChange={event => setCode(event.target.value)} minLength={1} maxLength={128} required /></label><label>Kind<select value={kind} onChange={event => setKind(event.target.value as typeof kind)}><option>BUDGET</option><option>FORECAST</option><option>ADJUSTMENT</option></select></label><label>Budget article<input value={article} onChange={event => setArticle(event.target.value)} required /></label><label>Amount<input value={amount} onChange={event => setAmount(event.target.value)} pattern="^-?\d{1,40}(\.\d{1,8})?$" required /></label><button disabled={!enabled || busy}>{!enabled ? "Proposal permission required" : busy ? "Submitting…" : "Submit for review"}</button></form>{error && <p className="g8-inline-error" role="alert">{error}</p>}{message && <p role="status">{message}</p>}</section>;
}
