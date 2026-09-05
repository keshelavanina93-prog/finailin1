"use client";

import { useState } from "react";

type Run = {
  workflow_id: string; runtime_status: string;
  execution?: { state: string; result: { assessment_id?: string } };
  definition: { nodes: Array<{ id: string; function: string; depends_on: string[] }> };
  events: Array<{ event_id: string; created_at: string; node: string; state?: string; command?: string; reason?: string }>;
};

export default function ReportWorkflow({ token, report }: { token: string; report: { period: string; company_label: string; currency: string; receipt_ids: string[] } }) {
  const [run, setRun] = useState<Run | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [reason, setReason] = useState("");
  async function api(path: string, body?: unknown) {
    const response = await fetch(`/api/workspace/workflows${path}`, {
      method: body ? "POST" : "GET", cache: "no-store",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    const value = await response.json();
    if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : "Workflow unavailable");
    return value;
  }
  async function action(command: string) {
    setBusy(true); setError("");
    try {
      let identity = run?.workflow_id;
      if (command === "start") identity = (await api("", { report })).workflow_id;
      else if (command === "latest") identity = (await api(""))[0]?.workflow_id;
      else if (command !== "refresh" && identity) {
        await api(`/${identity}/control`, { command, reason, idempotency_key: crypto.randomUUID() });
      }
      if (!identity) throw new Error("No retained workflow in this scope.");
      setRun(await api(`/${identity}`));
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Workflow failed"); }
    finally { setBusy(false); }
  }
  const state = run?.execution?.state;
  return <section aria-label="Durable report processing" className="data-panel">
    <h4>Report processing</h4>
    <p>Run source checks with recovery after interruption. Review acknowledges the assessment; it does not certify financial amounts.</p>
    <div className="upload-strip"><button disabled={busy} onClick={() => void action("start")}>Start durable processing</button><button disabled={busy} onClick={() => void action("latest")}>Reopen latest process</button>{run && <button disabled={busy} onClick={() => void action("refresh")}>Refresh status</button>}</div>
    {error && <p role="alert">{error}</p>}
    {run && <><p role="status">{state ?? run.runtime_status}</p><ol>{run.definition.nodes.map(node => <li key={node.id}>{node.id} · {node.depends_on.length ? `after ${node.depends_on.join(", ")}` : "starts first"}</li>)}</ol>
      <label>Reason for process action<input value={reason} onChange={event => setReason(event.target.value)} minLength={10} maxLength={2000} /></label>
      <div className="upload-strip">{(state === "PAUSED" ? ["resume", "cancel"] : state === "WAITING_REVIEW" ? ["pause", "retry", "complete", "cancel"] : state === "FAILED" ? ["retry", "cancel"] : []).map(command => <button key={command} disabled={busy || reason.trim().length < 10} onClick={() => void action(command)}>{command === "complete" ? "Acknowledge review" : command}</button>)}</div>
      <div className="data-scroll"><table><thead><tr><th>Step</th><th>Event</th><th>Recorded at</th></tr></thead><tbody>{run.events.map(event => <tr key={event.event_id}><td>{event.node}</td><td>{event.state ?? event.command}</td><td>{new Date(event.created_at).toLocaleString()}</td></tr>)}</tbody></table></div>
      {run.execution?.result.assessment_id && <p>Saved output: {run.execution.result.assessment_id}</p>}
    </>}
  </section>;
}
