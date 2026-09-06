"use client";

import { useEffect, useRef, useState } from "react";

type Company = { resource_id: string; display_name: string; attributes: { registration_code?: string } };
type Notice = { licence_number: string; company_code: string; company_label: string; issued_on: string; activity: string; stated_term: string; current_status: string; source_url: string; raw_rows: string[][] };
type Inspection = { notice: Notice; companies: Company[]; binding: { attributes: { company_id: string; rationale: string } } | null };
type Operation = { operation_id: string; state: string; prepared_proposal_id: string; proposal: { proposal: { proposal_id: string } } | null; events: { event_id: string; state: string; created_at: string; reason?: string }[] };

export default function SourceLicenceNotice({ token, documentId, canPropose, onProposal }: {
  token: string; documentId: string; canPropose: boolean; onProposal: (id: string) => void;
}) {
  const [data, setData] = useState<Inspection | null>(null);
  const [company, setCompany] = useState("");
  const [rationale, setRationale] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [operations, setOperations] = useState<Operation[]>([]);
  const request = useRef<{ content: string; id: string } | null>(null);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  useEffect(() => {
    if (!/^doc_[a-f0-9]{64}$/.test(documentId)) return;
    const controller = new AbortController();
    fetch(`/api/ontology/operations?document_id=${encodeURIComponent(documentId)}`, {
      headers: { Authorization: `Bearer ${token}` }, signal: controller.signal,
    }).then(async response => {
      if (!response.ok) throw new Error("Could not load retained operations");
      const result = await response.json();
      if (!controller.signal.aborted) setOperations(result.operations);
    }).catch(failure => { if (!controller.signal.aborted) setError(String(failure)); });
    return () => controller.abort();
  }, [documentId, token]);
  async function refresh(operation: Operation, resume = false) {
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/ontology/operations/${operation.operation_id}${resume ? "/resume" : ""}`, {
        method: resume ? "POST" : "GET", headers: { Authorization: `Bearer ${token}` },
      });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Operation request failed");
      setOperations(current => current.map(row => row.operation_id === result.operation_id ? result : row));
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Operation request failed"); }
    finally { setBusy(false); }
  }
  async function run(propose: boolean) {
    pending.current?.abort(); const controller = new AbortController(); pending.current = controller;
    setBusy(true); setError("");
    try {
      const content = JSON.stringify({ document_id: documentId, company_id: company, rationale });
      if (propose && request.current?.content !== content) request.current = { content, id: crypto.randomUUID() };
      const response = await fetch(propose ? "/api/ontology/operations/licence-notices" : `/api/ontology/source-documents/${documentId}/licence/inspect`, {
        method: "POST", signal: controller.signal,
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify(propose ? { document_id: documentId, company_id: company, rationale, request_id: request.current!.id } : {}),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Licence notice request rejected");
      if (controller.signal.aborted) return;
      if (propose) setOperations(current => [result, ...current.filter(row => row.operation_id !== result.operation_id)]);
      else { setData(result); setCompany(result.binding?.attributes.company_id ?? ""); setRationale(result.binding?.attributes.rationale ?? ""); }
    } catch (failure) { if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "Request failed"); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  return <section>
    <h3>Official licence issuance evidence</h3>
    <p>Inspect a retained Matsne gas-distribution licence notice and bind it to the company already used by accounting.</p>
    <button disabled={busy || !documentId} onClick={() => void run(false)}>Inspect licence notice</button>
    {data && <>
      <dl><dt>Licence</dt><dd>№{data.notice.licence_number}</dd><dt>Company named in source</dt><dd>{data.notice.company_label} · {data.notice.company_code}</dd><dt>Issued</dt><dd>{data.notice.issued_on}</dd><dt>Activity</dt><dd>Natural gas distribution</dd><dt>Stated term</dt><dd>{data.notice.stated_term === "INDEFINITE" ? "Indefinite" : "Not stated"}</dd><dt>Current legal status</dt><dd>Not established by this historical notice</dd></dl>
      <p><a href={data.notice.source_url} target="_blank" rel="noreferrer">Open source notice on Matsne</a></p>
      <details><summary>Retained source table</summary><div className="g8-table-scroll"><table><tbody>{data.notice.raw_rows.map((row, index) => <tr key={index}>{row.map((cell, column) => <td key={column}>{cell || "—"}</td>)}</tr>)}</tbody></table></div></details>
      <p>{data.binding ? "Source notice and company binding are published." : "Awaiting source publication and identity review."} This does not activate a licence, operating area, tariff or financial obligation.</p>
      <label>Licence notice company<select value={company} onChange={event => setCompany(event.target.value)}><option value="">Select canonical company</option>{data.companies.map(row => <option key={row.resource_id} value={row.resource_id} disabled={!!row.attributes.registration_code && row.attributes.registration_code !== data.notice.company_code}>{row.display_name}</option>)}</select></label>
      <label>Licence identity matching rationale<textarea value={rationale} onChange={event => setRationale(event.target.value)} maxLength={2000}/></label>
      {canPropose && <button disabled={busy || !company || rationale.trim().length < 10} onClick={() => void run(true)}>Propose licence source binding</button>}
    </>}
    {operations.length > 0 && <section aria-label="Retained licence operations">
      <h4>Retained licence operations</h4>
      {operations.map(operation => <article key={operation.operation_id}>
        <p>{operation.state.replaceAll("_", " ")}</p>
        <details><summary>Operation record</summary><code>{operation.operation_id}</code>
          <ul>{operation.events.map(event => <li key={event.event_id}>{event.created_at} · {event.state}{event.reason ? ` · ${event.reason}` : ""}</li>)}</ul>
        </details>
        <button disabled={busy} onClick={() => void refresh(operation)}>Refresh review outcome</button>
        {operation.proposal && <button onClick={() => onProposal(operation.proposal!.proposal.proposal_id)}>Open binding review</button>}
        {canPropose && operation.state === "PREPARED" && <button disabled={busy} onClick={() => void refresh(operation, true)}>Resume prepared operation</button>}
      </article>)}
    </section>}
    {busy && <p role="status">Reading retained licence evidence…</p>}{error && <p role="alert">{error}</p>}
  </section>;
}
