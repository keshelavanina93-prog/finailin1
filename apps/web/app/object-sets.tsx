"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import type { CanonicalResource, SchemaField } from "@finai/contracts";
import ObjectBindingAction from "./object-binding-action";
import DerivedPropertyRun from "./derived-property-run";
import OntologyDefinitionEditor from "./ontology-definition-editor";

type Query = {
  object_type: string; search: string; filters: { field: string; value: string | number | boolean }[];
  traversal: { kind: "reference" | "link"; name: string; direction: "outgoing" | "incoming" }[];
  offset: number; limit: number; valid_at?: string; known_at?: string;
};
type Result = { query: Query; total: number; counts_by_type: Record<string, number>; objects: CanonicalResource[]; next_offset: number | null; definition_id?: string; definition_version_id?: string; filter_schema_versions?: {object_type:string;resource_id:string;version_id:string}[] };
const label = (value: string) => value.replaceAll("_", " ").replace(/([a-z])([A-Z])/g, "$1 $2");

export default function ObjectSets({ token, catalog: suppliedCatalog, onProposal }: { token: string; catalog?: CanonicalResource[]; onProposal?: (id: string) => void }) {
  const [loadedCatalog, setLoadedCatalog] = useState<CanonicalResource[]>([]);
  const catalog = suppliedCatalog ?? loadedCatalog;
  const schemas = catalog.filter(item => item.object_type === "SchemaDefinition");
  const [kind, setKind] = useState("LegalEntity");
  const [field, setField] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [definitions, setDefinitions] = useState<CanonicalResource[]>([]);
  const [libraryId, setLibraryId] = useState("");
  const [publication, setPublication] = useState("");
  const [executionFamily, setExecutionFamily] = useState<"sets" | "groups" | null>(null);
  const generation = useRef(0);
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/ontology/model/definitions", { headers: { Authorization: `Bearer ${token}` }, cache: "no-store", signal: controller.signal })
      .then(async response => { if (!response.ok) throw new Error("Published ontology definitions are unavailable."); return response.json(); })
      .then(data => { if (!controller.signal.aborted) setDefinitions(data); })
      .catch(cause => { if (!controller.signal.aborted) setError(cause.message); });
    return () => controller.abort();
  }, [token]);
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

  async function openPublished(page?: Result, offset = 0) {
    const selected = definitions.find(item => item.resource_id === (page?.definition_id ?? libraryId));
    if (!selected) return;
    const request = ++generation.current;
    setBusy(true); setError(""); setResult(null);
    try {
      const family = selected.object_type === "ObjectSetDefinition" ? "sets" : "groups";
      const params = new URLSearchParams({ offset: String(offset), limit: String(page?.query.limit ?? 50), version: page?.definition_version_id ?? selected.version_id });
      if (page?.query.valid_at) params.set("valid_at", page.query.valid_at);
      if (page?.query.known_at) params.set("known_at", page.query.known_at);
      const response = await fetch(`/api/ontology/model/${family}/${selected.resource_id}/objects?${params}`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Published query failed");
      if (generation.current === request) { setResult(data); setExecutionFamily(family); }
    } catch (cause) { if (generation.current === request) setError(cause instanceof Error ? cause.message : "Query failed"); }
    finally { if (generation.current === request) setBusy(false); }
  }

  async function publish(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!result || executionFamily === "groups") return;
    const fields = new FormData(event.currentTarget);
    const name = String(fields.get("setName") ?? "").trim();
    const rationale = String(fields.get("rationale") ?? "").trim();
    const fixed = fields.get("fixed") === "on";
    setBusy(true); setError(""); setPublication("");
    try {
      const response = await fetch("/api/ontology/model/definitions", { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ kind: "ObjectSetDefinition", key: `set:${crypto.randomUUID()}`, name, rationale, attributes: { definition: { ...result.query, offset: 0, valid_at: fixed ? result.query.valid_at : null, known_at: fixed ? result.query.known_at : null } } }) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "The definition could not be proposed.");
      setPublication(data.proposal.proposal_id);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Publication failed"); }
    finally { setBusy(false); }
  }

  async function run(query: Query) {
    const request = ++generation.current;
    setBusy(true); setError(""); setResult(null);
    try {
      const response = await fetch("/api/ontology/object-sets/query", { method: "POST", cache: "no-store",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify(query) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "The object query could not be evaluated.");
      if (request === generation.current) { setResult(data); setExecutionFamily(null); }
    } catch (cause) { if (request === generation.current) setError(cause instanceof Error ? cause.message : "Query failed"); }
    finally { if (request === generation.current) setBusy(false); }
  }

  function goToPage(offset: number) {
    if (!result) return;
    if (result.definition_id) void openPublished(result, offset);
    else void run({ ...result.query, offset });
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
    <OntologyDefinitionEditor token={token} definitions={definitions} onProposal={onProposal}/>
    <div className="resource-form"><label>Published sets and type groups<select value={libraryId} onChange={event => setLibraryId(event.target.value)}><option value="">Choose a published definition</option>{definitions.filter(item => ["ObjectSetDefinition", "ObjectInterface", "ObjectTypeGroup"].includes(item.object_type)).map(item => <option key={item.resource_id} value={item.resource_id}>{item.display_name} · {label(item.object_type)}</option>)}</select></label><button type="button" disabled={busy || !libraryId} onClick={() => void openPublished()}>Open published set</button></div>
    <form className="resource-form" onSubmit={submit}>
      <label>Object type<select value={kind} onChange={event => { setKind(event.target.value); setField(""); }}>{schemas.map(schema => <option key={schema.resource_id} value={schema.identity_key}>{label(schema.identity_key)}</option>)}</select></label>
      <label>Name or business key<input name="search" maxLength={128} placeholder="Search this object type" /></label>
      <label>Property equals<select value={field} onChange={event => setField(event.target.value)}><option value="">No property filter</option>{Object.entries(fields).filter(([, spec]) => !["money", "quantity", "geometry", "geojson", "definition"].includes(spec.kind)).map(([name]) => <option key={name} value={name}>{label(name)}</option>)}</select></label>
      {field && <label>Property value{fields[field]?.kind === "boolean" ? <select name="value"><option value="true">True</option><option value="false">False</option></select> : <input key={field} name="value" type={fields[field]?.kind === "date" ? "date" : "text"} required maxLength={256} placeholder={fields[field]?.kind === "reference" ? "Canonical object ID" : fields[field]?.kind === "datetime" ? "ISO timestamp with timezone" : "Exact value"} />}</label>}
      <label>Follow relationship<select key={kind} name="traversal"><option value="">Return matching objects</option><optgroup label="Reference properties">{references.map(([name]) => <option key={name} value={`reference:${name}`}>{label(name)}</option>)}</optgroup><optgroup label="Typed links">{links.map(link => <option key={link.resource_id} value={`link:${link.identity_key}`}>{link.display_name}</option>)}</optgroup></select></label>
      <label>Direction<select name="direction"><option value="outgoing">From matching objects</option><option value="incoming">Into matching objects</option></select></label>
      <button disabled={busy || !schemas.length}>{busy ? "Querying…" : "Explore objects"}</button>
    </form>
    {error && <p className="error-banner" role="alert">{error}</p>}
    {result && <>
      <div className="toolbar"><h3>{result.total.toLocaleString()} matching object versions</h3><span>{Object.entries(result.counts_by_type).map(([type, count]) => `${label(type)}: ${count}`).join(" · ")}</span></div>
      <p className="muted">{result.query.traversal.length ? "Relationships return the exact versions they reference, which may differ from today's values. " : "Effective objects at the query time. "}Counts cover the full result, not just this page.</p>
      {!!result.filter_schema_versions?.length && <details><summary>Property filters validated against the query-time schema</summary>{result.filter_schema_versions.map(schema=><p key={schema.version_id}>{label(schema.object_type)} · Schema version <code>{schema.version_id}</code></p>)}</details>}
      <div className="data-scroll"><table><thead><tr><th>Object</th><th>Type</th><th>Values & provenance</th></tr></thead><tbody>{result.objects.map(object => <tr key={object.version_id}><td>{object.display_name}<small>{object.identity_key}</small></td><td>{label(object.object_type)}</td><td><details><summary>Inspect returned version</summary><dl className="resource-fields">{Object.entries(object.attributes).map(([key, value]) => <div key={key}><dt>{label(key)}</dt><dd>{typeof value === "object" ? JSON.stringify(value) : String(value)}</dd></div>)}</dl><p>Object: {object.resource_id}</p><p>Version: {object.version_id}</p><p>Evidence: {label(object.evidence_class)}</p><p>Effective from: {object.valid_from}</p></details></td></tr>)}</tbody></table></div>
      {!result.total && <p className="empty-state">No objects match this query. Try another type, value or relationship.</p>}
      <div className="toolbar"><button className="quiet" disabled={busy || result.query.offset === 0} onClick={() => goToPage(Math.max(0, result.query.offset - result.query.limit))}>Previous</button><span>{result.total ? result.query.offset + 1 : 0}–{Math.min(result.query.offset + result.objects.length, result.total)} of {result.total}</span><button className="quiet" disabled={busy || result.next_offset === null} onClick={() => goToPage(result.next_offset ?? 0)}>Next</button></div>
      <details><summary>Reusable query contract</summary><p>Time is fixed across pages. Run Explore objects again to refresh.</p><pre>{JSON.stringify(result.query, null, 2)}</pre></details>
      <DerivedPropertyRun key={`derived:${JSON.stringify(result.query)}`} token={token} definitions={definitions.filter(item => item.object_type === "DerivedProperty")} query={result.query}/>
      {executionFamily !== "groups" && <ObjectBindingAction key={JSON.stringify(result.query)} token={token} bindings={definitions.filter(item => item.object_type === "ObjectBinding")} query={result.query} count={result.total} onProposal={onProposal}/>}
      {executionFamily !== "groups" && <details><summary>Save this Object Set for shared use</summary><form className="resource-form" onSubmit={publish}><label>Set name<input name="setName" required maxLength={200}/></label><label>Purpose and review rationale<input name="rationale" required minLength={10} maxLength={2000}/></label><label><input type="checkbox" name="fixed"/>Keep this exact query time</label><button disabled={busy}>Propose publication</button></form><p>Without a fixed time, the accepted definition returns effective objects when it is run. Publication uses the shared change-review process.</p></details>}
    </>}
    {publication && <p role="status">Object Set proposed for review. {onProposal ? <button onClick={() => onProposal(publication)}>Open change review</button> : <span>Proposal: {publication}</span>}</p>}
  </section>;
}
