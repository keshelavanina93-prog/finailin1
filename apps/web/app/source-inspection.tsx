"use client";

import type { IngestReceipt, ReviewDecision } from "@finai/contracts";

export default function SourceInspection({ receipt, decision }: { receipt: IngestReceipt; decision?: ReviewDecision | null }) {
  const profile = receipt.source_profile;
  const proof = (profile as unknown as { aggregation_proof?: {
    state: string; selected_rows: number[]; account_totals: Record<string, string>;
    source_total_residuals: Record<string, string>; naive_sum_overstatement: Record<string, string>;
    hierarchy_checks: Array<{ parent_row: number; state: string; residuals: Record<string, string> }>;
    policy: string;
  } } | undefined)?.aggregation_proof;
  return <section aria-label="Source analysis and persisted process">
    <h3>Upload process</h3>
    <p>Recorded execution and retained review state. Financial report generation remains unavailable until its source contracts are approved.</p>
    <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
      {(receipt.process_steps ?? []).map(step => <article key={step.id} style={{ border: "1px solid #365368", padding: 12, flex: "1 1 180px" }}>
        <strong>{step.id === "inspect" ? "Inspect source" : step.id === "preserve" ? "Preserve original" : "Review evidence"}</strong>
        <p>{step.id === "review" && decision ? decision.decision : step.state}</p>
        <small>{step.depends_on.length ? `Requires: ${step.depends_on.join(" + ")} → ${step.id}` : "Input: uploaded source"}</small>
        <p><small>{step.started_at ? new Date(step.started_at).toLocaleString() : "Not started"}{step.completed_at ? ` → ${new Date(step.completed_at).toLocaleString()}` : ""}</small></p>
        <details><summary>Execution evidence</summary><p>{step.function}</p><p style={{ overflowWrap: "anywhere" }}>{step.input_ids.join(", ")}</p><p style={{ overflowWrap: "anywhere" }}>{step.output_ids.join(", ")}</p></details>
      </article>)}
    </div>
    {profile?.source_use && <p>Use: {profile.source_use.replaceAll("_", " ")}</p>}
    {proof && <section aria-label="Source aggregation proof"><h3>Safe source-total selection</h3><p>{proof.state.replaceAll("_", " ")} · {proof.selected_rows.length} selected root rows</p><p>{proof.policy}</p><div className="data-scroll"><table><thead><tr><th>Measure</th><th>Selected source total</th><th>Difference from workbook total</th><th>Extra amount from adding overlapping rows</th></tr></thead><tbody>{Object.entries(proof.account_totals).map(([measure, amount]) => <tr key={measure}><td>{measure.replaceAll("_", " ")}</td><td>{amount}</td><td>{proof.source_total_residuals[measure] ?? "Unestablished"}</td><td>{proof.naive_sum_overstatement[measure]}</td></tr>)}</tbody></table></div><details><summary>Selected source rows</summary><p>{proof.selected_rows.join(", ")}</p></details><details><summary>Parent/detail reconciliation · {proof.hierarchy_checks.filter(check => check.state !== "PASS").length} residuals</summary>{proof.hierarchy_checks.filter(check => check.state !== "PASS").map(check => <p key={check.parent_row}>Row {check.parent_row}: {Object.entries(check.residuals).filter(([, value]) => Number(value) !== 0).map(([measure, value]) => `${measure}: ${value}`).join("; ")}</p>)}</details></section>}
    {!!profile?.sheets?.length && <><h3>Source types and scope</h3><div className="data-scroll"><table><thead><tr><th>Sheet</th><th>Source type / grain</th><th>Observed period / company</th><th>Rows / formulas</th></tr></thead><tbody>{profile.sheets.map(sheet => <tr key={sheet.sheet}><td>{sheet.sheet}</td><td>{sheet.source_type}<br /><small>{sheet.grain}</small></td><td>{sheet.periods.join(", ") || "Period unestablished"}<br />{sheet.company_labels.join(", ") || "Company unestablished"}</td><td>{sheet.source_rows} / {sheet.formula_count}</td></tr>)}</tbody></table></div></>}
    {!!profile?.findings?.length && <><h3>Detected source findings</h3>{profile.findings.map((finding, index) => <details key={index}><summary>{finding.code.replaceAll("_", " ")} {finding.sheet && `· ${finding.sheet}`} {finding.occurrences ? `(${finding.occurrences})` : ""}</summary><p>{finding.message}</p><p style={{ overflowWrap: "anywhere" }}>{finding.coordinates.join(", ") || "Applies to source context"}</p></details>)}</>}
    {!!profile?.dependencies?.length && <details><summary>Workbook dependency DAG · {profile.dependencies.length} sheet relationships</summary><p>Edges are observed formula references. Cycles and unresolved references require review; formulas have not been executed.</p><div className="data-scroll"><table><thead><tr><th>Input → dependent sheet</th><th>Formula references</th><th>Resolution</th></tr></thead><tbody>{profile.dependencies.map((edge, index) => <tr key={index}><td>{edge.source} → {edge.target}</td><td>{edge.formula_count}</td><td>{edge.resolved_sheet ? "Sheet present" : "Unresolved / external"}</td></tr>)}</tbody></table></div></details>}
  </section>;
}
