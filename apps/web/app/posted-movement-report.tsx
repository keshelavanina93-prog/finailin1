"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {financeReportReference} from "./finance-report-reference";

export type PostedFunction = { resource_id: string; version_id: string; display_name: string };
type Group = { account_code: string; side: string; value: string; source_coordinates: string[] };
type SourceRow = { row: number; attributes: { posting_date: string; source_recorder: string; account_code: string; credit_account_code: string }; cells: Record<string, { value: string; formula: string | null }>; numeric_observations: Record<string, { coordinate: string; literal_decimal: string | null }> };
type RetainedReport = { invocation_id: string; status: string; receipt_hash: string; output?: {
  function?: PostedFunction; query?: {known_at:string};
  source_document: { filename: string; sheet: string;document_id?:string;scope?:{resource_id:string};binding?:{resource_id:string;version_id:string} };
  source_rows: SourceRow[];
  posted_movements: { groups: Group[]; coverage: { source_rows: number; included_rows: number; excluded_rows: number }; excluded_rows: { row: number; coordinate: string; reason: string }[] };
} };

export default function PostedMovementReport({ token, contextKey, functions, currency, eligible,expectedSource,initialInvocationId,onInspectFunction,onTraceFunction }: {
  token: string; contextKey: string; functions: PostedFunction[]; currency: string; eligible: boolean;
  initialInvocationId?:string;
  expectedSource?:{company_id:string;document_id:string;scope_id:string;binding_id:string;binding_version_id:string;ledger_id:string;book_id:string;period_id:string;currency_id:string};
  onInspectFunction?:(reference:{resource_id:string;version_id:string;known_at?:string})=>void;
  onTraceFunction?:(reference:{resource_id:string;version_id:string;known_at?:string})=>void;
}) {
  const [saved, setSaved] = useState<{ key: string; value: RetainedReport; currency:string } | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [page, setPage] = useState(0);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), [contextKey]);
  const report = saved?.key === contextKey ? saved.value : null;
  const output = report?.output;
  const groups = output?.posted_movements.groups ?? [];
  const group = groups.find(row => `${row.account_code}:${row.side}` === selected);
  const excluded = output?.posted_movements.excluded_rows ?? [];
  const rows = output?.source_rows.filter(row => selected === "excluded"
    ? excluded.some(item => item.row === row.row)
    : group?.source_coordinates.includes(row.numeric_observations.source_amount?.coordinate)) ?? [];

  const expectedKey=JSON.stringify(expectedSource);
  const run=useCallback(async(functionRef?: PostedFunction,reopenId?:string) => {
    pending.current?.abort();
    const controller = new AbortController(); pending.current = controller;
    setBusy(true); setError("");
    const timer=setTimeout(()=>controller.abort(),20000);
    try {
      const now = new Date().toISOString();
      const response = await fetch(functionRef ? "/api/ontology/functions/invocations"
        : `/api/ontology/functions/invocations/${encodeURIComponent(reopenId??"")}`, {
        method: functionRef ? "POST" : "GET", signal: controller.signal,
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        ...(functionRef ? { body: JSON.stringify({ function: { resource_id: functionRef.resource_id,
          version_id: functionRef.version_id }, valid_at: now, known_at: now }) } : {}),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Calculation unavailable");
      if (!financeReportReference(data)) throw new Error("The guarded calculation did not complete. No totals were released.");
      const expected:typeof expectedSource=expectedKey?JSON.parse(expectedKey):undefined;
      const source=data.output.source_document;
      if(reopenId&&data.invocation_id!==reopenId)throw new Error("The saved report reference did not match.");
      if(expected&&(source.company_id!==expected.company_id||source.document_id!==expected.document_id||source.scope?.resource_id!==expected.scope_id||source.binding?.resource_id!==expected.binding_id||source.binding?.version_id!==expected.binding_version_id||["ledger_id","book_id","period_id","currency_id"].some(field=>source.context?.[field]!==expected[field as keyof typeof expected])))throw new Error("The retained report does not match this reviewed company, period and currency. Review its original accounting context.");
      if(functionRef&&(data.output.function?.resource_id!==functionRef.resource_id||data.output.function?.version_id!==functionRef.version_id))throw new Error("The calculation did not return the selected Function version.");
      if (controller.signal.aborted) return;
      setSaved({ key: contextKey, value: data,currency });
      if (functionRef) { setSelected(null); setPage(0); }
    } catch (failure) {
      if(pending.current===controller)setError(controller.signal.aborted?"The report request timed out. Reopen its retained result or retry.":failure instanceof Error ? failure.message : "Report unavailable");
    } finally { clearTimeout(timer);if(pending.current===controller)setBusy(false); }
  },[token,contextKey,expectedKey,currency]);
  // State updates follow the retained API response.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(()=>{if(initialInvocationId)void run(undefined,initialInvocationId);},[initialInvocationId,run]);

  return <section aria-label="Posted account movements">
    <h3>Posted account movements · {saved?.key===contextKey?saved.currency:currency}</h3>
    <p>Amounts as posted in Сумма. VAT is not recalculated. Amount is preserved separately and excluded from totals.</p>
    {functions.map(item => <button key={item.version_id} disabled={busy || !eligible} onClick={() => void run(item)}>
      {functions.length === 1 ? "Calculate posted account movements" : item.display_name}
    </button>)}
    {!functions.length && <p>A reviewed calculation is not available for this source yet.</p>}
    {busy && <p role="status">Checking reviewed inputs and calculating retained postings…</p>}
    {error && <p role="alert">{error}</p>}
    {output && <>
      <p><strong>Partial source coverage:</strong> {output.posted_movements.coverage.included_rows} of {output.posted_movements.coverage.source_rows} rows included. Full-ledger completeness and financial-statement classification are not established.</p>
      <button disabled={busy} onClick={() => void run(undefined,report.invocation_id)}>Reopen saved report</button>
      {excluded.length > 0 && <button onClick={() => { setSelected("excluded"); setPage(0); }}>Inspect {excluded.length} excluded row{excluded.length === 1 ? "" : "s"}</button>}
      <div style={{ overflow: "auto",maxHeight:440 }}><table><caption>{output.source_document.filename} · exact posted amounts in {saved?.currency}</caption>
        <thead><tr><th>Account</th><th>Posting side</th><th>Amount</th><th>Evidence</th></tr></thead>
        <tbody>{groups.map(row => <tr key={`${row.account_code}:${row.side}`}>
          <th scope="row">{row.account_code}</th><td>{row.side === "debit" ? "Debit" : "Credit"}</td><td>{row.value}</td>
          <td><button onClick={() => { setSelected(`${row.account_code}:${row.side}`); setPage(0); }}>Inspect {row.source_coordinates.length} source rows</button></td>
        </tr>)}</tbody>
      </table></div>
      {selected && <section aria-label="Posted movement source contributors"><h4>{selected === "excluded" ? "Excluded source rows" : `Account ${group?.account_code} · ${group?.side} contributors`}</h4>
        {selected === "excluded" && <p>The posted amount is missing or is not a literal source number. No supplementary value or zero was substituted.</p>}
        {selected === "excluded" && excluded.map(item => <p key={item.row}><strong>{item.coordinate}</strong>: no literal posted amount.</p>)}
        {rows.slice(page * 20, (page + 1) * 20).map(row => <details key={row.row}><summary>{output.source_document.sheet}!{row.row} · {row.attributes.posting_date} · {row.attributes.source_recorder}</summary>
          <p>Debit {row.attributes.account_code} · Credit {row.attributes.credit_account_code}</p>
          <div style={{ overflowX: "auto" }}><table><caption>Original retained cells</caption><thead><tr><th>Source cell</th><th>Recorded value</th><th>Source formula</th></tr></thead><tbody>
            {Object.entries(row.cells).map(([coordinate, cell]) => <tr key={coordinate}><th scope="row">{coordinate}</th><td>{cell.value || "Not recorded"}</td><td>{cell.formula ?? "—"}</td></tr>)}
          </tbody></table></div>
        </details>)}
        <button disabled={page === 0} onClick={() => setPage(value => value - 1)}>Previous source rows</button>
        <button disabled={(page + 1) * 20 >= rows.length} onClick={() => setPage(value => value + 1)}>Next source rows</button>
      </section>}
      <details><summary>Saved calculation evidence</summary><p>Invocation: {report.invocation_id}</p><p>Receipt: {report.receipt_hash}</p><p>This is retained calculation evidence. Reopening it does not authorize new accounting use.</p></details>
      {output.function&&<p>{onInspectFunction&&<button onClick={()=>onInspectFunction({...output.function!,known_at:output.query?.known_at})}>Explain calculation in NYX</button>}{onTraceFunction&&<button onClick={()=>onTraceFunction({...output.function!,known_at:output.query?.known_at})}>Show Function system trace</button>}</p>}
    </>}
  </section>;
}
