"use client";
import { useEffect, useRef, useState } from "react";
type Resource = { resource_id: string; version_id: string; display_name: string; attributes: Record<string, string> };
type Context = { scope_id: string; observed: Record<string, string>; scope: Resource | null; binding: Resource | null; candidates: Record<string, Resource[]> };
export default function SourceAccountingContext({ token, documentId, sheet, profile, companyId, canPropose, onProposal }: {
  token: string; documentId: string; sheet: string; profile: string; companyId: string; canPropose: boolean; onProposal: (id: string) => void;
}) {
  const [context, setContext] = useState<Context | null>(null);
  const [use, setUse] = useState(""); const [selection, setSelection] = useState<Record<string, string>>({});
  const [rationale, setRationale] = useState(""); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), [token, documentId, sheet, profile, companyId]);
  async function run(action: "inspect" | "scope-proposal" | "binding-proposal") {
    pending.current?.abort(); const controller = new AbortController(); pending.current = controller;
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/ontology/source-documents/${documentId}/accounting-context/${action}`, {
        method: "POST", signal: controller.signal,
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ sheet, profile, company_id: companyId,
          ...(action === "binding-proposal" ? { selection: { source_use: use, rationale,
            ...(use === "ACCOUNTING_INPUT" ? selection : {}) } } : {}) }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Accounting context rejected");
      if (controller.signal.aborted) return;
      if (action !== "inspect") onProposal(data.proposal.proposal_id);
      else { setContext(data); setUse(data.binding?.attributes.source_use ?? "");
        setRationale(data.binding?.attributes.rationale ?? "");
        setSelection(Object.fromEntries(["ledger_id", "book_id", "period_id", "currency_id", "currency_role"].flatMap(key => data.binding?.attributes[key] ? [[key, data.binding.attributes[key]]] : []))); }
    } catch (failure) { if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "Accounting context unavailable"); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  const ledger = context?.candidates.Ledger.find(r => r.resource_id === selection.ledger_id);
  const choices: [string, string, Resource[]][] = context ? [
    ["ledger_id", "Ledger", context.candidates.Ledger],
    ["book_id", "Accounting book", context.candidates.AccountingBook.filter(r => r.attributes.ledger_id === selection.ledger_id)],
    ["period_id", "Fiscal period", context.candidates.FiscalPeriod.filter(r => ledger && r.attributes.calendar_id === ledger.attributes.calendar_id && r.attributes.starts_on <= context.observed.observed_from && r.attributes.ends_on >= context.observed.observed_through)],
    ["currency_id", "Source amount currency", context.candidates.Currency],
  ] : [];
  const complete = use === "STRUCTURAL_REFERENCE" || (use === "ACCOUNTING_INPUT" && ["ledger_id", "book_id", "period_id", "currency_id", "currency_role"].every(key => selection[key]));
  return <section><h3>Source accounting context</h3>
    <p>Review the source company and dates, then decide whether this file is a structural reference or an accounting input.</p>
    <button disabled={busy} onClick={() => void run("inspect")}>Inspect source accounting context</button>
    {busy && <p role="status">Resolving source accounting context…</p>}{error && <p role="alert">{error}</p>}
    {context && <>
      <p>{context.observed.observed_from} → {context.observed.observed_through} · {context.observed.date_basis === "EXPLICIT_REPORT_PERIOD" ? "Period explicitly stated in the report" : "Extent of observed movement dates"}.</p>
      <p>Source completeness is unestablished. Ledger, book and currency are separate reviewed choices.</p>
      <p>Observed scope: {context.scope ? "Published" : "Awaiting publication"}. Accounting use: {context.binding ? context.binding.attributes.source_use.toLowerCase().replaceAll("_", " ") : "Not selected"}.</p>
      {!context.scope && canPropose && <button disabled={busy} onClick={() => void run("scope-proposal")}>Propose observed source scope</button>}
      {context.scope && <>
        <label htmlFor="source-accounting-use">Source use</label><select id="source-accounting-use" value={use} onChange={e => setUse(e.target.value)}><option value="">Select accounting use</option><option value="STRUCTURAL_REFERENCE">Structural reference</option><option value="ACCOUNTING_INPUT">Accounting input</option></select>
        {use === "ACCOUNTING_INPUT" && <>
          {!context.candidates.Ledger.length && <p>No reviewed ledger matches this company and chart. Register the company accounting context before activating this source.</p>}
          {choices.map(([key, label, rows]) => <div key={key}><label htmlFor={`source-context-${key}`}>{label}</label><select id={`source-context-${key}`} value={selection[key] ?? ""} onChange={e => setSelection(previous => key === "ledger_id" ? { ...previous, ledger_id: e.target.value, book_id: "", period_id: "" } : { ...previous, [key]: e.target.value })}><option value="">Select {label.toLowerCase()}</option>{rows.map(row => <option key={row.resource_id} value={row.resource_id}>{row.display_name}</option>)}</select></div>)}
          <label htmlFor="source-currency-role">Currency role</label><select id="source-currency-role" value={selection.currency_role ?? ""} onChange={e => setSelection(previous => ({ ...previous, currency_role: e.target.value }))}><option value="">Select currency role</option><option value="FUNCTIONAL">Functional</option><option value="TRANSACTION">Transaction</option><option value="PRESENTATION">Presentation</option></select>
        </>}
        <label htmlFor="source-context-rationale">Basis for this choice</label><textarea id="source-context-rationale" value={rationale} onChange={e => setRationale(e.target.value)} maxLength={2000}/>
        {canPropose && <button disabled={busy || !complete || rationale.trim().length < 10} onClick={() => void run("binding-proposal")}>Propose accounting context for review</button>}
      </>}
    </>}
  </section>;
}
