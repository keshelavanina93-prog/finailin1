"use client";

import { useEffect, useRef, useState } from "react";
import type { CanonicalResource } from "@finai/contracts";
import "./derived-property-run.css";

type Pin = { resource_id: string; version_id: string; content_hash?: string };
type SourceField = {
  object_id: string; object_version_id: string; object_content_hash: string;
  schema_version_id: string; field: string; state: "MISSING" | "NULL" | "VALUE"; value: unknown;
};
type Value = {
  object_id: string; object_version_id: string; definition_id: string;
  definition_version_id: string; name: string; value: unknown; status: string;
  reason?: string; content_hash?: string; schema?: Pin; source_fields?: SourceField[];
};
type Run = {
  run_id: string; contract: string; coverage: string;
  query: { offset: number; limit: number; valid_at?: string; known_at?: string };
  total: number; objects?: CanonicalResource[];
  derived_values: (Value & { dependency_values?: Value[] })[];
  derived_graph?: { roots: Pin[]; nodes: (Pin & { schema: Pin; dependencies: Pin[] })[] };
};
type Props = { token: string; definitions: CanonicalResource[]; query: unknown };
const human = (value: string) => value.toLowerCase().replaceAll("_", " ");
const display = (value: unknown) => value === null || value === undefined ? "No value" : typeof value === "string" ? value : JSON.stringify(value);
const date = (value?: string) => value ? new Date(value).toLocaleString() : "Not retained";

function References({ value }: { value: unknown }) {
  return <details className="derived-run-references"><summary>Exact retained references</summary><pre>{JSON.stringify(value, null, 2)}</pre></details>;
}

function SourceFields({ fields }: { fields?: SourceField[] }) {
  if (!fields) return <p>Field-level read evidence was not retained in this calculation.</p>;
  if (!fields.length) return <p>No direct source fields were read for this value.</p>;
  return <ul className="derived-run-inputs">{fields.map(field => <li key={`${field.object_version_id}:${field.field}`}>
    <strong>{field.field}</strong><span>{human(field.state)}{field.state === "VALUE" ? `: ${display(field.value)}` : ""}</span>
    <References value={{ object_id: field.object_id, object_version_id: field.object_version_id, object_content_hash: field.object_content_hash, schema_version_id: field.schema_version_id }} />
  </li>)}</ul>;
}

export default function DerivedPropertyRun(props: Props) {
  return <Calculation key={JSON.stringify([props.token, props.query])} {...props} />;
}

function Calculation({ token, definitions, query }: Props) {
  const [selected, setSelected] = useState("");
  const [run, setRun] = useState<Run | null>(null);
  const [saved, setSaved] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => { active.current?.abort(); active.current = null; }, []);

  async function execute(reopen = false) {
    const definition = definitions.find(row => row.resource_id === selected);
    if (!reopen && !definition) return;
    const retainedId = saved;
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    const timeout = setTimeout(() => controller.abort(), 20000);
    setBusy(true); setError(""); setRun(null);
    try {
      const response = await fetch(reopen ? `/api/ontology/model/fact-runs/${retainedId}` : "/api/ontology/model/derived/query", {
        method: reopen ? "GET" : "POST", signal: controller.signal,
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        ...(!reopen ? { body: JSON.stringify({ query, definitions: [definition!.resource_id], definition_versions: { [definition!.resource_id]: definition!.version_id } }) } : {}),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Calculation unavailable");
      if (result.contract !== "ontology-derived-result/1" || result.coverage !== "QUERY_PAGE_ONLY" ||
          !/^fcr_[a-f0-9]{64}$/.test(result.run_id) || !Array.isArray(result.derived_values) ||
          !result.query || !Number.isInteger(result.query.offset) || !Number.isInteger(result.query.limit) ||
          !Number.isInteger(result.total) || (reopen && result.run_id !== retainedId)) {
        throw new Error("This response is not the requested retained page calculation.");
      }
      if (active.current !== controller) return;
      setRun(result); setSaved(result.run_id);
    } catch (failure) {
      if (active.current === controller) setError(controller.signal.aborted
        ? "The response timed out. Completion is unknown; reopen a retained calculation if you have its reference."
        : failure instanceof Error ? failure.message : "Calculation failed");
    } finally {
      clearTimeout(timeout);
      if (active.current === controller) { active.current = null; setBusy(false); }
    }
  }

  return <details className="derived-run"><summary>Calculate derived properties</summary>
    <p>Evaluate a reviewed property on this page of object versions. These derived values do not establish accounting or action authority.</p>
    <div className="derived-run-controls">
      <label>Published derived property<select disabled={busy} value={selected} onChange={event => setSelected(event.target.value)}>
        <option value="">Choose a property</option>{definitions.map(row => <option key={row.resource_id} value={row.resource_id}>{row.display_name}</option>)}
      </select></label>
      <button disabled={busy || !definitions.some(row => row.resource_id === selected)} onClick={() => void execute()}>Calculate and retain result</button>
    </div>
    {!definitions.length && <p>No derived-property definitions have been published in this context.</p>}
    <details><summary>Reopen a retained calculation</summary><div className="derived-run-controls">
      <label>Retained calculation reference<input disabled={busy} value={saved} onChange={event => setSaved(event.target.value)} placeholder="fcr_…" /></label>
      <button disabled={busy || !/^fcr_[a-f0-9]{64}$/.test(saved)} onClick={() => void execute(true)}>Reopen retained calculation</button>
    </div></details>
    {busy && <p role="status">Reading calculation result…</p>}
    {error && <p role="alert">{error}</p>}
    {run && <section aria-label="Derived calculation result">
      <p>Retained page: offset {run.query.offset}, limit {run.query.limit}, from {run.total} matching objects. Values cover this page only, not a total over the full set.</p>
      <p>Effective context: {date(run.query.valid_at)} · Known context: {date(run.query.known_at)}. A reopened calculation keeps its original context.</p>
      {!run.derived_values.length && <p>No derived values were returned for this retained page.</p>}
      {!!run.derived_values.length && <div className="derived-run-table"><table><thead><tr><th>Original object</th><th>Property</th><th>Result</th><th>Availability & inputs</th></tr></thead>
        <tbody>{run.derived_values.map(row => {
          const object = run.objects?.find(item => item.resource_id === row.object_id && item.version_id === row.object_version_id);
          return <tr key={`${row.object_version_id}:${row.definition_version_id}`}>
            <td><strong>{object?.display_name ?? "Original object name not retained"}</strong>{object && <small>{object.object_type}</small>}</td>
            <td>{row.name}</td><td className="derived-run-value">{display(row.value)}</td>
            <td><span>{human(row.status)}</span>{row.reason && <p>{row.reason}</p>}
              <details><summary>Inputs & derivation</summary>
                <h4>Direct source reads</h4><SourceFields fields={row.source_fields} />
                {row.dependency_values && <><h4>Evaluated dependencies</h4>
                  <p>Only dependencies actually evaluated for this object are listed; unused fallback branches are excluded.</p>
                  {!row.dependency_values.length && <p>No dependency values were evaluated.</p>}
                  {row.dependency_values.map(dependency => <details key={`${dependency.definition_version_id}:${dependency.object_version_id}`}>
                    <summary>{dependency.name} · {human(dependency.status)} · {display(dependency.value)}</summary>
                    {dependency.reason && <p>{dependency.reason}</p>}
                    <SourceFields fields={dependency.source_fields} />
                    <References value={{ property_id: dependency.definition_id, property_version_id: dependency.definition_version_id, content_hash: dependency.content_hash, schema: dependency.schema, object_id: dependency.object_id, object_version_id: dependency.object_version_id }} />
                  </details>)}
                </>}
                <References value={{ object_id: row.object_id, object_version_id: row.object_version_id, definition_id: row.definition_id, definition_version_id: row.definition_version_id }} />
              </details>
            </td>
          </tr>;
        })}</tbody></table></div>}
      {run.derived_graph && <details><summary>Declared calculation graph · {run.derived_graph.nodes.length} definitions</summary>
        <p>These are the pinned definition dependencies. Their presence does not mean every branch was evaluated; actual reads appear with each result.</p>
        {run.derived_graph.nodes.map(node => {
          const value = run.derived_values.flatMap(row => [row, ...(row.dependency_values ?? [])]).find(row => row.definition_id === node.resource_id && row.definition_version_id === node.version_id);
          return <details key={node.version_id}><summary>{value?.name ?? "Retained property definition"} · {node.dependencies.length} declared dependencies</summary><References value={node} /></details>;
        })}
      </details>}
      <References value={{ run_id: run.run_id, contract: run.contract, coverage: run.coverage, query: run.query, roots: run.derived_graph?.roots }} />
    </section>}
  </details>;
}
