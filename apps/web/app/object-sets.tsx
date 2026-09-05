"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import type { CanonicalResource, SchemaField } from "@finai/contracts";

type Query = {
  object_type: string; search: string; filters: { field: string; value: string | number | boolean }[];
  traversal: { kind: "reference" | "link"; name: string; direction: "outgoing" | "incoming" }[];
  offset: number; limit: number; valid_at?: string; known_at?: string;
};
type Result = { query: Query; total: number; counts_by_type: Record<string, number>; objects: CanonicalResource[]; next_offset: number | null };
const label = (value: string) => value.replaceAll("_", " ").replace(/([a-z])([A-Z])/g, "$1 $2");

export default function ObjectSets({ token, catalog: suppliedCatalog }: { token: string; catalog?: CanonicalResource[] }) {
  const [loadedCatalog, setLoadedCatalog] = useState<CanonicalResource[]>([]);
  const catalog = suppliedCatalog ?? loadedCatalog;
  const schemas = catalog.filter(item => item.object_type === "SchemaDefinition");
  const [kind, setKind] = useState("LegalEntity");
  const [field, setField] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);
  useEffect(() => {
    if (suppliedCatalog) return;
    const controller = new AbortController();
    fetch("/api/ontology/catalog", { headers: { Authorization: `Bearer ${token}` }, cache: "no-store", signal: controller.signal })
      .then(async response => { if (!response.ok) throw new Error("Ontology definitions are unavailable."); return response.json(); })
      .then(data => { if (!controller.signal.aborted) setLoadedCatalog(data); })
      .catch(cause => { if (!controller.signal.aborted) setError(cause.message); });
    return () => controller.abort();
  }, [token, suppliedCatalog]);
  const fields = (schemas.find(item => item.identity_key === kind)?.attributes.fields ?? {}) as Record<string, SchemaField>;
  const references = Object.entries(fields).filter(([, spec]) => spec.kind === "reference");
  const links = catalog.filter(item => item.object_type === "LinkType");

  async function run(query: Query) {
    const request = ++generation.current;
    setBusy(true); setError(""); setResult(null);
    try {
      const response = await fetch("/api/ontology/object-sets/query", { method: "POST", cache: "no-store",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify(query) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "The object query could not be evaluated.");
      if (request === generation.current) setResult(data);
    } catch (cause) { if (request === generation.current) setError(cause instanceof Error ? cause.message : "Query failed"); }
    finally { if (request === generation.current) setBusy(false); }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    let value: string | number | boolean = String(data.get("value") ?? "");
    if (field && fields[field]?.kind === "integer") {
      if (!/^-?\d+$/.test(value) || !Number.isSafeInteger(Number(value))) { setError("Enter a whole number within the supported integer range."); return; }
      value = Number(value);
    }
    if (field && fields[field]?.kind === "boolean") value = value === "true";
    const edge = String(data.get("traversal") ?? "");
    const split = edge.indexOf(":");
    void run({ object_type: kind, search: String(data.get("search") ?? ""),
      filters: field ? [{ field, value }] : [],
      traversal: edge ? [{ kind: edge.slice(0, split) as "reference" | "link", name: edge.slice(split + 1), direction: String(data.get("direction")) as "outgoing" | "incoming" }] : [],
      offset: 0, limit: 50 });
  }

  return <section className="data-panel">
    <div className="toolbar"><div><h2>Object Sets</h2><p className="muted">Explore across companies in your workspace. Find canonical objects and follow their version-bound relationships.</p></div></div>
    <form className="resource-form" onSubmit={submit}>
      <label>Object type<select value={kind} onChange={event => { setKind(event.target.value); setField(""); }}>{schemas.map(schema => <option key={schema.resource_id} value={schema.identity_key}>{label(schema.identity_key)}</option>)}</select></label>
      <label>Name or business key<input name="search" maxLength={128} placeholder="Search this object type" /></label>
      <label>Property equals<select value={field} onChange={event => setField(event.target.value)}><option value="">No property filter</option>{Object.entries(fields).filter(([, spec]) => !["money", "quantity", "geometry", "geojson"].includes(spec.kind)).map(([name]) => <option key={name} value={name}>{label(name)}</option>)}</select></label>
      {field && <label>Property value{fields[field]?.kind === "boolean" ? <select name="value"><option value="true">True</option><option value="false">False</option></select> : <input name="value" required maxLength={256} placeholder={fields[field]?.kind === "reference" ? "Canonical object ID" : "Exact value"} />}</label>}
      <label>Follow relationship<select key={kind} name="traversal"><option value="">Return matching objects</option><optgroup label="Reference properties">{references.map(([name]) => <option key={name} value={`reference:${name}`}>{label(name)}</option>)}</optgroup><optgroup label="Typed links">{links.map(link => <option key={link.resource_id} value={`link:${link.identity_key}`}>{link.display_name}</option>)}</optgroup></select></label>
      <label>Direction<select name="direction"><option value="outgoing">From matching objects</option><option value="incoming">Into matching objects</option></select></label>
      <button disabled={busy || !schemas.length}>{busy ? "Querying…" : "Explore objects"}</button>
    </form>
    {error && <p className="error-banner" role="alert">{error}</p>}
    {result && <>
      <div className="toolbar"><h3>{result.total.toLocaleString()} matching object versions</h3><span>{Object.entries(result.counts_by_type).map(([type, count]) => `${label(type)}: ${count}`).join(" · ")}</span></div>
      <p className="muted">{result.query.traversal.length ? "Relationships return the exact versions they reference, which may differ from today's values. " : "Effective objects at the query time. "}Counts cover the full result, not just this page.</p>
      <div className="data-scroll"><table><thead><tr><th>Object</th><th>Type</th><th>Values & provenance</th></tr></thead><tbody>{result.objects.map(object => <tr key={object.version_id}><td>{object.display_name}<small>{object.identity_key}</small></td><td>{label(object.object_type)}</td><td><details><summary>Inspect returned version</summary><dl className="resource-fields">{Object.entries(object.attributes).map(([key, value]) => <div key={key}><dt>{label(key)}</dt><dd>{typeof value === "object" ? JSON.stringify(value) : String(value)}</dd></div>)}</dl><p>Object: {object.resource_id}</p><p>Version: {object.version_id}</p><p>Evidence: {label(object.evidence_class)}</p><p>Effective from: {object.valid_from}</p></details></td></tr>)}</tbody></table></div>
      {!result.total && <p className="empty-state">No objects match this query. Try another type, value or relationship.</p>}
      <div className="toolbar"><button className="quiet" disabled={busy || result.query.offset === 0} onClick={() => void run({ ...result.query, offset: Math.max(0, result.query.offset - result.query.limit) })}>Previous</button><span>{result.total ? result.query.offset + 1 : 0}–{Math.min(result.query.offset + result.objects.length, result.total)} of {result.total}</span><button className="quiet" disabled={busy || result.next_offset === null} onClick={() => void run({ ...result.query, offset: result.next_offset ?? 0 })}>Next</button></div>
      <details><summary>Reusable query contract</summary><p>Time is fixed across pages. Run Explore objects again to refresh.</p><pre>{JSON.stringify(result.query, null, 2)}</pre></details>
    </>}
  </section>;
}
