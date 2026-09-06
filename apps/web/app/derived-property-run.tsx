"use client";

import { useState } from "react";
import type { CanonicalResource } from "@finai/contracts";

type Run = { run_id: string; contract: string; coverage: string; query: { offset: number; limit: number }; total: number;
  derived_values: { object_id: string; object_version_id: string; definition_version_id: string; name: string; value: string | null; status: string; reason?: string }[] };

export default function DerivedPropertyRun({ token, definitions, query }: {
  token: string; definitions: CanonicalResource[]; query: unknown;
}) {
  const [selected, setSelected] = useState("");
  const [run, setRun] = useState<Run | null>(null);
  const [saved, setSaved] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function execute(reopen = false) {
    const definition = definitions.find(row => row.resource_id === selected);
    if (!reopen && !definition) return;
    setBusy(true); setError("");
    try {
      const response = await fetch(reopen ? `/api/ontology/model/fact-runs/${saved}` : "/api/ontology/model/derived/query", {
        method: reopen ? "GET" : "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        ...(!reopen ? { body: JSON.stringify({ query, definitions: [definition!.resource_id], definition_versions: { [definition!.resource_id]: definition!.version_id } }) } : {}),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Calculation unavailable");
      if (result.contract !== "ontology-derived-result/1") throw new Error("This record is not a derived-property calculation");
      setRun(result); setSaved(result.run_id);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Calculation failed"); }
    finally { setBusy(false); }
  }
  return <details><summary>Calculate derived properties</summary>
    <p>Evaluate the selected published property on this page of object versions. Results retain their definition, source versions and query time.</p>
    <label>Published derived property<select disabled={busy} value={selected} onChange={event => setSelected(event.target.value)}><option value="">Choose a property</option>{definitions.map(row => <option key={row.resource_id} value={row.resource_id}>{row.display_name}</option>)}</select></label>
    {!definitions.length && <p>No derived-property definitions have been published in this context.</p>}
    <button disabled={busy || !selected} onClick={() => void execute()}>Calculate and retain result</button>
    <label>Retained calculation ID<input value={saved} onChange={event => setSaved(event.target.value)} placeholder="fcr_…"/></label>
    <button disabled={busy || !/^fcr_[a-f0-9]{64}$/.test(saved)} onClick={() => void execute(true)}>Reopen retained calculation</button>
    {error && <p role="alert">{error}</p>}
    {run && <section aria-label="Derived calculation result"><p>Calculation: <code>{run.run_id}</code></p><p>Page at offset {run.query.offset}; at most {run.query.limit} objects from {run.total} matches. This is not a total over the full set.</p>
      <div className="data-scroll"><table><thead><tr><th>Object version</th><th>Property</th><th>Value</th><th>Availability</th><th>Definition version</th></tr></thead><tbody>{run.derived_values.map(row => <tr key={`${row.object_version_id}:${row.definition_version_id}`}><td>{row.object_version_id}</td><td>{row.name}</td><td>{row.value ?? "—"}</td><td>{row.status}{row.reason ? `: ${row.reason}` : ""}</td><td>{row.definition_version_id}</td></tr>)}</tbody></table></div>
    </section>}
  </details>;
}
