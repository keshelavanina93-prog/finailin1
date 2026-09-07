"use client";
import { useEffect, useRef, useState, type FormEvent } from "react";
import type { SourceAccountNavigation } from "./seg-account-observations";
import "./source-accounting-setup.css";
type Resource = {
  resource_id: string;
  version_id: string;
  display_name: string;
  attributes: Record<string, unknown>;
};
type Setup = {
  request_id: string;
  ledger_code: string;
  ledger_name: string;
  book_code: string;
  book_name: string;
  currency_id?: string;
  currency_code?: string;
  calendar: {
    resource_id: string;
  } | {
    code: string;
    name: string;
  };
  period: {
    resource_id: string;
  } | {
    name: string;
    starts_on: string;
    ends_on: string;
  };
  rationale: string;
};
type Receipt = {
  proposal_id: string;
  planned: {
    ledger_id: string;
    book_id: string;
    calendar_id: string;
    period_id: string;
    currency_id: string;
    company_id: string;
    chart_id: string;
  };
  created: Array<{
    resource_id: string;
    object_type: string;
  }>;
  reused: Array<{
    resource_id: string;
    version_id: string;
  }>;
  authority: "USER_ASSERTED_PROPOSAL";
  review_required: boolean;
  decision: null | "APPROVED" | "REJECTED";
};
type Props = {
  token: string;
  documentId: string;
  sheet: string;
  profile: string;
  companyId: string;
  companyName: string;
  chartId: string;
  chartName?: string;
  candidates: Record<string, Resource[]>;
  canPropose: boolean;
  refreshing: boolean;
  onRefresh: () => void;
  onProposal: (id: string) => void;
} & SourceAccountNavigation;
export default function SourceAccountingSetup(props: Props) {
  return <details className="source-accounting-setup">
    <summary>Set up accounting structure</summary>
    <SetupForm key={JSON.stringify([props.token, props.documentId, props.sheet, props.profile, props.companyId])} {...props} />
  </details>;
}
function SetupForm({ token, documentId, sheet, profile, companyId, companyName, chartId, chartName, candidates, canPropose, refreshing, onRefresh, onProposal, onInspectResource, onTraceResource }: Props) {
  const [currencyMode, setCurrencyMode] = useState("");
  const [calendarMode, setCalendarMode] = useState(""), [periodMode, setPeriodMode] = useState("");
  const [calendarId, setCalendarId] = useState(""), [periodId, setPeriodId] = useState(""), [currencyId, setCurrencyId] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [frozen, setFrozen] = useState<Setup | null>(null);
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => { active.current?.abort(); active.current = null; }, []);
  const locked = busy || Boolean(frozen);
  const resources = (type: string) => candidates[type] ?? [];
  const periods = resources("FiscalPeriod").filter(item => item.attributes.calendar_id === calendarId);
  const accepted = receipt ? [...resources("Ledger"), ...resources("AccountingBook"), ...resources("FiscalCalendar"), ...resources("FiscalPeriod")].filter(item => [receipt.planned.ledger_id, receipt.planned.book_id, receipt.planned.calendar_id, receipt.planned.period_id].includes(item.resource_id)) : [];
  function input(key: string, label: string, type = "text", maxLength = 128) {
    return <label>{label}<input type={type} value={values[key] ?? ""} required disabled={locked} maxLength={maxLength} onChange={event => setValues(previous => ({ ...previous, [key]: event.target.value }))} />
    </label>;
  }
  async function submit(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    if(busy || !canPropose || receipt)
      return;
    setError("");
    if(!frozen && (!calendarMode || !periodMode || !currencyMode || currencyMode === "existing" && !currencyId || calendarMode === "existing" && !calendarId || periodMode === "existing" && !periodId)) {
      setError("Choose currency, calendar and fiscal period explicitly.");
      return;
    }
    const setup: Setup = frozen ?? { request_id: crypto.randomUUID(), ledger_code: (values.ledger_code ?? "").trim(), ledger_name: (values.ledger_name ?? "").trim(), book_code: (values.book_code ?? "").trim(), book_name: (values.book_name ?? "").trim(), ...(currencyMode === "existing" ? { currency_id: currencyId } : { currency_code: (values.currency_code ?? "").trim() }), calendar: calendarMode === "existing" ? { resource_id: calendarId } : { code: (values.calendar_code ?? "").trim(), name: (values.calendar_name ?? "").trim() }, period: periodMode === "existing" ? { resource_id: periodId } : { name: (values.period_name ?? "").trim(), starts_on: values.starts_on ?? "", ends_on: values.ends_on ?? "" }, rationale: (values.rationale ?? "").trim() };
    if(setup.currency_code !== undefined && !/^[A-Z]{3}$/.test(setup.currency_code)) {
      setError("Enter an explicit three-letter uppercase currency code.");
      return;
    }
    if(setup.rationale.length < 10) {
      setError("Explain the accounting setup in at least 10 characters.");
      return;
    }
    setFrozen(setup);
    setBusy(true);
    const controller = new AbortController();
    active.current = controller;
    const timer = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(`/api/ontology/source-documents/${encodeURIComponent(documentId)}/accounting-context/setup-proposal`, { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ sheet, profile, company_id: companyId, setup }), signal: controller.signal, cache: "no-store" });
      const data = await response.json();
      if(!response.ok)
        throw new Error(typeof data.detail === "string" ? data.detail : `Setup proposal refused (${response.status}).`);
      const saved = data as Receipt;
      if(saved.authority !== "USER_ASSERTED_PROPOSAL" || ![null, "APPROVED", "REJECTED"].includes(saved.decision) || saved.review_required !== (saved.decision === null) || saved.planned?.company_id !== companyId || saved.planned?.chart_id !== chartId || !/^[a-f0-9-]{36}$/i.test(saved.proposal_id))
        throw new Error("Setup response did not match this source/company/chart proposal.");
      if(active.current === controller && !controller.signal.aborted)
        setReceipt(saved);
    }
    catch(failure) {
      if(active.current === controller)
        setError(controller.signal.aborted ? "Response timed out. Retry keeps the exact setup request; do not assume it was rejected." : failure instanceof Error ? failure.message : "Setup proposal unavailable.");
    }
    finally {
      clearTimeout(timer);
      if(active.current === controller)
        setBusy(false);
    }
  }
  return <section aria-label="Source accounting structure setup">
    <p>
      <strong>{companyName || "Selected canonical company"}</strong> · Source: {sheet} · Chart: {chartName || "Accepted canonical chart"}</p>
    <p>Currency and calendar choices are explicit user assertions. This creates a proposal for independent review; it does not activate accounting, convert amounts or create transactions.</p>
    {!canPropose && <p>This identity cannot propose accounting structure.</p>}
    <form onSubmit={submit}>
      <div className="accounting-setup-grid">{input("ledger_code", "Ledger code")}{input("ledger_name", "Ledger name")}{input("book_code", "Book code")}{input("book_name", "Book name")}<label>Currency choice<select value={currencyMode} required disabled={locked} onChange={event => { setCurrencyMode(event.target.value); setCurrencyId(""); }}>
        <option value="">Choose currency approach</option>
        <option value="existing">Reuse accepted currency</option>
        <option value="code">Declare a currency code for review</option>
      </select>
      </label>{currencyMode === "code" && input("currency_code", "Currency code (three uppercase letters)", "text", 3)}{currencyMode === "existing" && <label>Functional currency<select value={currencyId} required disabled={locked} onChange={event => setCurrencyId(event.target.value)}>
        <option value="">Choose currency</option>{resources("Currency").map(item => <option key={item.resource_id} value={item.resource_id}>{item.display_name}</option>)}</select>
      </label>}<label>Calendar choice<select value={calendarMode} required disabled={locked} onChange={event => { setCalendarMode(event.target.value); setCalendarId(""); setPeriodId(""); setPeriodMode(""); }}>
        <option value="">Choose calendar approach</option>
        <option value="existing">Reuse accepted calendar</option>
        <option value="new">Propose a new calendar</option>
      </select>
        </label>
        {calendarMode === "existing" && <label>Accepted calendar<select value={calendarId} required disabled={locked} onChange={event => { setCalendarId(event.target.value); setPeriodId(""); }}>
          <option value="">Choose calendar</option>{resources("FiscalCalendar").map(item => <option key={item.resource_id} value={item.resource_id}>{item.display_name}</option>)}</select>
        </label>}{calendarMode === "new" && <>{input("calendar_code", "Calendar code")}{input("calendar_name", "Calendar name")}</>}
        <label>Period choice<select value={periodMode} required disabled={locked || !calendarMode} onChange={event => { setPeriodMode(event.target.value); setPeriodId(""); }}>
          <option value="">Choose period approach</option>{calendarMode === "existing" && <option value="existing">Reuse accepted period</option>}<option value="new">Propose a new period</option>
        </select>
        </label>{periodMode === "existing" && <label>Accepted period<select value={periodId} required disabled={locked} onChange={event => setPeriodId(event.target.value)}>
          <option value="">Choose period in selected calendar</option>{periods.map(item => <option key={item.resource_id} value={item.resource_id}>{item.display_name} · {String(item.attributes.starts_on)} to {String(item.attributes.ends_on)}</option>)}</select>
        </label>}{periodMode === "new" && <>{input("period_name", "Fiscal period name")}{input("starts_on", "Period starts on", "date")}{input("ends_on", "Period ends on", "date")}</>}</div>
      <label>Basis for this accounting structure<textarea value={values.rationale ?? ""} required minLength={10} maxLength={2000} disabled={locked} onChange={event => setValues(previous => ({ ...previous, rationale: event.target.value }))} />
      </label>
      {!receipt && <div className="accounting-setup-actions">
        <button disabled={!canPropose || busy || refreshing} type="submit">{busy ? "Submitting setup…" : frozen ? "Retry exact setup proposal" : "Propose accounting structure"}</button>{frozen && !busy && <button type="button" onClick={() => { setFrozen(null); setError(""); }}>Discard local retry draft</button>}</div>}</form>
    {error && <p role="alert">{error}</p>}{frozen && !receipt && <p>Retry preserves the same proposal request. Discarding this local draft does not withdraw any proposal already retained by the server.</p>}
    {receipt && <p role="status">{receipt.decision === null ? "User-asserted setup proposal retained; independent review required." : receipt.decision === "APPROVED" ? "Setup proposal approved. Refresh to inspect the accepted structure; accounting activation is a separate step." : "Setup proposal rejected. This request does not establish accounting structure."} <button type="button" onClick={() => onProposal(receipt.proposal_id)}>Open existing proposal review</button>
    </p>}
    <button type="button" disabled={busy || refreshing} onClick={onRefresh}>Refresh accepted structure and candidates</button>{accepted.map(item => <p key={item.version_id}>{item.display_name} {onInspectResource && <button type="button" onClick={() => onInspectResource(item)}>Inspect accepted structure</button>}{onTraceResource && <button type="button" onClick={() => onTraceResource(item)}>Trace structure</button>}</p>)}
    <details>
      <summary>Exact source and setup references</summary>
      <p>Company: {companyId}</p>
      <p>Chart: {chartId}</p>
      <p>Source: {documentId} · {sheet} · {profile}</p>{frozen && <p>Setup request: {frozen.request_id}</p>}{receipt && <pre>{JSON.stringify(receipt, null, 2)}</pre>}</details>
  </section>;
}
