"use client";

import { useState, type FormEvent } from "react";
import type { IngestReceipt } from "@finai/contracts";

export default function Home() {
  const [receipt, setReceipt] = useState<IngestReceipt | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function ingest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const file = data.get("source") as File;
    setError(""); setReceipt(null); setBusy(true);
    try {
      if (file.size > 1_000_000) throw new Error("Choose a CSV smaller than 1 MB.");
      const response = await fetch("/api/hydration", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${data.get("token")}` },
        body: JSON.stringify({
          scope: { tenant_id: data.get("tenant"), legal_entity_id: data.get("entity"),
            period: data.get("period"), currency: data.get("currency") },
          filename: file.name, csv_text: new TextDecoder("utf-8", { fatal: true, ignoreBOM: true })
            .decode(await file.arrayBuffer()),
        }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string"
        ? result.detail : "Request validation failed. Check the file and exact scope.");
      setReceipt(result);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Ingestion failed");
    } finally { setBusy(false); }
  }
  return <main>
    <header className="topbar">
      <div className="brand"><span className="brandMark">F</span><div><strong>FinAI</strong><span>NYX CORE</span></div></div>
      <div className="context">Enterprise Hydration · Source Authority</div>
      <div className="environment">CANDIDATE WORKSPACE</div>
    </header>
    <section className="hero">
      <div><p className="eyebrow">EVIDENCE → UNDERSTANDING → REVIEW</p>
        <h1>Construct what the evidence can prove.</h1>
        <p className="heroCopy">Upload a trial balance or an unfamiliar CSV. Inspect retained evidence,
          source boundaries and proposed objects before any canonical promotion.</p></div>
      <div className="receipt"><span>CONSTRUCTION RECEIPT</span>
        <strong>{receipt?.receipt_id ?? "Awaiting source evidence"}</strong>
        <small>Candidate only · promotion requires reconciliation and approval</small></div>
    </section>
    <section className="workspace">
      <form className="sourcePanel" onSubmit={ingest}>
        <p className="panelLabel">SOURCE AND EXACT SCOPE</p>
        <label>Access token<input name="token" type="password" autoComplete="off" required /></label>
        <label>Tenant UUID<input name="tenant" required /></label>
        <label>Legal entity<input name="entity" required maxLength={128} /></label>
        <label>Period<input name="period" type="month" required /></label>
        <label>Currency<input name="currency" pattern="[A-Z]{3}" maxLength={3} placeholder="GEL" required /></label>
        <label>CSV source<input name="source" type="file" accept=".csv,text/csv" required /></label>
        <p className="heroCopy">TB columns: account_code, debit, credit. Other schemas remain source records.</p>
        <button disabled={busy}>{busy ? "Retaining and compiling…" : "Ingest evidence"}</button>
        {error && <p role="alert">{error}</p>}
      </form>
      <section className="authorityPanel" aria-live="polite">
        <div className="panelHeader"><div><p className="panelLabel">EVIDENCE WORKSPACE</p>
          <h2>{receipt?.source_class ?? "No source ingested"}</h2></div>
          <span className="count">{receipt?.candidates.length ?? 0} candidates</span></div>
        {receipt ? <div className="resultBody">
          <p><strong>{receipt.authority_state}</strong> · Reconciliation: {receipt.reconciliation.status}</p>
          <p className="hash">Source SHA-256 <code>{receipt.source_sha256}</code></p>
          <ol className="pipeline" aria-label="Executed compilation plan">
            {receipt.plan.map(stage => <li key={stage}>{stage}</li>)}</ol>
          {receipt.warnings.map(warning => <p key={warning}>{warning}</p>)}
          <h3>Rejected rows ({receipt.rejects.length})</h3>
          {receipt.rejects.map(reject => <p key={reject} role="status">{reject}</p>)}
          <div className="tableScroll"><table><thead><tr><th>Source row</th><th>Object</th><th>Evidence state</th><th>Values</th></tr></thead>
            <tbody>{receipt.candidates.map((candidate, i) => <tr key={i}>
              <td>{candidate.source_row}</td><td>{candidate.object_type}</td>
              <td>{candidate.epistemic_state}</td><td><code>{JSON.stringify(candidate.values)}</code></td>
            </tr>)}</tbody></table></div>
          <details><summary>Full construction receipt</summary><pre>{JSON.stringify(receipt, null, 2)}</pre></details>
        </div> : <p className="resultBody">Ingest evidence to see the compilation plan, candidates, rejected rows and durable receipt.</p>}
      </section>
    </section>
    <footer><span>Evidence state and business authority remain separate</span><span>Hydration compiler / 1</span></footer>
  </main>;
}
