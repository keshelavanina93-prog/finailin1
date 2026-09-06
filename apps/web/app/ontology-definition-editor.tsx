"use client";

import { useEffect, useState } from "react";
import type { CanonicalResource } from "@finai/contracts";

export default function OntologyDefinitionEditor({ token, definitions, onProposal }: {
  token: string; definitions: CanonicalResource[]; onProposal?: (id: string) => void;
}) {
  const [identity, setIdentity] = useState("");
  const [kind, setKind] = useState("DerivedProperty");
  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const [attributes, setAttributes] = useState("{\n  \"definition\": {}\n}");
  const [rationale, setRationale] = useState("");
  const [contracts, setContracts] = useState<Record<string, unknown>>({});
  const [preview, setPreview] = useState<unknown>(null);
  const [proposal, setProposal] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const selected = definitions.find(row => row.resource_id === identity);
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/ontology/model/definitions/contracts", { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal })
      .then(async response => { if (!response.ok) throw new Error("Definition contracts unavailable"); return response.json(); })
      .then(result => { if (!controller.signal.aborted) setContracts(result.kinds); })
      .catch(failure => { if (!controller.signal.aborted) setError(String(failure)); });
    return () => controller.abort();
  }, [token]);
  function load(value: string) {
    const row = definitions.find(item => item.resource_id === value);
    setIdentity(value); setKind(row?.object_type ?? "DerivedProperty"); setKey(row?.identity_key ?? ""); setName(row?.display_name ?? "");
    setAttributes(JSON.stringify(row?.attributes ?? { definition: {} }, null, 2)); setRationale(""); setPreview(null); setProposal(""); setError("");
  }
  async function submit(publish: boolean) {
    setBusy(true); setError(""); setPreview(null);
    try {
      const response = await fetch(`/api/ontology/model/definitions${publish ? "" : "/preview"}`, {
        method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ kind, key, name, rationale, attributes: JSON.parse(attributes),
          ...(selected ? { resource_id: selected.resource_id, expected_version_id: selected.version_id } : {}) }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : JSON.stringify(result.detail));
      if (publish) setProposal(result.proposal.proposal_id); else setPreview(result);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Definition request failed"); }
    finally { setBusy(false); }
  }
  return <details><summary>Engineer ontology definitions</summary>
    <p>Create or revise a definition against published schemas and dependencies. Validation is advisory; publication and review recheck current versions.</p>
    <fieldset disabled={busy} onChange={() => { setPreview(null); setProposal(""); }}>
      <label>Definition to revise<select value={identity} onChange={event => load(event.target.value)}><option value="">New definition</option>{definitions.filter(row => row.object_type !== "RegulatoryRule").map(row => <option key={row.resource_id} value={row.resource_id}>{row.display_name} · {row.object_type}</option>)}</select></label>
      {selected && <p>Expected published version: <code>{selected.version_id}</code></p>}
      <label>Definition kind<select disabled={!!selected} value={kind} onChange={event => setKind(event.target.value)}>{Object.keys(contracts).map(value => <option key={value}>{value}</option>)}</select></label>
      <label>Definition business key<input disabled={!!selected} value={key} onChange={event => setKey(event.target.value)} maxLength={256}/></label>
      <label>Definition name<input value={name} onChange={event => setName(event.target.value)} maxLength={200}/></label>
      <label>Definition attributes JSON<textarea rows={14} value={attributes} onChange={event => setAttributes(event.target.value)}/></label>
      <details><summary>Definition structure contract</summary><p>The definition property follows this contract. Schema and other resource references belong alongside it in attributes.</p><pre>{JSON.stringify(contracts[kind], null, 2)}</pre></details>
      <label>Definition change rationale<textarea value={rationale} onChange={event => setRationale(event.target.value)} maxLength={2000}/></label>
      <button disabled={!key || !name || rationale.trim().length < 10} onClick={() => void submit(false)}>Validate definition and impact</button>
      <button disabled={!key || !name || rationale.trim().length < 10} onClick={() => void submit(true)}>Propose definition change</button>
    </fieldset>
    {preview !== null && <details open><summary>Validation and dependency impact</summary><pre>{JSON.stringify(preview, null, 2)}</pre></details>}
    {error && <p role="alert">{error}</p>}
    {proposal && <p role="status">Definition proposed for review. {onProposal ? <button onClick={() => onProposal(proposal)}>Open definition review</button> : <code>{proposal}</code>}</p>}
  </details>;
}
