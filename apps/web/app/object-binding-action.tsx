"use client";

import { useEffect, useRef, useState } from "react";
import type { CanonicalResource } from "@finai/contracts";

type Operation = { operation_id: string; prepared_proposal_id: string; state: string; proposal: unknown | null };

export default function ObjectBindingAction({ token, bindings, query, count, onProposal }: {
  token: string; bindings: CanonicalResource[]; query: unknown; count: number;
  onProposal?: (id: string) => void;
}) {
  const [bindingId, setBindingId] = useState("");
  const [rationale, setRationale] = useState("");
  const [operations, setOperations] = useState<Operation[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const request = useRef<{ content: string; id: string } | null>(null);
  const selected = bindings.find(row => row.resource_id === bindingId);
  useEffect(() => {
    if (!bindingId) return;
    const controller = new AbortController();
    fetch(`/api/ontology/operations?binding_id=${encodeURIComponent(bindingId)}`, {
      headers: { Authorization: `Bearer ${token}` }, signal: controller.signal,
    }).then(async response => {
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Cannot read binding operations");
      if (!controller.signal.aborted) setOperations(result.operations);
    }).catch(failure => { if (!controller.signal.aborted) setError(String(failure)); });
    return () => controller.abort();
  }, [bindingId, token]);

  async function act(operation?: Operation) {
    if (!selected || busy) return;
    setBusy(true); setError("");
    try {
      const content = JSON.stringify({ binding_id: selected.resource_id, binding_version_id: selected.version_id, query, rationale });
      if (request.current?.content !== content) request.current = { content, id: crypto.randomUUID() };
      const resume = operation?.state === "PREPARED";
      const response = await fetch(`/api/ontology/operations/${operation ? operation.operation_id + (resume ? "/resume" : "") : "bindings"}`, {
        method: !operation || resume ? "POST" : "GET",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        ...(!operation ? { body: JSON.stringify({ ...JSON.parse(content), request_id: request.current.id }) } : {}),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Binding operation rejected");
      setOperations(current => [result, ...current.filter(row => row.operation_id !== result.operation_id)]);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Binding operation failed"); }
    finally { setBusy(false); }
  }

  return <details><summary>Apply a published Object Binding</summary>
    <p>Publish mapped objects from this query through the shared change-review process. The source query time, source versions and binding version are retained with the operation.</p>
    {!bindings.length ? <p>No published Object Bindings are available. Publish a source-to-target binding definition before running an action.</p> : <>
      <label>Object Binding<select disabled={busy} value={bindingId} onChange={event => { setBindingId(event.target.value); setOperations([]); setError(""); }}><option value="">Choose a binding</option>{bindings.map(row => <option key={row.resource_id} value={row.resource_id}>{row.display_name}</option>)}</select></label>
      {selected && <>
        <p>Definition version: <code>{selected.version_id}</code></p>
        <details><summary>Inspect mapping contract</summary><pre>{JSON.stringify(selected.attributes, null, 2)}</pre></details>
        <label>Binding operation rationale<textarea value={rationale} onChange={event => setRationale(event.target.value)} minLength={10} maxLength={2000}/></label>
        <p>{count} source objects selected. Each atomic binding operation supports 1–100 source objects with matching schema versions.</p>
        <button disabled={busy || count < 1 || count > 100 || rationale.trim().length < 10} onClick={() => void act()}>Prepare binding proposal</button>
        <section aria-label="Retained binding operations">{operations.map(operation => <article key={operation.operation_id}>
          <p>{operation.state.replaceAll("_", " ")}</p><details><summary>Operation identity</summary><code>{operation.operation_id}</code></details>
          <button disabled={busy} onClick={() => void act(operation)}>{operation.state === "PREPARED" ? "Resume prepared binding" : "Refresh binding outcome"}</button>
          {!!operation.proposal && (onProposal ? <button onClick={() => onProposal(operation.prepared_proposal_id)}>Open binding review</button> : <p>Proposal: {operation.prepared_proposal_id}</p>)}
        </article>)}</section>
      </>}
    </>}
    {error && <p role="alert">{error}</p>}
  </details>;
}
