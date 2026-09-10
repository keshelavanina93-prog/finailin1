"use client";

import { useEffect, useState } from "react";
import type {
  ExecutableFinding,
  ExecutableFunction,
  ExecutableFunctionRegistry,
  ExecutablePreflightResponse,
} from "@finai/contracts";

function FindingTree({ findings }: { findings: ExecutableFinding[] }) {
  return <ul>{findings.map(finding => <li key={finding.requirement_id}><strong>{finding.requirement_id}</strong> · <span data-preflight-state={finding.state}>{finding.state}</span><p>{finding.message}</p>{finding.children.length > 0 && <FindingTree findings={finding.children} />}</li>)}</ul>;
}

export default function ExecutableModelPanel({ token }: { token: string }) {
  const [functions, setFunctions] = useState<ExecutableFunction[]>([]);
  const [selected, setSelected] = useState("");
  const [result, setResult] = useState<ExecutablePreflightResponse | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    void fetch("/api/workspace/executable-functions", { headers: { Authorization: `Bearer ${token}` }, cache: "no-store", signal: controller.signal })
      .then(async response => { const data = await response.json() as ExecutableFunctionRegistry & { detail?: string }; if (!response.ok) throw new Error(data.detail ?? "Executable function registry unavailable"); return data; })
      .then(data => { setFunctions(data.functions); setSelected(current => current || data.functions[0]?.function_id || ""); })
      .catch(cause => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Executable function registry unavailable"); });
    return () => controller.abort();
  }, [token]);

  async function preflight() {
    if (!selected) return;
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/workspace/executable-preflight", { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ function_id: selected, available: [] }), cache: "no-store" });
      const data = await response.json() as ExecutablePreflightResponse & { detail?: string };
      if (!response.ok) throw new Error(data.detail ?? "Executable preflight unavailable");
      setResult(data);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Executable preflight unavailable"); }
    finally { setBusy(false); }
  }

  const selectedFunction = functions.find(item => item.function_id === selected);
  return <section className="g8-panel" aria-label="Executable enterprise model">
    <div className="g8-panel-heading"><div><p className="overline">EXECUTABLE ENTERPRISE MODEL · READ-ONLY PREFLIGHT</p><h2>What is required?</h2><p>Registered domain verbs expose their dependency contract before calculation. Missing evidence is shown as a block; no fact, ledger or business action is changed.</p></div><span className="g8-badge">NO AUTHORITY EFFECT</span></div>
    {error && <p className="g8-inline-error" role="alert">{error}</p>}
    <div className="g8-actionbar"><label>Executable function<select value={selected} onChange={event => { setSelected(event.target.value); setResult(null); }}><option value="">Select function</option>{functions.map(item => <option key={`${item.function_id}@${item.version}`} value={item.function_id}>{item.function_id} · {item.domain}</option>)}</select></label><button onClick={() => void preflight()} disabled={busy || !selected}>{busy ? "Checking…" : "Run preflight"}</button></div>
    {selectedFunction && <p>Version {selectedFunction.version} · required authority {selectedFunction.required_authority ?? "not specified"} · deterministic {String(selectedFunction.deterministic)}</p>}
    {result && <section aria-label="Executable preflight result"><h3>{result.function.function_id} · {result.preflight.state}</h3><p>Registry: {result.registry_state}. Accounting and business-effect authority: none.</p><FindingTree findings={result.preflight.findings} /></section>}
  </section>;
}
