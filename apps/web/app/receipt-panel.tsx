"use client";

import { useRef, useState } from "react";
import type { Principal, ReceiptDetail } from "@finai/contracts";
import CanonicalTrace from "./canonical-trace";

type Props = {
  detail: ReceiptDetail;
  principal: Principal;
  busy: boolean;
  onDecision: (decision: "APPROVED" | "REJECTED", reason: string, key: string) => Promise<void>;
  onExport: (format: "source" | "export") => void;
  onObjects: () => void;
  onClose: () => void;
};

export default function ReceiptPanel({ detail, principal, busy, onDecision, onExport, onObjects, onClose }: Props) {
  const [reason, setReason] = useState("");
  const [candidatePage, setCandidatePage] = useState(0);
  const [stage, setStage] = useState("candidates");
  const intent = useRef({ signature: "", key: "" });
  const { receipt, decision } = detail;
  const canReview = principal.permissions.includes("review");
  const canReject = canReview && !!detail.submitted_by && detail.submitted_by !== principal.actor_id;
  async function decide(value: "APPROVED" | "REJECTED") {
    const signature = JSON.stringify([receipt.receipt_id, value, reason, detail.current_head]);
    if (signature !== intent.current.signature) intent.current = { signature, key: crypto.randomUUID() };
    await onDecision(value, reason, intent.current.key);
  }

  return <section className="construction" aria-label="Construction review">
    <div className="section-heading"><div><p className="overline">CONSTRUCTION REVIEW</p><h2>{detail.filename}</h2></div>
      <button className="quiet" onClick={onClose}>Close review</button></div>
    <div className="review-layout">
      <div>
        <div className="identity-line"><span className={`status ${decision?.decision.toLowerCase() ?? "pending"}`}>{decision?.decision ?? "PENDING REVIEW"}</span>
          <span>{receipt.source_class.replaceAll("_", " ")}</span><span>{receipt.candidates.length} proposed objects</span></div>
        <p className="muted">{receipt.binding_state === "CANONICAL_BOUND" ? "Shared identity bound · financial certification remains separate" : "Source-only construction · canonical accounting identity unavailable"}</p>
        <CanonicalTrace references={receipt.canonical_references} />
        <nav className="pipeline-nav" aria-label="Compilation stages">
          {receipt.plan.map((name, index) => <button aria-pressed={stage === name} className={stage === name ? "selected" : ""}
            onClick={() => setStage(name)} key={name}><small>{String(index + 1).padStart(2, "0")}</small>{name}</button>)}
        </nav>
        <div className="stage-content">
          {stage === "preserve" && <><h3>Retained source evidence</h3><p>Original submitted UTF-8 content is retained with this construction.</p><p>{receipt.source_storage ? `Stored separately as original evidence · ${receipt.source_storage.byte_length.toLocaleString()} bytes` : "Retained in the original construction store"}. Downloads verify the content against the retained hash.</p><code className="full-hash">{receipt.source_sha256}</code><p>Submitted by {detail.submitted_by ?? "Legacy identity unavailable"} · {new Date(detail.ingested_at).toLocaleString()}</p></>}
          {stage === "classify" && <><h3>{receipt.source_class.replaceAll("_", " ")}</h3><p>Structural recognition determines the source contract. It does not certify the source or establish deeper transactions.</p><p>Pack: {receipt.pack_version}</p></>}
          {stage === "authority-check" && <><h3>Source authority: {receipt.authority_contract_version}</h3><p>{receipt.source_class === "TRIAL_BALANCE" ? "Account and period-balance candidates only. Invoices, journal documents and inventory movements require their own evidence." : "Raw source records only. Business identities and financial meaning have not been inferred."}</p><p>Review approval accepts the construction, not a certified financial statement.</p></>}
          {(stage === "profile" || stage === "bind") && <><h3>Source field coverage</h3><p>Used: {receipt.used_fields.join(", ")}</p><p>Unused: {receipt.unused_fields.join(", ") || "None"}</p><p>Executed functions: {receipt.functions_executed.join(", ") || "No financial functions"}</p></>}
          {stage === "validate" && <><h3>Reconciliation: {receipt.reconciliation.status}</h3><dl className="value-list">{Object.entries(receipt.reconciliation).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl>
            <h3>Rejected rows ({receipt.rejects.length})</h3>{receipt.rejects.slice(0, 100).map(item => <p className="warning" key={item}>{item}</p>)}</>}
          {stage === "candidates" && <><h3>Proposed objects · source-row lineage</h3><div className="data-scroll"><table><thead><tr><th>Row</th><th>Object type</th><th>Evidence</th><th>Values</th></tr></thead>
            <tbody>{receipt.candidates.slice(candidatePage * 50, (candidatePage + 1) * 50).map((item, i) => <tr key={i}><td>{item.source_row}</td><td>{item.object_type}</td><td><span className="status observed">{item.epistemic_state}</span></td><td className="values">{Object.entries(item.values).map(([key, value]) => <span key={key}><small>{key}</small> {value}</span>)}</td></tr>)}</tbody></table></div>
            <div className="pagination"><button className="quiet" disabled={candidatePage === 0} onClick={() => setCandidatePage(candidatePage - 1)}>Previous</button><span>Page {candidatePage + 1}</span><button className="quiet" disabled={(candidatePage + 1) * 50 >= receipt.candidates.length} onClick={() => setCandidatePage(candidatePage + 1)}>Next</button></div></>}
        </div>
        <details className="raw-receipt"><summary>Full construction receipt</summary><pre>{JSON.stringify(receipt, null, 2)}</pre></details>
      </div>
      <aside className="decision-panel">
        <p className="overline">VERSION IMPACT</p><h3>{detail.current_head ? "Replace accepted construction" : "First accepted construction"}</h3>
        <div className="impact-counts">{Object.entries(detail.impact).map(([label, count]) => <div key={label}><strong>{count}</strong><span>{label}</span></div>)}</div>
        <p className="muted">One current construction per source class in this exact scope. Previous versions remain available in history. Unfamiliar records are compared by row position.</p>
        {decision ? <div className="decision-record"><h3>{decision.decision === "APPROVED" ? "Construction accepted" : "Construction rejected"}</h3><p>{decision.reason}</p><small>{decision.actor_id} · {new Date(decision.decided_at).toLocaleString()}</small>
          {decision.decision === "APPROVED" && <button onClick={onObjects}>Open this object version</button>}</div> : <>
          {detail.approval_blockers.map(blocker => <p className="warning" key={blocker}>{blocker}</p>)}
          <label>Review rationale<textarea value={reason} onChange={event => setReason(event.target.value)} minLength={10} maxLength={2000} rows={4} placeholder="Record the evidence and basis for your decision" /></label>
          <button disabled={busy || reason.trim().length < 10 || detail.approval_blockers.length > 0} onClick={() => void decide("APPROVED")}>Approve construction</button>
          <button className="danger" disabled={busy || reason.trim().length < 10 || !canReject} onClick={() => void decide("REJECTED")}>Reject construction</button>
        </>}
        {principal.permissions.includes("export") && <div className="export-actions"><button className="quiet" onClick={() => onExport("source")}>Download original CSV</button><button className="quiet" onClick={() => onExport("export")}>Export evidence bundle</button></div>}
        <p className="muted">No posting or external-system action occurs here.</p>
      </aside>
    </div>
  </section>;
}
