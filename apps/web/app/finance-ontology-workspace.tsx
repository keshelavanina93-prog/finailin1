"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import type { Principal } from "@finai/contracts";
import styles from "./finance-ontology-workspace.module.css";

type Pin = { resource_id: string; version_id: string };
type Catalog = { catalog_id: string; catalog_sha256: string; definitions: Array<{ object_type: string; status: string; display_name: string; version_id: string | null }>; phases: Array<{ kind: string; pending: number }>; ready: boolean; company_facts_published: false };
type Construction = { construction_id: string; status: string; authority: string; row_count: number; candidate_file_sha256: string; construction_content_sha256: string; source_sha256: string | null; rows: unknown[] };
type TBSource = { receipt_id: string; filename: string | null; source_sha256: string; observed_period: string | null; working_period: string | null; source_use: string; rejects: string[]; warnings: string[]; submitted_by: string | null; ingested_at: string | null };
type TBSourceSnapshot = { snapshot_id: string; receipt_id: string | null; filename: string; source_sha256: string; observed_period: string; period_start: string; period_end: string; working_period: string | null; findings: string[]; construction_state: string; evidence_class: string };
type TBPulse = Record<string, string | number | null> & { period?: string; ar_end?: string; ap_end?: string; continuity_status?: string };
type TBDraft = { run_id?: string; function: string; profile: string; certification: string; source_snapshots: TBSourceSnapshot[]; source_receipts: Array<Record<string, unknown>>; year_pulse: TBPulse[]; review?: { snapshot_state?: string; year_package_state?: string; accounting_use_authorized?: boolean; business_effect_authorized?: boolean; currency_status?: string; certification?: string; petroleum_actuals?: string }; exceptions?: { continuity_breaks?: unknown[]; unsupported?: string[] }; };

function pin(id: string, version: string): Pin | null {
  return id.trim() && version.trim() ? { resource_id: id.trim(), version_id: version.trim() } : null;
}
function now() { return new Date().toISOString(); }

async function call<T>(route: string, token: string, method = "GET", payload?: unknown): Promise<T> {
  const response = await fetch(`/api/ontology/finance/${route}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: payload === undefined ? undefined : JSON.stringify(payload),
    cache: "no-store",
  });
  const value = await response.json() as { detail?: string } & T;
  if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : `Finance request failed (${response.status})`);
  return value;
}

export default function FinanceOntologyWorkspace({ token, principal, onProposal }: { token: string; principal: Principal; onProposal: (id: string) => void }) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [constructions, setConstructions] = useState<Construction[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [candidate, setCandidate] = useState<Record<string, string>>({ construction_id: "g8.candidate.coa-406", document_id: "", evidence_id: "", evidence_version: "", company_id: "", company_version: "", chart_id: "", chart_version: "", offset: "0", limit: "25", valid_from: now(), rationale: "Retain this observed construction for independent review." });
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [execution, setExecution] = useState<Record<string, unknown> | null>(null);
  const [run, setRun] = useState({ operation: "trial_balance", contract_id: "", contract_version: "", object_type: "JournalLine", as_of: "2026-08-31", starts_on: "2026-08-01" });
  const [classification, setClassification] = useState({ policy_id: "", policy_version: "", document_id: "", offset: "0", limit: "25" });
  const [tbSources, setTBSources] = useState<TBSource[]>([]);
  const [tbSelected, setTBSelected] = useState<string[]>([]);
  const [tbDraft, setTBDraft] = useState<TBDraft | null>(null);
  const [tbBusy, setTBBusy] = useState(false);
  const [tbLoading, setTBLoading] = useState(true);
  const [tbError, setTBError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function refresh() {
      setBusy(true); setError("");
      setTBLoading(true); setTBError("");
      const [catalogResult, constructionsResult, tbResult] = await Promise.allSettled([
        call<Catalog>("catalog", token), call<Construction[]>("constructions", token), call<TBSource[]>("tb/sources", token),
      ]);
      if (cancelled) return;
      if (catalogResult.status === "fulfilled") setCatalog(catalogResult.value);
      else setError(catalogResult.reason instanceof Error ? catalogResult.reason.message : "Finance catalog unavailable");
      if (constructionsResult.status === "fulfilled") setConstructions(constructionsResult.value);
      else setError(constructionsResult.reason instanceof Error ? constructionsResult.reason.message : "Finance constructions unavailable");
      if (tbResult.status === "fulfilled") {
        setTBSources(tbResult.value);
        setTBSelected(current => current.filter(id => tbResult.value.some(source => source.receipt_id === id)));
      } else setTBError(tbResult.reason instanceof Error ? tbResult.reason.message : "TB Finance sources unavailable");
      setTBLoading(false); setBusy(false);
    }
    void refresh();
    return () => { cancelled = true; };
  }, [token]);

  const firstPending = useMemo(() => catalog?.phases.find(item => item.pending > 0)?.kind ?? "", [catalog]);
  const canPropose = principal.permissions.includes("ontology_propose") && principal.permissions.includes("ontology_admin");
  const canRead = principal.permissions.includes("ontology_read");
  function update(setter: typeof setCandidate, key: string, value: string) { setter(previous => ({ ...previous, [key]: value })); }

  async function proposeCatalog(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!catalog) return; setBusy(true); setError(""); setNotice("");
    const form = new FormData(event.currentTarget); const phase = String(form.get("phase") ?? firstPending);
    try { const value = await call<{ proposal: { proposal_id: string } }>("catalog/proposals", token, "POST", { catalog_sha256: catalog.catalog_sha256, phase, offset: 0, limit: 40, valid_from: String(form.get("valid_from")), rationale: String(form.get("rationale")), request_id: crypto.randomUUID() }); setNotice("Catalog proposal retained. An independent reviewer must decide it."); onProposal(value.proposal.proposal_id); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "Catalog proposal failed"); }
    finally { setBusy(false); }
  }
  function candidatePayload() {
    const evidence = pin(candidate.evidence_id, candidate.evidence_version); const company = pin(candidate.company_id, candidate.company_version); const chart = pin(candidate.chart_id, candidate.chart_version);
    return { construction_id: candidate.construction_id, document_id: candidate.document_id || null, evidence, company, chart, valid_from: new Date(candidate.valid_from).toISOString(), offset: Number(candidate.offset), limit: Number(candidate.limit), rationale: candidate.rationale };
  }
  async function previewCandidate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(""); setNotice("");
    try { setPreview(await call<Record<string, unknown>>("candidates/preview", token, "POST", candidatePayload())); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "Candidate preview failed"); }
    finally { setBusy(false); }
  }
  async function submitCandidate() {
    setBusy(true); setError("");
    try { const value = await call<{ proposal: { proposal_id: string } }>("candidates/proposals", token, "POST", candidatePayload()); setNotice("Candidate proposal retained. No company fact was promoted."); onProposal(value.proposal.proposal_id); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "Candidate proposal failed"); }
    finally { setBusy(false); }
  }
  async function execute(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const valid = new Date().toISOString(); const value = await call<Record<string, unknown>>("execute", token, "POST", { operation: run.operation, contract: pin(run.contract_id, run.contract_version), query: { object_type: run.object_type, resource_ids: null, search: "", filters: [], traversal: [], offset: 0, limit: 200, valid_at: valid, known_at: valid }, starts_on: run.starts_on, as_of: run.as_of, group_by: ["account_id"] }); setExecution(value);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Finance execution failed"); }
    finally { setBusy(false); }
  }
  async function classify(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    try { const value = await call<Record<string, unknown>>("classify", token, "POST", { policy: pin(classification.policy_id, classification.policy_version), document_id: classification.document_id, offset: Number(classification.offset), limit: Number(classification.limit) }); setExecution(value); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "Classification failed"); }
    finally { setBusy(false); }
  }

  function toggleTBReceipt(receiptId: string) {
    setTBSelected(current => current.includes(receiptId) ? current.filter(id => id !== receiptId) : [...current, receiptId]);
    setTBDraft(null); setTBError("");
  }
  async function produceTBDraft() {
    if (!tbSelected.length) { setTBError("Select at least one retained TB source"); return; }
    setTBBusy(true); setTBError("");
    try { setTBDraft(await call<TBDraft>("tb/draft", token, "POST", { receipt_ids: tbSelected })); }
    catch (failure) { setTBError(failure instanceof Error ? failure.message : "TB Finance draft unavailable"); }
    finally { setTBBusy(false); }
  }
  async function exportTBDraft() {
    if (!tbDraft?.run_id) { setTBError("Generate and retain a TB draft before exporting"); return; }
    setTBBusy(true); setTBError("");
    try {
      const response = await fetch("/api/ontology/finance/tb/export", { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ run_id: tbDraft.run_id }), cache: "no-store" });
      if (!response.ok) {
        const value = await response.json().catch(() => null) as { detail?: string } | null;
        throw new Error(typeof value?.detail === "string" ? value.detail : `TB export failed (${response.status})`);
      }
      const certification = response.headers.get("X-FinAI-Certification");
      if (certification && certification !== "NOT_CERTIFIED") throw new Error("TB export returned an unexpected certification state");
      const blob = await response.blob(); const url = URL.createObjectURL(blob); const link = document.createElement("a");
      link.href = url; link.download = "TB_Finance_Draft.zip"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (failure) { setTBError(failure instanceof Error ? failure.message : "TB export unavailable"); }
    finally { setTBBusy(false); }
  }
  function displayPeriod(value: string | null | undefined): string { return value && value.trim() ? value : "Not recorded"; }
  function displayTimestamp(value: string | null | undefined): string { return value ? new Date(value).toLocaleString() : "Not recorded"; }
  function displayPulseValue(value: unknown): string { return value === null || value === undefined || value === "" ? "—" : String(value); }

  if (!canRead) return <section className="g8-panel"><h2>Finance ontology</h2><p>Your identity does not include ontology read access.</p></section>;
  return <section className={styles.shell} aria-label="Finance ontology workspace">
    <div className={styles.intro}><div><p className={styles.eyebrow}>VERSIONED FINANCE DOMAIN</p><h2>Finance ontology runtime</h2><p className={styles.muted}>Publish reusable objects, links, interfaces, sets, derived properties and reviewed policies. Company constructions stay candidate until a separate review decision.</p></div><div className={styles.status}><span>Catalog status</span><strong>{catalog ? (catalog.ready ? "Ready" : "Publication required") : busy ? "Loading…" : "Unavailable"}</strong><small>{catalog?.company_facts_published === false ? "Company facts: 0 published by catalog" : ""}</small></div></div>
    {error && <p className={styles.error} role="alert">{error}</p>}{notice && <p className={styles.notice} role="status">{notice}</p>}
    <div className={styles.grid}>
      <section className={`${styles.card} ${styles.wide}`} aria-label="TB Finance draft">
        <div className={styles.cardHeading}><div><p className={styles.eyebrow}>ACCOUNT_PERIOD · SOURCE BOUND</p><h3>1C trial balance finance draft</h3><p>Choose retained trial-balance receipts to produce a source-linked draft. Accounting periods come from each file’s internal header; ingestion time and working scope remain audit metadata.</p></div><span className={styles.badge}>SOURCE HEADER ONLY</span></div>
        <div className={styles.authority}><strong>Period authority</strong><span>Internal source header</span><small>Current date, session date and ingestion timestamp never set or rewrite the ledger period. A mismatch is retained as an explicit finding.</small></div>
        {tbError && <p className={styles.error} role="alert">{tbError}</p>}
        {tbLoading ? <p role="status" className={styles.muted}>Loading retained trial-balance sources…</p> : !tbSources.length ? <p className={styles.muted}>No retained trial-balance sources are available in this exact scope.</p> : <>
          <div className={styles.table}><table><caption>Retained trial-balance sources</caption><thead><tr><th>Select</th><th>Source</th><th>Observed period</th><th>Working scope</th><th>Ingested</th><th>Findings</th></tr></thead><tbody>{tbSources.map(source => <tr key={source.receipt_id}><td><input type="checkbox" aria-label={`Select ${source.filename ?? source.receipt_id}`} checked={tbSelected.includes(source.receipt_id)} onChange={() => toggleTBReceipt(source.receipt_id)} /></td><td><strong>{source.filename ?? source.receipt_id}</strong><div className={styles.hash}>{source.source_use} · {source.source_sha256.slice(0, 16)}…</div></td><td><span className={styles.observed}>{displayPeriod(source.observed_period)}</span></td><td>{displayPeriod(source.working_period)}<div className={styles.hash}>finding context only</div></td><td>{displayTimestamp(source.ingested_at)}</td><td>{source.rejects.length || source.warnings.length ? `${source.rejects.length + source.warnings.length} finding(s)` : "No retained findings"}</td></tr>)}</tbody></table></div>
          <div className={styles.row}><span className={styles.muted}>{tbSelected.length} receipt(s) selected</span><button className={styles.button} type="button" disabled={tbBusy || !tbSelected.length} onClick={() => void produceTBDraft()}>{tbBusy ? "Producing…" : "Generate retained draft"}</button>{tbDraft?.run_id && <button className={`${styles.button} ${styles.secondary}`} type="button" disabled={tbBusy} onClick={() => void exportTBDraft()}>Export draft ZIP</button>}</div>
        </>}
        {tbDraft && <div className={styles.draftResult}>
          <div className={styles.draftHeader}><div><strong>{tbDraft.function}</strong><small>{tbDraft.profile} · {tbDraft.run_id ?? "retained run unavailable"}</small></div><span className={styles.notCertified}>{tbDraft.certification}</span></div>
          <p className={styles.warning}>NOT_CERTIFIED · Company facts remain unpublished. Petroleum actuals are unimplemented. This draft does not create journals, invoices, aging, liters, tanks, trucks, product margin or GEL currency facts.</p>
          <div className={styles.table}><table aria-label="TB Finance Year Pulse"><caption>Year Pulse · {tbDraft.year_pulse.length} observed period(s)</caption><thead><tr><th>Period</th><th>Revenue</th><th>COGS</th><th>Gross margin</th><th>AR closing</th><th>AP closing</th><th>Boundary</th></tr></thead><tbody>{tbDraft.year_pulse.map((row, index) => <tr key={`${String(row.period ?? "period")}:${index}`}><td>{displayPulseValue(row.period)}</td><td>{displayPulseValue(row.revenue_month)}</td><td>{displayPulseValue(row.cogs_month)}</td><td>{displayPulseValue(row.gross_margin_month)}</td><td>{displayPulseValue(row.ar_end)}</td><td>{displayPulseValue(row.ap_end)}</td><td>{displayPulseValue(row.continuity_status)}</td></tr>)}</tbody></table></div>
          {tbDraft.source_snapshots.some(snapshot => snapshot.findings.length) && <details><summary>Period and source findings</summary>{tbDraft.source_snapshots.filter(snapshot => snapshot.findings.length).map(snapshot => <p key={snapshot.snapshot_id}>{snapshot.observed_period}: {snapshot.findings.join("; ")}</p>)}</details>}
        </div>}
      </section>
      <section className={styles.card}><h3>Catalog publication</h3><p>The catalog is platform definition authority. Submit one dependency phase at a time to the existing review queue.</p>{catalog && <><div className={styles.phaseList}>{catalog.phases.map(item => <div className={styles.phase} key={item.kind}><span>{item.kind}</span><b>{item.pending ? `${item.pending} pending` : "installed"}</b></div>)}</div><form className={styles.form} onSubmit={proposeCatalog}><label>Phase<select name="phase" defaultValue={firstPending}>{catalog.phases.map(item => <option key={item.kind} value={item.kind}>{item.kind} · {item.pending} pending</option>)}</select></label><label>Effective from<input name="valid_from" type="datetime-local" defaultValue={new Date().toISOString().slice(0, 16)} required /></label><label>Rationale<textarea name="rationale" minLength={10} defaultValue="Publish this reviewed platform ontology phase while preserving candidate company facts." required /></label><button disabled={!canPropose || busy || !firstPending}>{canPropose ? "Submit catalog phase for review" : "Admin publication access required"}</button></form></>}</section>
      <section className={styles.card}><h3>Candidate constructions</h3><p>Observed entities and the 406 account rows are retained with their source hashes. Exact company, chart and evidence pins are required before submission.</p><div className={styles.table}><table><thead><tr><th>Construction</th><th>Rows</th><th>Source hash</th></tr></thead><tbody>{constructions.map(item => <tr key={item.construction_id}><td>{item.construction_id}<div className={styles.hash}>{item.candidate_file_sha256}</div></td><td>{item.row_count}<div>{item.authority}</div></td><td className={styles.hash}>{item.source_sha256 ?? "not supplied"}</td></tr>)}</tbody></table></div></section>
      <section className={styles.card}><h3>Review a candidate page</h3><form className={styles.form} onSubmit={previewCandidate}><label>Construction<select value={candidate.construction_id} onChange={event => update(setCandidate, "construction_id", event.target.value)}><option>g8.candidate.coa-406</option><option>g8.candidate.seg-entities</option></select></label><label>Retained document ID<input value={candidate.document_id} onChange={event => update(setCandidate, "document_id", event.target.value)} placeholder="doc_… (exact retained source)" /></label><label>Evidence resource / version<input value={candidate.evidence_id} onChange={event => update(setCandidate, "evidence_id", event.target.value)} placeholder="resource UUID" /><input value={candidate.evidence_version} onChange={event => update(setCandidate, "evidence_version", event.target.value)} placeholder="version UUID" /></label><label>Company resource / version<input value={candidate.company_id} onChange={event => update(setCandidate, "company_id", event.target.value)} placeholder="LegalEntity resource UUID" /><input value={candidate.company_version} onChange={event => update(setCandidate, "company_version", event.target.value)} placeholder="version UUID" /></label><label>Chart resource / version<input value={candidate.chart_id} onChange={event => update(setCandidate, "chart_id", event.target.value)} placeholder="LocalChartOfAccounts resource UUID" /><input value={candidate.chart_version} onChange={event => update(setCandidate, "chart_version", event.target.value)} placeholder="version UUID" /></label><label>Effective from<input type="datetime-local" value={candidate.valid_from.slice(0, 16)} onChange={event => update(setCandidate, "valid_from", event.target.value)} required /></label><label>Page size<input type="number" min="1" max="25" value={candidate.limit} onChange={event => update(setCandidate, "limit", event.target.value)} /></label><label>Rationale<textarea minLength={10} value={candidate.rationale} onChange={event => update(setCandidate, "rationale", event.target.value)} required /></label><div className={styles.row}><button className={styles.button} disabled={busy}>Preview exact page</button>{preview && <button type="button" className={`${styles.button} ${styles.secondary}`} disabled={busy || preview.can_submit !== true} onClick={() => void submitCandidate()}>Submit pending proposal</button>}</div></form>{preview && <div className={styles.result}><pre>{JSON.stringify(preview, null, 2)}</pre></div>}</section>
      <section className={styles.card}><h3>Deterministic execution</h3><p>Execution requires an exact reviewed FactContract and exact time scope. Results are retained as immutable fact-run evidence.</p><form className={styles.form} onSubmit={execute}><label>Operation<select value={run.operation} onChange={event => setRun({ ...run, operation: event.target.value })}><option value="trial_balance">Trial balance turnover</option><option value="closing_as_of">Closing as of</option><option value="ytd_flow">YTD flow</option><option value="reconcile_parent">Parent reconciliation</option><option value="project">Reviewed projection</option></select></label><label>FactContract resource / version<input value={run.contract_id} onChange={event => setRun({ ...run, contract_id: event.target.value })} placeholder="resource UUID" /><input value={run.contract_version} onChange={event => setRun({ ...run, contract_version: event.target.value })} placeholder="version UUID" /></label><label>Fact object type<input value={run.object_type} onChange={event => setRun({ ...run, object_type: event.target.value })} /></label><div className={styles.row}><label>Starts<input type="date" value={run.starts_on} onChange={event => setRun({ ...run, starts_on: event.target.value })} /></label><label>As of<input type="date" value={run.as_of} onChange={event => setRun({ ...run, as_of: event.target.value })} /></label></div><button disabled={busy || !run.contract_id || !run.contract_version}>Run and retain exact calculation</button></form></section>
      <section className={styles.card}><h3>Rule based candidate classification</h3><p>Classification executes only an exact reviewed FinanceClassificationPolicy over a retained source. It never creates a canonical posting.</p><form className={styles.form} onSubmit={classify}><label>Policy resource / version<input value={classification.policy_id} onChange={event => setClassification({ ...classification, policy_id: event.target.value })} placeholder="resource UUID" /><input value={classification.policy_version} onChange={event => setClassification({ ...classification, policy_version: event.target.value })} placeholder="version UUID" /></label><label>Retained document ID<input value={classification.document_id} onChange={event => setClassification({ ...classification, document_id: event.target.value })} placeholder="doc_…" required /></label><button disabled={busy || !classification.policy_id || !classification.policy_version}>Classify as candidate evidence</button></form></section>
    </div>
    {execution && <section className={styles.card}><h3>Latest retained result</h3><div className={styles.result}><pre>{JSON.stringify(execution, null, 2)}</pre></div></section>}
  </section>;
}
