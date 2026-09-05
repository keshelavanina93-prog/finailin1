"use client";
import { useEffect, useRef, useState, type FormEvent } from "react";

type Resolution = { canonical_id: string; version_id: string; display_name: string; resolution_chain: string[]; valid_at: string; known_at: string; authority_state: string };

export default function IdentityHistory({ resourceId, token }: { resourceId: string; token: string }) {
  const [result, setResult] = useState<Resolution | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const active = useRef(true);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  async function resolve(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(""); setResult(null);
    const data = new FormData(event.currentTarget);
    try {
      const query = new URLSearchParams({ valid_at: new Date(String(data.get("valid"))).toISOString(), known_at: new Date(String(data.get("known"))).toISOString() });
      const response = await fetch(`/api/ontology/resolve/${resourceId}?${query}`, { cache: "no-store", headers: { Authorization: `Bearer ${token}` } });
      const value = await response.json();
      if (!response.ok) throw new Error(value.detail ?? "Historical resolution unavailable");
      if (active.current) setResult(value);
    } catch (failure) { if (active.current) setError(failure instanceof Error ? failure.message : "Historical resolution failed"); }
    finally { if (active.current) setBusy(false); }
  }
  return <details><summary>Resolve identity at a historical point</summary>
    <p>Separate when an identity applied in the business from when G8 knew about it. Dates use your local time zone.</p>
    <form onSubmit={resolve} className="resource-form"><label>Business date and time<input type="datetime-local" name="valid" required /></label>
      <label>Known to G8 by<input type="datetime-local" name="known" required /></label><button disabled={busy}>{busy ? "Resolving…" : "Reconstruct identity"}</button></form>
    {error && <p role="alert" className="warning">{error}</p>}
    {result && <div role="status"><h3>{result.display_name}</h3><p>{result.authority_state} · {result.resolution_chain.length - 1} identity redirects</p><p>Effective at {new Date(result.valid_at).toLocaleString()} · known by {new Date(result.known_at).toLocaleString()}</p><code className="full-hash">{result.canonical_id}<br />Version {result.version_id}</code><details><summary>Resolution path</summary><ol>{result.resolution_chain.map(id => <li key={id}>{id}</li>)}</ol></details></div>}
  </details>;
}
