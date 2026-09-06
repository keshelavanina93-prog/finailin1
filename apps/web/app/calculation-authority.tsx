"use client";

import { useEffect, useState } from "react";

type Reference = { resource_id: string; version_id: string };
type Check = {
  subject: Reference;
  display_name: string;
  role: string;
  authority_state: string | null;
  availability_state: string | null;
  event_changed: boolean;
  blocker: string | null;
};
type Status = { run_id: string; status: string; checked_at: string; checks: Check[] };
const readable = (value: string) => value.toLowerCase().replaceAll("_", " ");
const reasons: Record<string, string> = {
  AUTHORITY_WITHDRAWN: "Authority was withdrawn",
  AVAILABILITY_WITHDRAWN: "Input availability was withdrawn",
  MINIMUM_AUTHORITY_NOT_MET: "Required authority is no longer met",
  VERSION_NOT_CURRENT_OR_ACCESSIBLE: "The version is no longer current or accessible",
};

export default function CalculationAuthority({ token, runId, onTrace }: {
  token: string;
  runId: string;
  onTrace?: (reference: Reference) => void;
}) {
  const [result, setResult] = useState<Status | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const response = await fetch(`/api/ontology/model/fact-runs/${runId}/authority`, {
          headers: { Authorization: `Bearer ${token}` }, cache: "no-store", signal: controller.signal,
        });
        const data = await response.json();
        if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Authority status is unavailable");
        if (!controller.signal.aborted) { setResult(data); setError(""); }
      } catch (failure) {
        if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "Authority status is unavailable");
      }
    }
    void load();
    return () => controller.abort();
  }, [token, runId, revision]);
  return <section className="g8-promotion" aria-label="Current calculation input authority">
    <h3>Can these inputs still be used?</h3>
    {error ? <p role="alert">{error}</p> : !result ? <p role="status">Checking current input authority…</p> : <>
      <p role="status">{result.status === "BLOCKED"
        ? "Current use is blocked. Inspect the affected inputs before calculating again."
        : "No current blocker was found. Execute the calculation again to obtain a new authority check."}</p>
      <p>The retained result remains historical evidence. This inspection grants no new authority.</p>
      <div className="g8-table-scroll"><table>
        <thead><tr><th>Resource</th><th>Authority / availability</th><th>Change since calculation</th><th>Evidence</th></tr></thead>
        <tbody>{result.checks.map(check => <tr key={check.subject.version_id}>
          <td>{check.display_name}<small> · {readable(check.role)}</small></td>
          <td>{check.authority_state ? readable(check.authority_state) : "Not established"} / {check.availability_state ? readable(check.availability_state) : "Not established"}</td>
          <td>{check.blocker ? reasons[check.blocker] ?? readable(check.blocker) : check.event_changed ? "Lifecycle record changed" : "No recorded change"}</td>
          <td>{onTrace && <button className="g8-link" onClick={() => onTrace(check.subject)}>Trace evidence</button>}</td>
        </tr>)}</tbody>
      </table></div>
      <small>Inspected {new Date(result.checked_at).toLocaleString()}</small>
    </>}
    <button className="g8-link" disabled={!result && !error} onClick={() => { setResult(null); setError(""); setRevision(value => value + 1); }}>Refresh input status</button>
  </section>;
}
