"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import type { IngestReceipt, Principal } from "@finai/contracts";
import ReportInputs from "./report-inputs";

type Account = { resource_id: string; version_id: string; display_name: string; account_code: string };
type Prepared = { filename: string; csv_text?: string; xls_base64?: string; xlsx_base64?: string; context_version_id: string | null; codes: string[]; accounts: Account[]; observations: Record<string, string>; rejects: string[]; warnings: string[] };

export default function EvidenceIntake({ token, principal, onRetained }: {
  token: string; principal: Principal; onRetained: (receipt: IngestReceipt) => Promise<void>;
}) {
  const [prepared, setPrepared] = useState<Prepared | null>(null);
  const [bindings, setBindings] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sourceOnly, setSourceOnly] = useState(false);
  const [sourceUse, setSourceUse] = useState("ACTUAL_INPUT");
  const [page, setPage] = useState(0);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const fileForm = useRef<HTMLFormElement>(null);

  async function request<T>(url: string, body?: unknown): Promise<T> {
    const response = await fetch(url, { method: body ? "POST" : "GET", cache: "no-store",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      ...(body ? { body: JSON.stringify(body) } : {}) });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${response.status})`);
    return data as T;
  }

  async function prepare(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(""); setPrepared(null);
    try {
      const file = new FormData(event.currentTarget).get("source") as File;
      const isXls = file.name.toLowerCase().endsWith(".xls");
      const isXlsx = file.name.toLowerCase().endsWith(".xlsx");
      const isWorkbook = isXls || isXlsx;
      if (!file.size || file.size > (isXlsx ? 16_000_000 : isXls ? 4_000_000 : 1_000_000)) throw new Error("Choose a CSV up to 1 MB, XLS up to 4 MB or XLSX up to 16 MB.");
      const bytes = new Uint8Array(await file.arrayBuffer());
      let binary = "";
      if (isWorkbook) for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
      const payload = isXlsx ? { xlsx_base64: btoa(binary) } : isXls ? { xls_base64: btoa(binary) } : {
        csv_text: new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes),
      };
      const context = await request<{ binding: { version_id: string } | null }>("/api/ontology/context");
      const context_version_id = sourceOnly || isWorkbook || sourceUse !== "ACTUAL_INPUT" ? null : context.binding?.version_id ?? null;
      const source = await request<{ account_codes: string[]; source_class: string; observed_bindings: Record<string, string>; rejects: string[]; warnings: string[] }>("/api/ontology/context/source-accounts", {
        scope: principal.scope, filename: file.name, ...payload, context_version_id, source_use: sourceUse,
      });
      const accounts: Account[] = [];
      if (context_version_id && source.account_codes.length) {
        let more = true;
        for (let offset = 0; more; offset += 100) {
          if (offset >= 10000) throw new Error("This chart exceeds the intake selection limit. Narrow the governed chart before binding.");
          const page = await request<{ items: Account[]; has_more: boolean }>(`/api/ontology/context/accounts?context_version_id=${encodeURIComponent(context_version_id)}&offset=${offset}`);
          accounts.push(...page.items); more = page.has_more;
        }
      }
      const selected: Record<string, string> = {};
      for (const code of source.account_codes) {
        const matches = accounts.filter(account => account.account_code === code);
        if (matches.length === 1) selected[code] = matches[0].version_id;
      }
      if (!alive.current) return;
      setPage(0); setBindings(selected);
      setPrepared({ filename: file.name, ...payload, context_version_id, codes: source.account_codes, accounts,
        observations: source.observed_bindings, rejects: source.rejects, warnings: source.warnings });
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Source preparation failed"); }
    finally { setBusy(false); }
  }

  async function retain() {
    if (!prepared) return;
    setBusy(true); setError("");
    try {
      const receipt = await request<IngestReceipt>("/api/hydration", {
        scope: principal.scope, filename: prepared.filename, csv_text: prepared.csv_text,
        xls_base64: prepared.xls_base64,
        xlsx_base64: prepared.xlsx_base64, source_use: sourceUse,
        context_version_id: prepared.context_version_id,
        account_version_ids: prepared.context_version_id ? bindings : {},
      });
      if (!alive.current) return;
      setPrepared(null); fileForm.current?.reset(); await onRetained(receipt);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Evidence could not be retained"); }
    finally { setBusy(false); }
  }

  const needsBindings = !!prepared?.context_version_id && !!prepared.codes.length;
  return <><section className="data-panel intake-binding">
    <form ref={fileForm} className="upload-strip" onSubmit={prepare}>
      <div><h3>Add evidence</h3><p>{principal.scope.legal_entity_id} · {principal.scope.period} · {principal.scope.currency}</p>
        <p>CSV, XLS or XLSX · source context and reporting requirements stay separate.</p></div>
      <label>Source file<input type="file" accept=".csv,.xls,.xlsx" name="source" required disabled={busy} onChange={() => setPrepared(null)} /></label>
      <label>Intended use<select value={sourceUse} disabled={busy} onChange={event => { setSourceUse(event.target.value); setPrepared(null); }}><option value="ACTUAL_INPUT">Facts for selected period</option><option value="HISTORICAL_REFERENCE">Historical source example</option><option value="REPORT_TEMPLATE">Reporting requirement example</option><option value="MAPPING_REFERENCE">Mapping reference</option></select></label>
      <button disabled={busy}>{busy ? "Working…" : "Prepare intake"}</button>
      <label className="source-only-choice"><input type="checkbox" checked={sourceOnly} disabled={busy} onChange={event => { setSourceOnly(event.target.checked); setPrepared(null); }} /> Retain as source evidence without canonical binding</label>
    </form>
    {error && <p role="alert" className="error-banner">{error}</p>}
    {prepared && <div className="binding-review"><h3>{prepared.filename}</h3>
      {prepared.xls_base64 && <p className="warning">This XLS is retained as source observations. Company, currency and repeated account rows require review before financial use. It cannot create journal entries or certified reports.</p>}
      {prepared.xls_base64 && <p>Source company: {prepared.observations.company_label} · Source month: {prepared.observations.period}</p>}
      {prepared.xlsx_base64 && <p>Observed company: {prepared.observations.company_label} · Observed period: {prepared.observations.period}. Formula dependencies and source findings are available in the retained construction.</p>}
      {prepared.warnings.map((warning, index) => <p className="warning" key={index}>{warning}</p>)}
      {prepared.rejects.map((reason, index) => <p role="alert" className="error-banner" key={index}>{reason}</p>)}
      <p>{needsBindings ? "Review source codes against the accepted chart. Every choice pins an immutable account version; a separate reviewer approves the construction." : "This intake retains source observations. It does not establish canonical financial identity."}</p>
      {needsBindings && <div className="data-scroll"><table><thead><tr><th>Source account</th><th>Shared account</th></tr></thead><tbody>
        {prepared.codes.slice(page * 50, (page + 1) * 50).map(code => <tr key={code}><td>{code}</td><td><select disabled={busy} aria-label={`Canonical account for ${code}`} value={bindings[code] ?? ""} onChange={event => setBindings(previous => ({ ...previous, [code]: event.target.value }))}>
          <option value="">Select an accepted account</option>{prepared.accounts.filter(account => account.account_code === code).map(account => <option key={account.version_id} value={account.version_id}>{account.account_code} · {account.display_name}</option>)}
        </select></td></tr>)}
      </tbody></table></div>}
      {needsBindings && <div className="pagination"><button className="quiet" disabled={page === 0} onClick={() => setPage(value => value - 1)}>Previous</button><span>{prepared.codes.filter(code => !!bindings[code]).length} / {prepared.codes.length} bound · page {page + 1}</span><button className="quiet" disabled={(page + 1) * 50 >= prepared.codes.length} onClick={() => setPage(value => value + 1)}>Next</button></div>}
      {needsBindings && prepared.accounts.length === 0 && <p className="warning">No accepted accounts are available in this context’s chart. Review the chart in Ontology before binding this source.</p>}
      <button disabled={busy || (needsBindings && prepared.codes.some(code => !bindings[code]))} onClick={() => void retain()}>Retain & inspect</button>
      <button className="quiet" disabled={busy} onClick={() => setPrepared(null)}>Cancel</button>
    </div>}
  </section><ReportInputs token={token} principal={principal} /></>;
}
