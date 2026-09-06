"use client";
import { useEffect, useRef, useState } from "react";

type Measure = { left: string | null; right: string | null; state: string; difference: string | null };
type Comparison = { left_row: string; right_row: string; outline_relation: string; measure_state: string; measures: Record<string, Measure> };
type Result = {
  run_id: string; input_count: number; row_roles: Record<string, number>;
  comparison_counts: Record<string, number>;
  repeated_accounts: { account_code: string; comparisons: Comparison[] }[];
  multirow_documents: { source_rows: string[] }[];
  hierarchy_measure_comparisons: { parent_row: string; measure: string; parent_value: string | null; children_value: string | null; difference: string | null; present_children: number; total_children: number; state: string }[];
  limitations: string[];
};
const label = (value: string) => value.toLowerCase().replaceAll("_", " ");

export default function SourceReconciliation({ token, documentId, sheet, profile, companyId }: {
  token: string; documentId: string; sheet: string; profile: string; companyId: string;
}) {
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), [token, documentId, sheet, profile, companyId]);
  async function reconcile() {
    pending.current?.abort();
    const controller = new AbortController(); pending.current = controller;
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/ontology/source-documents/${documentId}/facts/reconcile`, {
        method: "POST", signal: controller.signal,
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ sheet, profile, company_id: companyId }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Source reconciliation unavailable");
      if (!controller.signal.aborted) setResult(data);
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "Source reconciliation unavailable");
    } finally { if (!controller.signal.aborted) setBusy(false); }
  }
  return <section>
    <h3>Source reconciliation</h3>
    <p>Compare repeated account observations and each outline measure separately. The retained comparison preserves missing values and does not choose a financial total.</p>
    <button disabled={busy || !companyId} onClick={() => void reconcile()}>Reconcile source structure</button>
    {busy && <p role="status">Comparing original source rows…</p>}
    {error && <p role="alert">{error}</p>}
    {result && <>
      <p>{result.input_count.toLocaleString()} retained source rows compared. Financial representation requires review.</p>
      <p>{Object.entries(result.row_roles).map(([role, count]) => `${count.toLocaleString()} ${label(role)}`).join(" · ")}</p>
      {result.repeated_accounts.map(account => <details key={account.account_code}>
        <summary>Account {account.account_code}: {account.comparisons.length} repeated-row comparison(s)</summary>
        {account.comparisons.map(comparison => <div key={`${comparison.left_row}:${comparison.right_row}`}>
          <p>{comparison.left_row} ↔ {comparison.right_row}: {label(comparison.outline_relation)}; {label(comparison.measure_state)}.</p>
          <div className="g8-table-scroll"><table><thead><tr><th>Measure</th><th>First row</th><th>Second row</th><th>Difference</th><th>Comparison</th></tr></thead><tbody>
            {Object.entries(comparison.measures).map(([measure, values]) => <tr key={measure}><td>{label(measure)}</td><td>{values.left ?? "Missing"}</td><td>{values.right ?? "Missing"}</td><td>{values.difference ?? "Not calculated"}</td><td>{label(values.state)}</td></tr>)}
          </tbody></table></div>
        </div>)}
      </details>)}
      {result.hierarchy_measure_comparisons.length > 0 && <details>
        <summary>Outline comparisons: {Object.entries(result.comparison_counts).map(([state, count]) => `${count} ${label(state)}`).join(" · ")}</summary>
        <p>Source outline groups are presentation structures. Even observed agreement does not prove an additive financial hierarchy.</p>
        <div className="g8-table-scroll"><table><thead><tr><th>Parent row</th><th>Measure</th><th>Parent</th><th>Children</th><th>Present children</th><th>Result</th></tr></thead><tbody>
          {result.hierarchy_measure_comparisons.map(item => <tr key={`${item.parent_row}:${item.measure}`}><td>{item.parent_row}</td><td>{label(item.measure)}</td><td>{item.parent_value ?? "Missing"}</td><td>{item.children_value ?? "Not calculated"}</td><td>{item.present_children} / {item.total_children}</td><td>{label(item.state)}</td></tr>)}
        </tbody></table></div>
      </details>}
      {profile === "1c_journal" && <p>{result.multirow_documents.length} source documents have multiple movement rows. Document reference alone does not identify a journal line; all original rows remain separate.</p>}
      <ul>{result.limitations.map(item => <li key={item}>{item}</li>)}</ul>
      <details><summary>Retained comparison receipt</summary><code>{result.run_id}</code></details>
    </>}
  </section>;
}
