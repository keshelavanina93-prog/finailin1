"use client";
import { useEffect, useRef, useState } from "react";
type Page = { offset: number; next_offset: number | null; total_rows: number; new_resources: number; assignments: { source_row: string; dimension: string; value: string | null; member_id?: string; state: string }[] };
type Movements = { total: number; next_offset: number | null; query: { valid_at: string; known_at: string }; objects: { resource_id: string; attributes: { source_row_key: string; posting_date: string; document_reference: string; amount: string } }[] };
export default function SourceDimensions({ token, documentId, sheet, companyId, canPropose, onProposal }: {
  token: string; documentId: string; sheet: string; companyId: string; canPropose: boolean; onProposal: (id: string) => void;
}) {
  const [page, setPage] = useState<Page | null>(null);
  const [movements, setMovements] = useState<Movements | null>(null);
  const [member, setMember] = useState<{ id: string; name: string } | null>(null);
  const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), [token, documentId, sheet, companyId]);
  async function run(offset: number, proposal = false) {
    pending.current?.abort(); const controller = new AbortController(); pending.current = controller;
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/ontology/source-documents/${documentId}/dimensions/${proposal ? "proposal" : "inspect"}`, {
        method: "POST", signal: controller.signal,
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ sheet, profile: "1c_journal", company_id: companyId, offset }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Analytical binding unavailable");
      if (controller.signal.aborted) return;
      if (proposal) onProposal(data.proposal.proposal_id); else setPage(data);
    } catch (failure) { if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "Analytical binding unavailable"); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  async function drill(id: string, name: string, offset = 0) {
    pending.current?.abort(); const controller = new AbortController(); pending.current = controller;
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/ontology/source-documents/${documentId}/dimensions/query`, {
        method: "POST", signal: controller.signal,
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ sheet, profile: "1c_journal", company_id: companyId, member_id: id, offset,
          ...(offset > 0 && member?.id === id && movements ? {
            valid_at: movements.query.valid_at, known_at: movements.query.known_at,
          } : {}) }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Movement query unavailable");
      if (!controller.signal.aborted) { setMember({ id, name }); setMovements(data); }
    } catch (failure) { if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "Movement query unavailable"); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  return <section><h3>Procurement analytical bindings</h3>
    <p>Connect source regions, budget articles and departments to company-scoped ontology members. Each movement keeps its own source-cell and version references.</p>
    <button disabled={busy} onClick={() => void run(0)}>Inspect procurement dimensions</button>
    {busy && <p role="status">Resolving analytical identities…</p>}{error && <p role="alert">{error}</p>}
    {page && <><p>{page.total_rows.toLocaleString()} source movements · showing rows {page.offset + 1}–{Math.min(page.offset + 10, page.total_rows)}.</p>
      <div className="g8-table-scroll"><table><thead><tr><th>Source row</th><th>Dimension</th><th>Source value</th><th>Publication</th><th>Canonical member</th></tr></thead><tbody>
        {page.assignments.map(a => <tr key={`${a.source_row}:${a.dimension}`}><td>{a.source_row}</td><td>{a.dimension}</td><td>{a.value ?? "Missing"}</td><td>{a.state}</td><td>{a.member_id && <><button disabled={busy || a.state !== "APPROVED"} onClick={() => void drill(a.member_id!, `${a.dimension}: ${a.value}`)}>Show movements</button><details><summary>Identity</summary><code>{a.member_id}</code></details></>}</td></tr>)}
      </tbody></table></div>
      <button disabled={busy || page.offset === 0} onClick={() => void run(Math.max(0, page.offset - 10))}>Previous movements</button>
      <button disabled={busy || page.next_offset === null} onClick={() => void run(page.next_offset ?? 0)}>Next movements</button>
      {canPropose && <button disabled={busy || page.new_resources === 0} onClick={() => void run(page.offset, true)}>Propose analytical bindings</button>}
    </>}
    {movements && member && <section><h4>{member.name}</h4><p>{movements.total} distinct source movements. Amounts retain their unestablished currency context.</p>
      <div className="g8-table-scroll"><table><thead><tr><th>Source</th><th>Date</th><th>Document</th><th>Source amount</th></tr></thead><tbody>
        {movements.objects.map(row => <tr key={row.resource_id}><td>{row.attributes.source_row_key}</td><td>{row.attributes.posting_date}</td><td>{row.attributes.document_reference}</td><td>{row.attributes.amount}</td></tr>)}
      </tbody></table></div>
      <button disabled={busy} onClick={() => void drill(member.id, member.name)}>First movement page</button>
      <button disabled={busy || movements.next_offset === null} onClick={() => void drill(member.id, member.name, movements.next_offset ?? 0)}>More movements</button>
    </section>}
    <p>Source classifications do not establish mandatory account dimensions, side-specific subconto, or legal ownership of a region.</p>
  </section>;
}
