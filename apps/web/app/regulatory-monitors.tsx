"use client";

import { useCallback, useEffect, useState } from "react";

type Monitor = { workflow_id: string; request: { name: string; document_number: string; publication: number; cadence_hours: number } };
type Check = { event_id: string; state: string; created_at: string; reason?: string; document?: { document_id: string }; signature?: { completeness: string; advertised_publications: number[] } };
type Detail = Monitor & { source_health: string; freshness: string; last_success: Check | null; last_new_item: Check | null; events: Check[]; runtime: { state: string; next_checks: string[]; running_checks?: number } };

export default function RegulatoryMonitors({ token, documentNumber, publication, onInspect }: {
  token: string; documentNumber: string; publication: number; onInspect: (id: string) => void;
}) {
  const [rows, setRows] = useState<Monitor[]>([]);
  const [selected, setSelected] = useState<Detail | null>(null);
  const [name, setName] = useState("");
  const [hours, setHours] = useState(24);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  // Retain identity across uncertain responses so retry cannot create a duplicate schedule.
  const [requestId, setRequestId] = useState<string | null>(null);
  const call = useCallback(async (path: string, body?: unknown, signal?: AbortSignal) => {
    const response = await fetch(`/api/ontology/regulation/monitors${path}`, {
      method: body === undefined ? "GET" : "POST", signal,
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const value = await response.json();
    if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : "Monitor request failed");
    return value;
  }, [token]);
  useEffect(() => {
    const controller = new AbortController();
    void call("", undefined, controller.signal).then(setRows).catch(e => { if (!controller.signal.aborted) setError(String(e)); });
    return () => controller.abort();
  }, [call]);
  async function run(action: () => Promise<void>) {
    setBusy(true); setError("");
    try { await action(); } catch (e) { setError(e instanceof Error ? e.message : "Monitor unavailable"); }
    finally { setBusy(false); }
  }
  async function create() {
    const identity = requestId ?? crypto.randomUUID(); setRequestId(identity);
    const result = await call("", { request_id: identity, name, cadence_hours: hours, rationale: reason, document_number: documentNumber, publication });
    setRows(await call("")); setSelected(await call(`/${result.workflow_id}`)); setRequestId(null);
  }
  async function control(command: "pause" | "resume") {
    await call(`/${selected!.workflow_id}/control`, { command, reason, idempotency_key: crypto.randomUUID() });
    setSelected(await call(`/${selected!.workflow_id}`));
  }
  return <section aria-label="Regulatory source monitoring">
    <h3>Scheduled source checks</h3>
    <p>Monitor the selected Matsne document and exact publication, including newly advertised publication numbers. Changes require source inspection and review. Pausing prevents future checks; a running check can finish.</p>
    <label>Monitor name<input value={name} onChange={e => { setName(e.target.value); setRequestId(null); }}/></label>
    <label>Check every (hours)<input type="number" min={1} max={720} value={hours} onChange={e => { setHours(Number(e.target.value)); setRequestId(null); }}/></label>
    <label>Monitoring rationale<textarea value={reason} onChange={e => { setReason(e.target.value); setRequestId(null); }}/></label>
    <button disabled={busy || name.length < 3 || reason.length < 10 || !/^[1-9][0-9]{0,11}$/.test(documentNumber)} onClick={() => void run(create)}>Start source monitor</button>
    <button disabled={busy} onClick={() => void run(async () => setRows(await call("")))}>Refresh monitors</button>
    <p>Most recent 100 monitors in this workspace.</p>
    {rows.map(row => <div key={row.workflow_id}><button disabled={busy} onClick={() => void run(async () => setSelected(await call(`/${row.workflow_id}`)))}>{row.request.name}</button> · Matsne {row.request.document_number}, publication {row.request.publication} · every {row.request.cadence_hours} hours</div>)}
    {selected && <section aria-label="Selected regulatory monitor">
      <h4>{selected.request.name}</h4><p>{selected.runtime.state} · Source health: {selected.source_health} · {selected.freshness}</p>
      <p>Last successful check: {selected.last_success?.created_at ?? "None"}. Running checks: {selected.runtime.running_checks ?? "Unknown"}.</p>
      <p>Last new source observation: {selected.last_new_item?.created_at ?? "None"}. Publisher latency is unknown; freshness describes the checking schedule.</p>
      <p>Next scheduled check: {selected.runtime.state === "PAUSED" ? "Paused" : selected.runtime.next_checks[0] ?? "Unavailable"}</p>
      <button disabled={busy} onClick={() => void run(async () => setSelected(await call(`/${selected.workflow_id}`)))}>Refresh source health</button>
      <button disabled={busy || reason.length < 10} onClick={() => void run(() => control(selected.runtime.state === "PAUSED" ? "resume" : "pause"))}>{selected.runtime.state === "PAUSED" ? "Resume monitor" : "Pause monitor"}</button>
      <details><summary>Retained checks and control history ({selected.events.length})</summary>
        {selected.events.map(event => <div key={event.event_id}><p>{event.created_at} · {event.state ?? event.event_id} {event.reason}</p>
          {event.signature && <p>{event.signature.completeness}. Advertised publications: {event.signature.advertised_publications.join(", ")}</p>}
          {event.document && <button onClick={() => onInspect(event.document!.document_id)}>Inspect retained source</button>}
        </div>)}
      </details>
    </section>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
