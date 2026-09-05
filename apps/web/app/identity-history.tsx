"use client";
import { useEffect, useRef, useState, type FormEvent } from "react";
import type { HistoricalGraph } from "@finai/contracts";

type Resolution = { canonical_id: string; version_id: string; display_name: string; resolution_chain: string[]; valid_at: string; known_at: string; authority_state: string };

export default function IdentityHistory({ resourceId, token }: { resourceId: string; token: string }) {
  const [result, setResult] = useState<Resolution | null>(null);
  const [graph, setGraph] = useState<HistoricalGraph | null>(null);
  const [page, setPage] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const active = useRef(true);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  async function resolve(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(""); setResult(null); setGraph(null); setPage(0);
    const data = new FormData(event.currentTarget);
    const trace = (event.nativeEvent as SubmitEvent).submitter?.getAttribute("value") === "graph";
    try {
      const query = new URLSearchParams({ valid_at: new Date(String(data.get("valid"))).toISOString(), known_at: new Date(String(data.get("known"))).toISOString() });
      const path = trace ? `resources/${resourceId}/graph` : `resolve/${resourceId}`;
      const response = await fetch(`/api/ontology/${path}?${query}`, { cache: "no-store", headers: { Authorization: `Bearer ${token}` } });
      const value = await response.json();
      if (!response.ok) throw new Error(value.detail ?? "Historical resolution unavailable");
      if (active.current) { if (trace) setGraph(value); else setResult(value); }
    } catch (failure) { if (active.current) setError(failure instanceof Error ? failure.message : "Historical resolution failed"); }
    finally { if (active.current) setBusy(false); }
  }
  const versions = new Map(graph?.nodes.map(node => [node.version_id, node]) ?? []);
  return <details><summary>Reconstruct identity and dependencies</summary>
    <p>Separate when an identity applied in the business from when G8 knew about it. Dates use your local time zone.</p>
    <form onSubmit={resolve} className="resource-form"><label>Business date and time<input type="datetime-local" name="valid" required /></label>
      <label>Known to G8 by<input type="datetime-local" name="known" required /></label><button disabled={busy} value="identity">{busy ? "Reconstructing…" : "Reconstruct identity"}</button><button className="quiet" disabled={busy} value="graph">Trace historical dependencies</button></form>
    {error && <p role="alert" className="warning">{error}</p>}
    {result && <div role="status"><h3>{result.display_name}</h3><p>{result.authority_state} · {result.resolution_chain.length - 1} identity redirects</p><p>Effective at {new Date(result.valid_at).toLocaleString()} · known by {new Date(result.known_at).toLocaleString()}</p><code className="full-hash">{result.canonical_id}<br />Version {result.version_id}</code><details><summary>Resolution path</summary><ol>{result.resolution_chain.map(id => <li key={id}>{id}</li>)}</ol></details></div>}
    {graph && <section aria-label="Historical dependency trace"><h3>{versions.get(graph.root_version_id)?.display_name} · {graph.nodes.length} retained versions</h3>
      <p>Historical lineage preserves the versions recorded with this resource. It does not authorize a current execution.</p>
      <p>Business time {new Date(graph.valid_at).toLocaleString()} · known by {new Date(graph.known_at).toLocaleString()}</p>
      <code className="full-hash">Root version {graph.root_version_id}</code>
      {graph.edges.length ? <><ol>{graph.edges.slice(page * 25, (page + 1) * 25).map(edge => <li key={`${edge.source_version_id}:${edge.target_version_id}:${edge.relation}`}>
        <strong>{versions.get(edge.source_version_id)?.display_name}</strong> → {versions.get(edge.target_version_id)?.display_name}
        <small className="hash-caption">{edge.relation}</small><details><summary>Retained dependency version</summary><code className="full-hash">{edge.target_version_id}</code><p>{versions.get(edge.target_version_id)?.authority_state} at acceptance · {versions.get(edge.target_version_id)?.object_type}</p><p>Effective from {new Date(versions.get(edge.target_version_id)!.valid_from).toLocaleString()} · recorded {new Date(versions.get(edge.target_version_id)!.system_from).toLocaleString()}</p></details>
      </li>)}</ol><div className="pagination"><button className="quiet" disabled={page === 0} onClick={() => setPage(value => value - 1)}>Previous</button><span>Page {page + 1}</span><button className="quiet" disabled={(page + 1) * 25 >= graph.edges.length} onClick={() => setPage(value => value + 1)}>Next</button></div></> : <p>No recorded dependencies.</p>}
      <small>Bounded to depth {graph.max_depth}, {graph.max_nodes} versions and {graph.max_edges} relationships; incomplete traces are refused.</small>
    </section>}
  </details>;
}
