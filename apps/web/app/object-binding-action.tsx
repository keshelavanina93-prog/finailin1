"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import type { CanonicalResource } from "@finai/contracts";

type Operation = { operation_id: string; prepared_proposal_id: string; state: string; proposal: unknown | null };

export default function ObjectBindingAction({ token, bindings, query, count, onProposal, inputResult, preview, blockedReason, onRequestFrozen }: {
  token: string; bindings: CanonicalResource[]; query: unknown; count: number;
  onProposal?: (id: string) => void; inputResult?: {invocation_id:string}; preview?:ReactNode; blockedReason?:string; onRequestFrozen?:(frozen:boolean)=>void;
}) {
  const [bindingId, setBindingId] = useState(bindings.length===1?bindings[0].resource_id:"");
  const [rationale, setRationale] = useState("");
  const [operations, setOperations] = useState<Operation[]>([]);
  const [frozen, setFrozen] = useState(false);
  const active = useRef<AbortController|null>(null);
  useEffect(()=>()=>{active.current?.abort();active.current=null;},[]);
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
    if (!selected || busy || (!operation && blockedReason)) return;
    const controller=new AbortController();active.current=controller;
    setBusy(true); setError("");
    try {
      const content = JSON.stringify({ binding_id: selected.resource_id, binding_version_id: selected.version_id, query, rationale, ...(inputResult?{input_result:inputResult}:{}) });
      if (request.current?.content !== content) request.current = { content, id: crypto.randomUUID() };
      if(!operation){setFrozen(true);onRequestFrozen?.(true);}
      const resume = operation?.state === "PREPARED";
      const response = await fetch(`/api/ontology/operations/${operation ? operation.operation_id + (resume ? "/resume" : "") : "bindings"}`, {
        method: !operation || resume ? "POST" : "GET", signal:controller.signal,
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        ...(!operation ? { body: JSON.stringify({ ...JSON.parse(content), request_id: request.current.id }) } : {}),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Binding operation rejected");
      if(active.current!==controller)return;
      setOperations(current => [result, ...current.filter(row => row.operation_id !== result.operation_id)]);
    } catch (failure) { if(active.current===controller)setError(failure instanceof Error ? failure.message : "Binding operation failed"); }
    finally { if(active.current===controller){active.current=null;setBusy(false);} }
  }

  return <details><summary>Apply a published Object Binding</summary>
    <p>Prepare mapped changes through the shared change-review process. The source query time, source versions and binding version are retained with the operation.</p>
    {!bindings.length ? <p>No published Object Bindings are available. Publish a source-to-target binding definition before running an action.</p> : <>
      <label>Object Binding<select disabled={busy||frozen} value={bindingId} onChange={event => { setBindingId(event.target.value); setOperations([]); setError(""); }}><option value="">Choose a binding</option>{bindings.map(row => <option key={row.resource_id} value={row.resource_id}>{row.display_name}</option>)}</select></label>
      {selected && <>
        {preview}<details><summary>Reviewed binding version</summary><code>{selected.version_id}</code></details>
        <details><summary>Inspect mapping contract</summary><pre>{JSON.stringify(selected.attributes, null, 2)}</pre></details>
        <label>Binding operation rationale<textarea disabled={busy||frozen} value={rationale} onChange={event => setRationale(event.target.value)} minLength={10} maxLength={2000}/></label>
        <p>{count} source objects selected. Each atomic binding operation supports 1–100 source objects with matching schema versions.</p>
        <button disabled={busy || !!blockedReason || count < 1 || count > 100 || rationale.trim().length < 10} onClick={() => void act()}>{frozen?"Retry exact binding proposal":"Prepare binding proposal"}</button>
        {blockedReason&&<p role="alert">{blockedReason}</p>}
        {frozen&&!busy&&<button onClick={()=>{setFrozen(false);onRequestFrozen?.(false);request.current=null;setRationale("");}}>Start another binding request</button>}
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
