"use client";

import { useEffect, useRef, useState } from "react";

type Company = { resource_id: string; display_name: string; attributes: { registration_code?: string } };
type Row = { row_number: number; reported_name: string; reported_code: string; reported_country: string; reported_role: string; reported_percent: string | null; former_indicator: string; binding: { attributes: { reporter_id: string; reporter_code: string; reporting_year: number; related_entity_id: string; rationale: string } } | null };
type Disclosure = { rows: Row[]; companies: Company[] };

export default function SourceCorporateDisclosure({ token, documentId, canPropose, onProposal }: {
  token: string; documentId: string; canPropose: boolean; onProposal: (id: string) => void;
}) {
  const [data, setData] = useState<Disclosure | null>(null);
  const [reporter, setReporter] = useState("");
  const [code, setCode] = useState("");
  const [year, setYear] = useState("");
  const [rationale, setRationale] = useState("");
  const [selections, setSelections] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  async function run(propose: boolean) {
    pending.current?.abort(); const controller = new AbortController(); pending.current = controller;
    setBusy(true); setError("");
    try {
      const bindings = Object.fromEntries(Object.entries(selections).filter(([, value]) => value).map(([key, value]) => [key, value === "CREATE" ? null : value]));
      const response = await fetch(`/api/ontology/source-documents/${documentId}/corporate/${propose ? "proposal" : "inspect"}`, {
        method: "POST", signal: controller.signal,
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify(propose ? { reporter_id: reporter, reporter_code: code, reporting_year: Number(year), rationale, bindings } : {}),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Corporate disclosure request rejected");
      if (controller.signal.aborted) return;
      if (propose) onProposal(result.proposal.proposal_id);
      else {
        setData(result); setSelections({});
        const prior = (result as Disclosure).rows.find(row => row.binding)?.binding?.attributes;
        if (prior) { setReporter(prior.reporter_id); setCode(prior.reporter_code); setYear(String(prior.reporting_year)); setRationale(prior.rationale); }
      }
    } catch (failure) { if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "Request failed"); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  const selectedCount = Object.values(selections).filter(Boolean).length;
  return <section>
    <h3>Corporate group disclosure</h3>
    <p>Read a retained Reportal group-structure HTML document and connect its reported parties to canonical companies.</p>
    <button disabled={busy || !documentId} onClick={() => void run(false)}>Inspect corporate disclosure</button>
    {data && <>
      <p>These are reported relationships. Publication preserves the source statement; it does not establish current direct ownership, consolidation policy or a licence.</p>
      <label>Reporting company<select value={reporter} onChange={event => { setReporter(event.target.value); const company = data.companies.find(c => c.resource_id === event.target.value); setCode(company?.attributes.registration_code ?? ""); }}><option value="">Select canonical company</option>{data.companies.map(company => <option key={company.resource_id} value={company.resource_id}>{company.display_name}</option>)}</select></label>
      <label>Reporter identification code<input value={code} onChange={event => setCode(event.target.value)} inputMode="numeric" maxLength={9}/></label>
      <label>Reporting year<input type="number" min={2000} max={2100} value={year} onChange={event => setYear(event.target.value)}/></label>
      <p>The reporter and year come from the source retrieval context and require review. A reporting year is not a legal ownership effective date.</p>
      {!data.rows.length && <p>No company rows were disclosed. This does not establish that the company has no parent or subsidiaries.</p>}
      <div className="g8-table-scroll"><table><thead><tr><th>Source party</th><th>Reported role</th><th>Participation</th><th>Canonical company</th><th>Publication</th></tr></thead><tbody>{data.rows.map(row => <tr key={row.row_number}>
        <td>{row.reported_name}<br/>{row.reported_code} · {row.reported_country}{row.former_indicator && <p>Former subsidiary indicator: {row.former_indicator}</p>}</td>
        <td>{row.reported_role === "PARENT" ? "Reported parent" : "Reported subsidiary"}</td><td>{row.reported_percent === null ? "Not disclosed" : `${row.reported_percent}%`}</td>
        <td><select aria-label={`Canonical company for row ${row.row_number}`} value={selections[row.row_number] ?? ""} onChange={event => setSelections(previous => ({ ...previous, [row.row_number]: event.target.value }))}><option value="">Skip this row</option><option value="CREATE">Create from this source identity</option>{data.companies.filter(company => company.resource_id !== reporter).map(company => <option key={company.resource_id} value={company.resource_id}>{company.display_name}</option>)}</select></td>
        <td>{row.binding ? "Published with reviewed binding" : "Not published"}</td>
      </tr>)}</tbody></table></div>
      <label>Identity matching and source context rationale<textarea value={rationale} onChange={event => setRationale(event.target.value)} maxLength={2000}/></label>
      <p>{selectedCount} selected rows · at most 24 per review.</p>
      {canPropose && <button disabled={busy || !reporter || !/^\d{9}$/.test(code) || Number(year) < 2000 || Number(year) > 2100 || rationale.trim().length < 10 || !selectedCount || selectedCount > 24} onClick={() => void run(true)}>Propose corporate bindings for review</button>}
    </>}
    {busy && <p role="status">Resolving retained corporate evidence…</p>}{error && <p role="alert">{error}</p>}
  </section>;
}
