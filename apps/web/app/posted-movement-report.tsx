"use client";

import { useEffect, useRef, useState } from "react";

export type PostedFunction = { resource_id: string; version_id: string; display_name: string };
type Group = { account_code: string; side: string; value: string; source_coordinates: string[] };
type SourceRow = { row: number; attributes: { posting_date: string; source_recorder: string; account_code: string; credit_account_code: string }; cells: Record<string, { value: string; formula: string | null }>; numeric_observations: Record<string, { coordinate: string; literal_decimal: string | null }> };
type RetainedReport = { invocation_id: string; status: string; receipt_hash: string; output?: {
  source_document: { filename: string; sheet: string };
  source_rows: SourceRow[];
  posted_movements: { groups: Group[]; coverage: { source_rows: number; included_rows: number; excluded_rows: number }; excluded_rows: { row: number; coordinate: string; reason: string }[] };
} };

export default function PostedMovementReport({ token, contextKey, functions, currency, eligible }: {
  token: string; contextKey: string; functions: PostedFunction[]; currency: string; eligible: boolean;
}) {
  const [saved, setSaved] = useState<{ key: string; value: RetainedReport } | null>(null);
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

  async function run(functionRef?: PostedFunction) {
    pending.current?.abort();
    const controller = new AbortController(); pending.current = controller;
    setBusy(true); setError("");
    try {
      const now = new Date().toISOString();
      const response = await fetch(functionRef ? "/api/ontology/functions/invocations"
        : `/api/ontology/functions/invocations/${report?.invocation_id}`, {
        method: functionRef ? "POST" : "GET", signal: controller.signal,
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        ...(functionRef ? { body: JSON.stringify({ function: { resource_id: functionRef.resource_id,
          version_id: functionRef.version_id }, valid_at: now, known_at: now }) } : {}),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Calculation unavailable");
      if (data.status !== "SUCCEEDED" || !data.output?.posted_movements) throw new Error("The guarded calculation did not complete. No totals were released.");
      if (controller.signal.aborted) return;
      setSaved({ key: contextKey, value: data });
      if (functionRef) { setSelected(null); setPage(0); }
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "Report unavailable");
    } finally { if (!controller.signal.aborted) setBusy(false); }
  }

  return <section aria-label="Posted account movements">
    <h3>Posted account movements · {currency}</h3>
    <p>Amounts as posted in Сумма. VAT is not recalculated. Amount is preserved separately and excluded from totals.</p>
    {functions.map(item => <button key={item.version_id} disabled={busy || !eligible} onClick={() => void run(item)}>
      {functions.length === 1 ? "Calculate posted account movements" : item.display_name}
    </button>)}
    {!functions.length && <p>A reviewed calculation is not available for this source yet.</p>}
    {busy && <p role="status">Checking reviewed inputs and calculating retained postings…</p>}
    {error && <p role="alert">{error}</p>}
    {output && <>
      <p><strong>Partial source coverage:</strong> {output.posted_movements.coverage.included_rows} of {output.posted_movements.coverage.source_rows} rows included. Full-ledger completeness and financial-statement classification are not established.</p>
      <button disabled={busy} onClick={() => void run()}>Reopen saved report</button>
      {excluded.length > 0 && <button onClick={() => { setSelected("excluded"); setPage(0); }}>Inspect {excluded.length} excluded row{excluded.length === 1 ? "" : "s"}</button>}
      <div style={{ overflowX: "auto" }}><table><caption>{output.source_document.filename} · exact posted amounts in {currency}</caption>
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
    </>}
  </section>;
}
