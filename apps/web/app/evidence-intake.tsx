"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import type { IngestReceipt, Principal, TrialBalancePackageReport } from "@finai/contracts";
import ReportInputs from "./report-inputs";
import SgpTrialBalancePackage from "./sgp-trial-balance-package";

type DimensionRule = { rule_version_id: string; dimension_code: string; required: boolean; members: Array<{ code: string; version_id: string }> };
type Account = { resource_id: string; version_id: string; display_name: string; account_code: string; dimension_rules: DimensionRule[] };
type Prepared = { filename: string; csv_text?: string; xls_base64?: string; xlsx_base64?: string; context_version_id: string | null; codes: string[]; accounts: Account[]; observations: Record<string, string>; dimensionValues: Record<string, string[]>; rejects: string[]; warnings: string[] };
type PackageItem = Prepared & { status: "queued" | "preparing" | "ready" | "retaining" | "retained" | "failed"; error?: string };
const SGP_FILE_PATTERN = /^SGP\s+(?:[1-9]|1[0-2])\.xls$/;
const PACKAGE_TARGET = 12;
const PACKAGE_ROW_TARGET = 38137;

export default function EvidenceIntake({ token, principal, onRetained }: {
  token: string; principal: Principal; onRetained: (receipt: IngestReceipt) => Promise<void>;
}) {
  const [prepared, setPrepared] = useState<Prepared | null>(null);
  const [packagePrepared, setPackagePrepared] = useState<PackageItem[]>([]);
  const [packageReport, setPackageReport] = useState<TrialBalancePackageReport | null>(null);
  const [bindings, setBindings] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sourceOnly, setSourceOnly] = useState(false);
  const [sourceUse, setSourceUse] = useState("HISTORICAL_REFERENCE");
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

  async function encodeXls(file: File): Promise<string> {
    if (!file.size || file.size > 4_000_000) throw new Error("Choose an XLS workbook no larger than 4 MB.");
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = "";
    for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
    return btoa(binary);
  }

  async function prepareFile(file: File): Promise<Prepared> {
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
    // Historical workbooks never inherit the signed-in operational period. The source period
    // is established by the workbook adapter and remains a separate valid-time observation.
    const effectiveSourceUse = isWorkbook ? "HISTORICAL_REFERENCE" : sourceUse;
    const context_version_id = sourceOnly || isWorkbook || effectiveSourceUse !== "ACTUAL_INPUT" ? null : context.binding?.version_id ?? null;
    const source = await request<{ account_codes: string[]; source_class: string; observed_bindings: Record<string, string>; dimension_values: Record<string, string[]>; rejects: string[]; warnings: string[] }>("/api/ontology/context/source-accounts", {
      scope: principal.scope, filename: file.name, ...payload, context_version_id, source_use: effectiveSourceUse,
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
    return { filename: file.name, ...payload, context_version_id, codes: source.account_codes, accounts,
      observations: source.observed_bindings, dimensionValues: source.dimension_values, rejects: source.rejects, warnings: source.warnings };
  }

  async function prepare(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(""); setPrepared(null); setPackagePrepared([]);
    try {
      const input = event.currentTarget.elements.namedItem("source");
      const files = input instanceof HTMLInputElement ? Array.from(input.files ?? []) : [];
      if (!files.length) throw new Error("Choose at least one source workbook.");
      const isSgpPackage = files.some(file => SGP_FILE_PATTERN.test(file.name));
      if (isSgpPackage || files.length > 1) {
        if (files.length !== PACKAGE_TARGET) throw new Error("The SGP historical package requires exactly 12 monthly workbooks.");
        if (files.some(file => !SGP_FILE_PATTERN.test(file.name))) throw new Error("A package must contain SGP 1.xls through SGP 12.xls. Prepare CSV or XLSX files one at a time.");
        const names = files.map(file => file.name.toLocaleLowerCase());
        if (new Set(names).size !== names.length) throw new Error("Each monthly workbook can appear only once in the package.");
        const queued = files.map(file => ({ filename: file.name, status: "queued" as const } as PackageItem));
        setPackagePrepared(queued);
        const preparedItems: PackageItem[] = [];
        for (const file of files) {
          if (!alive.current) return;
          setPackagePrepared(previous => previous.map(item => item.filename === file.name ? { ...item, status: "preparing" } : item));
          try {
            const xls_base64 = await encodeXls(file);
            const item = { filename: file.name, xls_base64, context_version_id: null, codes: [], accounts: [], observations: {}, dimensionValues: {}, rejects: [], warnings: [], status: "ready" as const };
            preparedItems.push(item);
            setPackagePrepared(previous => previous.map(entry => entry.filename === file.name ? item : entry));
          } catch (failure) {
            const message = failure instanceof Error ? failure.message : "Source preparation failed";
            setPackagePrepared(previous => previous.map(entry => entry.filename === file.name ? { ...entry, status: "failed", error: message } : entry));
            throw new Error(`${file.name}: ${message}`);
          }
        }
        return;
      }
      const item = await prepareFile(files[0]);
      if (!alive.current) return;
      const selected: Record<string, string> = {};
      for (const code of item.codes) {
        const matches = item.accounts.filter(account => account.account_code === code);
        if (matches.length === 1) selected[code] = matches[0].version_id;
      }
      setPage(0); setBindings(selected); setPrepared(item);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Source preparation failed"); }
    finally { setBusy(false); }
  }

  async function retainPrepared(item: Prepared, selectedBindings: Record<string, string> = bindings) {
    return request<IngestReceipt>("/api/hydration", {
      scope: principal.scope, filename: item.filename, csv_text: item.csv_text,
      xls_base64: item.xls_base64,
      xlsx_base64: item.xlsx_base64, source_use: item.xls_base64 || item.xlsx_base64 ? "HISTORICAL_REFERENCE" : sourceUse,
      context_version_id: item.context_version_id,
      account_version_ids: item.context_version_id ? selectedBindings : {},
      account_dimension_rule_version_ids: item.context_version_id ? Object.fromEntries(item.codes.map(code => [code, (item.accounts.find(account => account.version_id === selectedBindings[code])?.dimension_rules ?? []).map(rule => rule.rule_version_id)])) : {},
      dimension_member_version_ids: item.context_version_id ? Object.fromEntries(Object.entries(item.dimensionValues).map(([name, values]) => {
        const members = item.accounts.filter(account => Object.values(selectedBindings).includes(account.version_id)).flatMap(account => account.dimension_rules.filter(rule => rule.dimension_code === name).flatMap(rule => rule.members));
        return [name, Object.fromEntries(values.flatMap(value => {
          const matches = [...new Set(members.filter(member => member.code === value).map(member => member.version_id))];
          return matches.length === 1 ? [[value, matches[0]]] : [];
        }))];
      })) : {},
    });
  }

  async function retain() {
    if (!prepared) return;
    setBusy(true); setError("");
    try {
      const receipt = await retainPrepared(prepared);
      if (!alive.current) return;
      setPrepared(null); fileForm.current?.reset(); await onRetained(receipt);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Evidence could not be retained"); }
    finally { setBusy(false); }
  }

  async function retainPackage() {
    const ready = packagePrepared.filter(item => item.status === "ready");
    if (!ready.length || ready.length !== packagePrepared.length) return;
    setBusy(true); setError("");
    try {
      const report = await request<TrialBalancePackageReport>("/api/hydration/package", {
        year: 2025,
        files: ready.map(item => ({ filename: item.filename, xls_base64: item.xls_base64 })),
      });
      if (!alive.current) return;
      setPackagePrepared(previous => previous.map(entry => ({ ...entry, status: "retained" })));
      setPackageReport(report);
      setPackagePrepared([]); fileForm.current?.reset();
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Package ingestion failed"); }
    finally { setBusy(false); }
  }

  const needsBindings = !!prepared?.context_version_id && !!prepared.codes.length;
  return <>{packageReport && <SgpTrialBalancePackage token={token} principal={principal} report={packageReport} onClose={() => setPackageReport(null)} />}<section className="data-panel intake-binding">
    <form ref={fileForm} className="upload-strip" onSubmit={prepare}>
      <div><p className="overline">HISTORICAL SOURCE PACKAGE</p><h2>2025 Trial Balance Intake</h2><p>SOCAR Georgia Petroleum · SGP 1.xls — SGP 12.xls</p>
        <p>Monthly 1C workbooks are retained against their 2025 valid periods. The active operational scope ({principal.scope.period}) is kept separate.</p></div>
      <label>Source workbook(s)<input type="file" accept=".csv,.xls,.xlsx" name="source" multiple required disabled={busy} onChange={() => { setPrepared(null); setPackagePrepared([]); setPackageReport(null); setError(""); }} /><small>Select exactly 12 SGP XLS workbooks for an asynchronous package intake.</small></label>
      <label>Intended use<select value={sourceUse} disabled={busy} onChange={event => { setSourceUse(event.target.value); setPrepared(null); }}><option value="ACTUAL_INPUT">Facts for selected period</option><option value="HISTORICAL_REFERENCE">Historical source example</option><option value="REPORT_TEMPLATE">Reporting requirement example</option><option value="MAPPING_REFERENCE">Mapping reference</option></select></label>
      <button disabled={busy}>{busy ? "Preparing…" : "Prepare intake"}</button>
      <label className="source-only-choice"><input type="checkbox" checked={sourceOnly} disabled={busy} onChange={event => { setSourceOnly(event.target.checked); setPrepared(null); }} /> Retain as source evidence without canonical binding</label>
    </form>
    {error && <p role="alert" className="error-banner">{error}</p>}
    {packagePrepared.length > 0 && <section className="tb-package-intake" aria-label="2025 trial balance package preparation">
      <header><div><p className="overline">PACKAGE MANIFEST</p><h3>SGP 2025 monthly workbooks</h3><p>{packagePrepared.filter(item => item.status === "ready" || item.status === "retained").length} of {PACKAGE_TARGET} selected · target {PACKAGE_ROW_TARGET.toLocaleString()} source rows</p></div><span className={`tb-package-status ${packagePrepared.every(item => item.status === "ready") ? "ready" : "working"}`}>{packagePrepared.every(item => item.status === "ready") ? "Ready to retain" : "Preparing package"}</span></header>
      <div className="tb-package-list">{packagePrepared.map(item => <div className="tb-package-row" key={item.filename}><span className="tb-package-file">{item.filename}</span><span className="tb-package-period">{item.observations?.period || "2025 month detected by adapter"}</span><span className={`tb-package-item-status ${item.status}`}>{item.status === "preparing" ? "Reading workbook…" : item.status === "retaining" ? "Retaining…" : item.status === "retained" ? "Retained" : item.status === "failed" ? item.error || "Failed" : item.status === "ready" ? "Ready" : "Queued"}</span></div>)}</div>
      <p className="tb-package-note">Package ingestion runs one workbook at a time so a slow workbook does not block or duplicate the others. Each original hash remains independently traceable. Finance, Planning and Reporting stay locked until mappings are approved.</p>
      <div className="tb-package-actions"><button disabled={busy || !packagePrepared.every(item => item.status === "ready")} onClick={() => void retainPackage()}>Retain package asynchronously</button><button className="quiet" disabled={busy} onClick={() => { setPackagePrepared([]); fileForm.current?.reset(); }}>Cancel package</button></div>
    </section>}
    {prepared && <div className="binding-review"><h3>{prepared.filename}</h3>
      {prepared.xls_base64 && <p className="warning">This XLS is retained as source observations. Company, currency and repeated account rows require review before financial use. It cannot create journal entries or certified reports.</p>}
      {prepared.xls_base64 && <p>Source company: {prepared.observations.company_label} · Source month: {prepared.observations.period}</p>}
      {prepared.xlsx_base64 && <p>Observed company: {prepared.observations.company_label} · Observed period: {prepared.observations.period}. Formula dependencies and source findings are available in the retained construction.</p>}
      {prepared.warnings.map((warning, index) => <p className="warning" key={index}>{warning}</p>)}
      {prepared.rejects.map((reason, index) => <p role="alert" className="error-banner" key={index}>{reason}</p>)}
      <p>{needsBindings ? "Review source codes against the accepted chart. Every choice pins an immutable account version; a separate reviewer approves the construction." : "This intake retains source observations. It does not establish canonical financial identity."}</p>
      {needsBindings && <div><h4>Account dimensions</h4><p>CSV analytical columns use dimension: followed by the canonical dimension code. Values must match accepted member codes. Missing or unknown values are retained as row findings and block approval.</p>{prepared.codes.flatMap(code => (prepared.accounts.find(account => account.version_id === bindings[code])?.dimension_rules ?? []).map(rule => <p key={`${code}:${rule.rule_version_id}`}>{code}: dimension:{rule.dimension_code} — {rule.required ? "required" : "optional"}</p>))}</div>}
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
