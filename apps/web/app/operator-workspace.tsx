"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import type { IngestReceipt, IntakeItem, ObjectDetail, Principal, ReceiptDetail, WorkspaceObject, WorkspaceSummary } from "@finai/contracts";
import EvidenceIntake from "./evidence-intake";
import ReceiptPanel from "./receipt-panel";
import ObjectPanel from "./object-panel";
import OntologyWorkspace from "./ontology-workspace";

async function decodeError(response: Response): Promise<string> {
  const data = await response.json().catch(() => null);
  if (typeof data?.detail === "string") return data.detail;
  if (Array.isArray(data?.detail)) return data.detail.map((item: { msg: string }) => item.msg).join("; ");
  return `Workspace request failed (${response.status})`;
}

export default function OperatorWorkspace() {
  const [token, setToken] = useState("");
  const [principal, setPrincipal] = useState<Principal | null>(null);
  const [view, setView] = useState<"intake" | "objects" | "history" | "ontology">("intake");
  const [summary, setSummary] = useState<WorkspaceSummary | null>(null);
  const [intake, setIntake] = useState<IntakeItem[]>([]);
  const [objects, setObjects] = useState<WorkspaceObject[]>([]);
  const [detail, setDetail] = useState<ReceiptDetail | null>(null);
  const [inspector, setInspector] = useState<ObjectDetail | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const [offset, setOffset] = useState(0);
  const [filter, setFilter] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [version, setVersion] = useState("");
  const generation = useRef(0);
  const selection = useRef(0);
  const api = useCallback(async <T,>(path: string, options?: RequestInit): Promise<T> => {
    const active = generation.current;
    const response = await fetch(`/api/workspace/${path}`, { ...options,
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, cache: "no-store" });
    if (!response.ok) throw new Error(await decodeError(response));
    const data = await response.json();
    if (active !== generation.current) throw new Error("Workspace session changed");
    return data as T;
  }, [token]);

  useEffect(() => {
    if (!principal || view === "ontology") return;
    let cancelled = false;
    const query = new URLSearchParams({ offset: String(offset) });
    if (view === "objects") {
      if (filter) query.set("object_type", filter);
      if (search) query.set("search", search);
      if (version) query.set("receipt_id", version);
    } else if (view === "intake") query.set("state", "PENDING");
    else if (filter) query.set("state", filter);
    const load = async () => {
      setLoading(true); setError("");
      try {
        const [counts, data] = await Promise.all([
          api<WorkspaceSummary>("summary"),
          api<IntakeItem[] | WorkspaceObject[]>(`${view === "objects" ? "objects" : "intake"}?${query}`),
        ]);
        if (!cancelled) {
          setSummary(counts);
          if (view === "objects") setObjects(data as WorkspaceObject[]);
          else setIntake(data as IntakeItem[]);
        }
      } catch (failure) { if (!cancelled) setError(String(failure instanceof Error ? failure.message : failure)); }
      finally { if (!cancelled) setLoading(false); }
    };
    void load();
    return () => { cancelled = true; };
  }, [api, principal, view, filter, search, version, offset, revision]);

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const key = String(new FormData(event.currentTarget).get("token") ?? "").trim();
    try {
      const response = await fetch("/api/workspace/session", { headers: { Authorization: `Bearer ${key}` }, cache: "no-store" });
      if (!response.ok) throw new Error(await decodeError(response));
      const identity: Principal = await response.json();
      generation.current++; setToken(key); setPrincipal(identity); setNotice("");
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Sign-in failed"); }
    finally { setBusy(false); }
  }

  function signOut() {
    generation.current++; selection.current++; setToken(""); setPrincipal(null); setDetail(null);
    setInspector(null); setSummary(null); setIntake([]); setObjects([]); setError(""); setNotice("");
    setOffset(0); setFilter(""); setSearch(""); setSearchInput(""); setVersion(""); setView("intake");
  }

  function navigate(next: typeof view) {
    selection.current++; setView(next); setOffset(0); setFilter(""); setSearch(""); setSearchInput("");
    setVersion(""); setDetail(null); setInspector(null); setError(""); setNotice("");
  }

  async function openConstruction(receiptId: string) {
    const request = ++selection.current;
    setBusy(true); setError(""); setInspector(null);
    try { const result = await api<ReceiptDetail>(`constructions/${receiptId}`); if (request === selection.current) setDetail(result); }
    catch (failure) { if (request === selection.current) setError(failure instanceof Error ? failure.message : "Could not load construction"); }
    finally { setBusy(false); }
  }

  async function decide(decision: "APPROVED" | "REJECTED", reason: string, key: string) {
    if (!detail) return;
    setBusy(true); setError("");
    try {
      await api(`constructions/${detail.receipt.receipt_id}/decision`, { method: "POST",
        body: JSON.stringify({ decision, reason, idempotency_key: key, expected_head: detail.current_head }),
      });
      setNotice(decision === "APPROVED" ? "Construction approved. Its object version is available." : "Rejection recorded. Original evidence is preserved.");
      setRevision(value => value + 1); await openConstruction(detail.receipt.receipt_id);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Review could not be saved"); }
    finally { setBusy(false); }
  }

  async function inspect(objectId: string) {
    const request = ++selection.current;
    setBusy(true); setError("");
    try { const result = await api<ObjectDetail>(`objects/${encodeURIComponent(objectId)}`); if (request === selection.current) setInspector(result); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "Could not load object"); }
    finally { setBusy(false); }
  }

  async function download(format: "source" | "export") {
    if (!detail) return;
    const active = generation.current;
    setError("");
    try {
      const response = await fetch(`/api/workspace/constructions/${detail.receipt.receipt_id}/${format}`, { headers: { Authorization: `Bearer ${token}` } });
      if (!response.ok) throw new Error(await decodeError(response));
      const blob = await response.blob();
      const expectedHash = format === "source" ? detail.receipt.source_sha256 : response.headers.get("X-Content-SHA256");
      const digest = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
      const actualHash = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
      if (!expectedHash || actualHash !== expectedHash) throw new Error("Evidence integrity could not be verified. Download was withheld.");
      if (active !== generation.current) return;
      const link = document.createElement("a"); const url = URL.createObjectURL(blob);
      link.href = url; link.download = format === "source" ? "retained-source.csv" : "g8-evidence-bundle.json";
      link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice("Evidence download verified against its retained hash.");
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Export failed"); }
  }

  if (!principal) return <main className="login-shell"><div className="login-story"><div className="wordmark">G8<span>by NYXCore</span></div>
    <p className="overline">EVIDENCE-NATIVE ENTERPRISE WORKSPACE</p><h1>From source evidence<br />to reviewed enterprise state.</h1>
    <p>Retain the original. Understand the source. Review what it can establish. Work with accepted objects and their evidence.</p>
    <ol><li>Evidence & construction</li><li>Independent review</li><li>Versioned objects & lineage</li></ol></div>
    <form className="login-card" onSubmit={signIn}><p className="overline">WORKSPACE ACCESS</p><h2>Open your workspace</h2>
      <p>Your identity determines the entity, period, currency and available actions.</p>
      <label>Workspace access key<input type="password" name="token" autoComplete="off" required autoFocus /></label>
      <button disabled={busy}>{busy ? "Connecting…" : "Continue"}</button>{error && <p role="alert" className="error-banner">{error}</p>}
      <small>Keys stay in memory for this session. Use a separate reviewer identity for approval.</small></form></main>;

  const pageSize = view === "objects" ? 100 : 50;
  const count = view === "objects" ? objects.length : intake.length;
  return <main className="operator-shell">
    <aside className="navigation"><div className="wordmark">G8<span>by NYXCore</span></div><p className="nav-caption">ENTERPRISE WORKSPACE</p>
      {([ ["intake", "Evidence intake", "01"], ["objects", "Object workspace", "02"], ["history", "Construction history", "03"], ["ontology", "Enterprise & ontology", "04"] ] as const).map(([id, label, number]) => <button key={id} className={view === id ? "nav-link active" : "nav-link"} onClick={() => navigate(id)}><small>{number}</small>{label}</button>)}
      <div className="identity-card"><strong>{principal.display_name}</strong><small>{principal.permissions.join(" · ")}</small><button className="quiet" onClick={signOut}>Switch identity / sign out</button></div></aside>
    <div className="operator-main">
      <div className="operator-content">{view === "ontology" ? <OntologyWorkspace token={token} principal={principal} /> : <><div className="section-heading"><div><p className="overline">SOURCE → CONSTRUCTION → REVIEW → OBJECTS</p><h1>{view === "intake" ? "Evidence intake" : view === "objects" ? "Object workspace" : "Construction history"}</h1><p className="muted">{view === "objects" ? "Inspect accepted objects and follow every value back to source evidence." : "Review source construction without losing the evidence or earlier versions."}</p></div><button className="quiet" disabled={loading || busy} onClick={() => { setRevision(value => value + 1); if (detail) void openConstruction(detail.receipt.receipt_id); }}>Refresh</button></div>
        <div className="summary-grid"><article><span>Pending review</span><strong>{summary?.pending_count ?? "—"}</strong></article><article><span>Accepted constructions</span><strong>{summary?.approved_count ?? "—"}</strong></article><article><span>Rejected constructions</span><strong>{summary?.rejected_count ?? "—"}</strong></article><article><span>Current source versions</span><strong>{summary?.active_versions.length ?? "—"}</strong></article></div>
        {error && <div role="alert" className="error-banner">{error}</div>}{notice && <div role="status" className="success-banner">{notice}</div>}
        {view === "intake" && principal.permissions.includes("ingest") && <EvidenceIntake key={token} token={token} principal={principal} onRetained={async (receipt: IngestReceipt) => { setOffset(0); setRevision(value => value + 1); setNotice("Evidence retained with its reviewed identity selections."); await openConstruction(receipt.receipt_id); }} />}
        {!detail && <section className="data-panel"><div className="toolbar"><h2>{view === "objects" ? (version ? "Pinned construction version" : "Current accepted versions") : view === "intake" ? "Review queue" : "All constructions"}</h2>
          {view !== "intake" && <label className="compact-label">{view === "objects" ? "Object type" : "Decision"}<select value={filter} onChange={event => { setFilter(event.target.value); setOffset(0); }}>{(view === "objects" ? ["", "Account", "PeriodBalance", "SourceRecord"] : ["", "PENDING", "APPROVED", "REJECTED"]).map(value => <option key={value} value={value}>{value || "All"}</option>)}</select></label>}
          {view === "objects" && <form className="search-form" onSubmit={event => { event.preventDefault(); setSearch(searchInput); setOffset(0); }}><input aria-label="Search object values" value={searchInput} onChange={event => setSearchInput(event.target.value)} placeholder="Find an account or source value" maxLength={128} /><button className="quiet">Search</button></form>}
          {version && <button className="quiet" onClick={() => { setVersion(""); setOffset(0); }}>Return to current</button>}</div>
          {loading ? <div className="empty-state" role="status">Loading scoped workspace…</div> : count === 0 ? <div className="empty-state"><h3>{view === "objects" ? "No accepted objects in this view" : "No constructions in this view"}</h3><p>{view === "objects" ? "Approve an eligible construction with a separate reviewer to create an object version." : "Upload evidence or change the history filter to continue."}</p></div> : <div className="data-scroll"><table>{view === "objects" ? <><thead><tr><th>Object</th><th>Type</th><th>Evidence state</th><th>Values</th><th>Source</th></tr></thead><tbody>{objects.map(object => <tr key={object.object_id}><td><button className="text-link" onClick={() => void inspect(object.object_id)}>{object.values.account_code ?? `Record ${object.source_row}`}</button></td><td>{object.object_type}</td><td><span className="status observed">{object.epistemic_state}</span></td><td className="values">{Object.entries(object.values).filter(([key]) => key !== "account_code").map(([key, value]) => <span key={key}><small>{key}</small> {value}</span>)}</td><td>Row {object.source_row}</td></tr>)}</tbody></> : <><thead><tr><th>Source evidence</th><th>Class</th><th>Proposed objects</th><th>Validation</th><th>Decision</th><th>Received</th></tr></thead><tbody>{intake.map(item => <tr key={item.receipt_id}><td><button className="text-link" onClick={() => void openConstruction(item.receipt_id)}>{item.filename}</button><small className="hash-caption">{item.source_sha256.slice(0, 14)}…</small></td><td>{item.source_class.replaceAll("_", " ")}</td><td>{item.candidate_count}</td><td>{item.reject_count ? `${item.reject_count} rejected rows` : item.reconciliation_status}</td><td><span className={`status ${item.review_state.toLowerCase()}`}>{item.review_state}</span>{item.is_current && <small className="hash-caption">Current version</small>}</td><td>{new Date(item.ingested_at).toLocaleString()}</td></tr>)}</tbody></>}</table></div>}
          <div className="pagination"><button className="quiet" disabled={loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - pageSize))}>Previous</button><span>Page {Math.floor(offset / pageSize) + 1}</span><button className="quiet" disabled={loading || count < pageSize} onClick={() => setOffset(offset + pageSize)}>Next</button></div></section>}
        {detail && <ReceiptPanel key={detail.receipt.receipt_id} detail={detail} principal={principal} busy={busy} onDecision={decide} onExport={format => void download(format)} onClose={() => { selection.current++; setDetail(null); }} onObjects={() => { const id = detail.receipt.receipt_id; navigate("objects"); setVersion(id); }} />}
        {inspector && <ObjectPanel detail={inspector} onClose={() => { selection.current++; setInspector(null); }} />}
        </>}<footer className="workspace-footer"><span>Scope: {principal.scope.tenant_id}</span><span>Accepted construction ≠ certified financial truth</span></footer>
      </div></div>
  </main>;
}
