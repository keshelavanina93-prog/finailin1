"use client";

import { useEffect, useState } from "react";
import { Panel } from "./g8-ui";
import RegulatoryMonitors from "./regulatory-monitors";

type Observation = { matsne_id: string; title: string; publication: number | null; advertised_publications: number[]; metadata: Record<string,string>; text_sha256: string; text: string; completeness: string; attachments_retained: boolean; current_law_verified: boolean };
type Capture = { document: { document_id: string; sha256: string }; observation: Observation; source_url: string };
type Publication = { resource_id: string; version_id: string; attributes: { document_id: string; act_id: string; observation: Observation } };
type ImpactObject = { resource_id: string; version_id: string; object_type: string; display_name: string; depth?: number; relation?: string };
type Impact = { run_id: string; act: ImpactObject; observed_at: string; dependency_impact: { affected: ImpactObject[] }; rule_contexts: { rule: ImpactObject; references: ImpactObject[] }[]; financial_impact: { state: string; reason: string }; limitations: string[] };

export default function RegulatorySources({ token, onProposal }: { token: string; onProposal: (id: string) => void }) {
  const [number, setNumber] = useState("");
  const [publication, setPublication] = useState(0);
  const [captured, setCaptured] = useState<Capture | null>(null);
  const [rows, setRows] = useState<Publication[]>([]);
  const [rationale, setRationale] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [before, setBefore] = useState("");
  const [after, setAfter] = useState("");
  const [comparison, setComparison] = useState<{ run_id: string; state: string; diff: string[]; diff_truncated: boolean } | null>(null);
  const [impact, setImpact] = useState<Impact | null>(null);
  const [impactId, setImpactId] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      const collected: Publication[] = [];
      let offset: number | null = 0;
      while (offset !== null) {
        const response: Response = await fetch(`/api/ontology/regulation/sources?offset=${offset}`, { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal });
        if (!response.ok) throw new Error("Regulatory publication history unavailable");
        const result: { publications: Publication[]; next_offset: number | null } = await response.json(); collected.push(...result.publications); offset = result.next_offset;
        if (collected.length >= 5000 && offset !== null) throw new Error("Publication history exceeds this view's capacity");
      }
      if (!controller.signal.aborted) setRows(collected);
    }
    void load().catch(failure => { if (!controller.signal.aborted) setError(String(failure)); });
    return () => controller.abort();
  }, [token, revision]);
  async function act(propose: boolean) {
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/ontology/regulation/sources/${propose ? "proposals" : "capture"}`, {
        method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify(propose ? { document_id: captured!.document.document_id, rationale } : { document_number: number, publication }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Source request rejected");
      if (propose) onProposal(result.proposal.proposal_id); else setCaptured(result);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Source request failed"); }
    finally { setBusy(false); }
  }
  async function compare() {
    setBusy(true); setError(""); setComparison(null);
    try {
      const response = await fetch("/api/ontology/regulation/sources/compare", { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ before_version: before, after_version: after }) });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Comparison unavailable");
      setComparison(result);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Comparison failed"); }
    finally { setBusy(false); }
  }
  async function inspect(documentId: string) {
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/ontology/regulation/sources/inspect?document_id=${encodeURIComponent(documentId)}`, { headers: { Authorization: `Bearer ${token}` } });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Source unavailable");
      setCaptured(result);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Source unavailable"); }
    finally { setBusy(false); }
  }
  async function traceImpact(reopen: boolean) {
    setBusy(true); setError("");
    try {
      const response = await fetch(reopen ? `/api/ontology/regulation/impacts/${impactId}` : "/api/ontology/regulation/sources/impact", {
        method: reopen ? "GET" : "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: reopen ? undefined : JSON.stringify({ document_id: captured!.document.document_id }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Impact trace unavailable");
      setImpact(result); setImpactId(result.run_id);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Impact trace failed"); }
    finally { setBusy(false); }
  }
  return <Panel title="Official regulatory sources">
    <p>Capture an exact Matsne publication and review its act identity. Capture does not establish current law or activate obligations.</p>
    <label>Matsne document ID<input value={number} onChange={event => setNumber(event.target.value)} inputMode="numeric"/></label>
    <label>Publication number<input type="number" min={0} max={10000} value={publication} onChange={event => setPublication(Number(event.target.value))}/></label>
    <button disabled={busy || !/^[1-9][0-9]{0,11}$/.test(number)} onClick={() => void act(false)}>Capture official publication</button>
    <RegulatoryMonitors token={token} documentNumber={number} publication={publication} onInspect={id => void inspect(id)}/>
    {captured && <section aria-label="Captured regulatory publication"><h3>{captured.observation.title}</h3>
      <p>{captured.observation.completeness.replaceAll("_", " ")}. Annexes have not been retained; current-law completeness remains unverified.</p>
      <p>Served publication: {captured.observation.publication ?? "Unknown"}. Advertised publications: {captured.observation.advertised_publications.join(", ") || "None identified"}.</p>
      <details><summary>Official metadata and source text</summary><dl>{Object.entries(captured.observation.metadata).map(([key,value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl><pre style={{whiteSpace:"pre-wrap"}}>{captured.observation.text}</pre></details>
      <p><a href={captured.source_url} target="_blank" rel="noreferrer">Open official publication</a></p>
      <label>Regulatory source review rationale<textarea value={rationale} onChange={event => setRationale(event.target.value)} maxLength={2000}/></label>
      <button disabled={busy || rationale.trim().length < 10} onClick={() => void act(true)}>Propose act and publication binding</button>
      <button disabled={busy} onClick={() => void traceImpact(false)}>Trace affected ontology</button>
    </section>}
    <label>Retained regulatory impact ID<input value={impactId} onChange={event => setImpactId(event.target.value)}/></label>
    <button disabled={busy || !/^fcr_[a-f0-9]{64}$/.test(impactId)} onClick={() => void traceImpact(true)}>Reopen impact trace</button>
    {impact && <section aria-label="Regulatory ontology impact"><h3>Potential dependency impact</h3>
      <p>{impact.act.display_name} · Snapshot {impact.observed_at}</p>
      <p>Financial impact: {impact.financial_impact.state}. {impact.financial_impact.reason}.</p>
      {impact.dependency_impact.affected.map(object => <p key={object.version_id}>{object.object_type}: {object.display_name} · dependency depth {object.depth}<br/><small>Object {object.resource_id} · version {object.version_id}</small></p>)}
      {!impact.dependency_impact.affected.length && <p>No registered downstream dependencies found. This does not establish no business impact.</p>}
      {impact.rule_contexts.map(context => <details key={context.rule.version_id}><summary>{context.rule.display_name}: exact company, licence and evidence references</summary>
        {context.references.map(reference => <p key={`${reference.relation}:${reference.version_id}`}>{reference.relation}: {reference.display_name} ({reference.object_type})<br/><small>{reference.resource_id} · version {reference.version_id}</small></p>)}
      </details>)}
      <ul>{impact.limitations.map(limit => <li key={limit}>{limit}</li>)}</ul>
    </section>}
    {error && <p role="alert">{error}</p>}
    <h3>Reviewed publication history</h3><button onClick={() => setRevision(value => value + 1)}>Refresh publications</button>
    <label>Earlier publication<select value={before} onChange={event => setBefore(event.target.value)}><option value="">Select captured version</option>{rows.map(row => <option key={row.version_id} value={row.version_id}>Matsne {row.attributes.observation.matsne_id} / {row.attributes.observation.publication} · {row.version_id}</option>)}</select></label>
    <label>Later publication<select value={after} onChange={event => setAfter(event.target.value)}><option value="">Select captured version</option>{rows.map(row => <option key={row.version_id} value={row.version_id}>Matsne {row.attributes.observation.matsne_id} / {row.attributes.observation.publication} · {row.version_id}</option>)}</select></label>
    <button disabled={busy || !before || !after} onClick={() => void compare()}>Compare retained publications</button>
    {comparison && <section aria-label="Regulatory source comparison"><p>{comparison.state.replaceAll("_", " ")}</p><p>Retained comparison: {comparison.run_id}. Text differences require interpretation and review before they can change obligations.</p>{comparison.diff_truncated && <p>Diff display truncated; retained originals remain available.</p>}<pre style={{whiteSpace:"pre-wrap"}}>{comparison.diff.join("\n") || "No document-text differences."}</pre></section>}
    {rows.map(row => <article key={row.version_id}><h4>{row.attributes.observation.title}</h4><p>Matsne {row.attributes.observation.matsne_id} · publication {row.attributes.observation.publication ?? "unknown"} · {row.attributes.observation.completeness.replaceAll("_", " ")}</p>
      <details><summary>Publication evidence</summary><p>Act identity: {row.attributes.act_id}</p><p>Original document: {row.attributes.document_id}</p><p>Legal text hash: {row.attributes.observation.text_sha256}</p><p>Later publications listed: {row.attributes.observation.advertised_publications.join(", ")}</p></details><button disabled={busy} onClick={() => void inspect(row.attributes.document_id)}>Read retained publication</button>
    </article>)}
  </Panel>;
}
