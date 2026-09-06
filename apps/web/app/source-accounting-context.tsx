"use client";
import { useEffect, useId, useRef, useState } from "react";

type Resource = { resource_id: string; version_id: string; display_name: string; attributes: Record<string, string> };
type SourceObservations = { source_sha256: string; construction_receipt_id?: string; source_snapshot?: { source_use?: string }; row_count: number; granularity?: string; deepest_valid_drill?: string; unresolved?: string[]; sample_rows?: { row: number; numeric_observations: Record<string, { coordinate: string; value: string }> }[] };
type Context = { scope_id: string; observed: Record<string, string>; source_coordinate?: string; source_company_label?: string; canonical_ready?: boolean; unresolved?: string[]; source_observations?: SourceObservations; scope: Resource | null; binding: Resource | null; candidates: Record<string, Resource[]> };
const fields = ["ledger_id", "book_id", "period_id", "currency_id", "currency_role", "functional_currency_id", "transaction_currency_id", "reporting_currency_id", "currency_policy", "account_mapping_id", "dimension_mapping_id", "granularity", "deepest_valid_drill", "amount_field", "amount_semantics"];
const required = ["ledger_id", "book_id", "period_id", "currency_id", "currency_role", "functional_currency_id", "currency_policy", "account_mapping_id", "dimension_mapping_id", "granularity", "deepest_valid_drill", "amount_field", "amount_semantics"];

export default function SourceAccountingContext({ token, documentId, sheet, profile, companyId, canPropose, onProposal }: {
  token: string; documentId: string; sheet: string; profile: string; companyId: string; canPropose: boolean; onProposal: (id: string) => void;
}) {
  const [loaded, setLoaded] = useState<{ key: string; value: Context } | null>(null);
  const [use, setUse] = useState("");
  const [selection, setSelection] = useState<Record<string, string>>({});
  const [rationale, setRationale] = useState("");
  const [unresolved, setUnresolved] = useState("");
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState("");
  const pending = useRef<AbortController | null>(null);
  const prefix = useId();
  const contextKey = JSON.stringify([token, documentId, sheet, profile, companyId]);
  const busy = busyKey === contextKey;
  const context = loaded?.key === contextKey ? loaded.value : null;
  useEffect(() => () => pending.current?.abort(), [contextKey]);

  async function run(action: "inspect" | "scope-proposal" | "binding-proposal") {
    pending.current?.abort();
    const controller = new AbortController(); pending.current = controller;
    setBusyKey(contextKey); setError("");
    const chosen = Object.fromEntries(fields.flatMap(key => selection[key]?.trim() ? [[key, selection[key].trim()]] : []));
    try {
      const response = await fetch(`/api/ontology/source-documents/${documentId}/accounting-context/${action}`, {
        method: "POST", signal: controller.signal,
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ sheet, profile, company_id: companyId,
          ...(action === "binding-proposal" ? { selection: {
            contract_version: "2", source_use: use, rationale: rationale.trim(),
            ...(use === "STRUCTURAL_REFERENCE" ? {} : chosen),
            ...(use === "REVIEW_CANDIDATE" ? { unresolved_reason: unresolved.trim() } : {}),
          } } : {}),
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Accounting context rejected");
      if (controller.signal.aborted) return;
      if (action !== "inspect") onProposal(data.proposal.proposal_id);
      else {
        setLoaded({ key: contextKey, value: data });
        setUse(data.binding?.attributes.source_use ?? "");
        setRationale(data.binding?.attributes.rationale ?? "");
        setUnresolved(data.binding?.attributes.unresolved_reason ?? "");
        setSelection(Object.fromEntries(fields.flatMap(key => data.binding?.attributes[key] ? [[key, data.binding.attributes[key]]] : [])));
      }
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "Accounting context unavailable");
    } finally { if (!controller.signal.aborted) setBusyKey(null); }
  }

  const candidates = (type: string) => context?.candidates[type] ?? [];
  const ledger = candidates("Ledger").find(row => row.resource_id === selection.ledger_id);
  const choices: [string, string, Resource[]][] = context ? [
    ["ledger_id", "Ledger", candidates("Ledger")],
    ["book_id", "Accounting book", candidates("AccountingBook").filter(row => row.attributes.ledger_id === selection.ledger_id)],
    ["period_id", "Fiscal period", candidates("FiscalPeriod").filter(row => ledger && row.attributes.calendar_id === ledger.attributes.calendar_id && row.attributes.starts_on <= context.observed.observed_from && row.attributes.ends_on >= context.observed.observed_through)],
    ["currency_id", "Selected source amount currency", candidates("Currency")],
    ["functional_currency_id", "Functional currency", candidates("Currency").filter(row => ledger && row.resource_id === ledger.attributes.currency_id)],
    ["transaction_currency_id", "Transaction currency (when applicable)", candidates("Currency")],
    ["reporting_currency_id", "Reporting currency (when applicable)", candidates("Currency")],
    ["account_mapping_id", "Account mapping", candidates("MappingVersion")],
    ["dimension_mapping_id", "Dimension mapping", candidates("MappingVersion")],
  ] : [];
  const multipleCurrenciesReady = selection.currency_policy !== "MULTI_CURRENCY" || Boolean(selection.transaction_currency_id && selection.reporting_currency_id);
  const roleFields: Record<string, string> = { FUNCTIONAL: "functional_currency_id", TRANSACTION: "transaction_currency_id", PRESENTATION: "reporting_currency_id" };
  const roleField = roleFields[selection.currency_role];
  const roleAgrees = Boolean(roleField && selection[roleField] === selection.currency_id);
  const resourcesExist = choices.every(([key, , rows]) => !selection[key] || rows.some(row => row.resource_id === selection[key]));
  const depthAgrees = selection.granularity !== "PERIOD_ACCOUNT" || selection.deepest_valid_drill === "PERIOD_ACCOUNT";
  const complete = use === "STRUCTURAL_REFERENCE" || (use === "REVIEW_CANDIDATE" && unresolved.trim().length >= 10) ||
    (use === "ACCOUNTING_INPUT" && required.every(key => selection[key]?.trim()) && multipleCurrenciesReady && roleAgrees && resourcesExist && depthAgrees);
  const canonicalReady = context?.canonical_ready === true;

  function change(key: string, value: string) {
    setSelection(previous => key === "ledger_id" ? { ...previous, ledger_id: value, book_id: "", period_id: "", functional_currency_id: "" } : { ...previous, [key]: value });
  }
  function select(key: string, label: string, options: [string, string][]) {
    return <div key={key}><label htmlFor={`${prefix}-${key}`}>{label}</label><select id={`${prefix}-${key}`} value={selection[key] ?? ""} onChange={event => change(key, event.target.value)}>
      <option value="">Select {label.toLowerCase()}</option>{options.map(([value, name]) => <option key={value} value={value}>{name}</option>)}
    </select></div>;
  }

  return <section><h3>Source accounting context</h3>
    <p>Decide how the observed company, dates and amounts may be used. A proposal preserves the decision for review.</p>
    <button disabled={busy} onClick={() => void run("inspect")}>Inspect source accounting context</button>
    {busy && <p role="status">Resolving source accounting context…</p>}
    {error && <p role="alert">{error}</p>}
    {context && <>
      {context.source_company_label && <p>Company reported by the source: <strong>{context.source_company_label}</strong></p>}
      <p>{context.observed.observed_from} → {context.observed.observed_through} · {context.observed.date_basis === "EXPLICIT_REPORT_PERIOD" ? "Period explicitly stated in the report" : "Extent of observed movement dates"}. Completeness remains unestablished.</p>
      <p>Evidence: {sheet}{context.source_coordinate ? ` · ${context.source_coordinate}` : ""}. Drill must remain within the retained evidence grain.</p>
      {context.source_observations && <details><summary>{context.source_observations.row_count} observed rows · retained source evidence</summary>
        <p>Original source use: {context.source_observations.source_snapshot?.source_use?.toLowerCase().replaceAll("_", " ") ?? "See retained source"}. {context.source_observations.deepest_valid_drill && `Deepest supported drill: ${context.source_observations.deepest_valid_drill.toLowerCase().replaceAll("_", " ")}.`}</p>
        <p>Source SHA-256: <code>{context.source_observations.source_sha256}</code></p>
        {context.source_observations.construction_receipt_id && <p>Original receipt: <code>{context.source_observations.construction_receipt_id}</code></p>}
        {context.source_observations.unresolved?.map(reason => <p key={reason}>{reason}</p>)}
        {Boolean(context.source_observations.sample_rows?.length) && <table><caption>Original source numerals · accounting meaning unresolved</caption><thead><tr><th>Row</th><th>Сумма</th><th>Annotated Amount</th></tr></thead><tbody>
          {context.source_observations.sample_rows?.map(row => <tr key={row.row}><td>{sheet}!{row.row}</td>{["source_amount", "annotated_amount"].map(key => <td key={key} title={row.numeric_observations[key]?.coordinate}>{row.numeric_observations[key]?.value ?? "Not recorded"}</td>)}</tr>)}
        </tbody></table>}
      </details>}
      {!canonicalReady && <div role="status"><p>Source-company or chart binding is unresolved. Scope publication and accounting activation are blocked.</p>{context.unresolved?.map(reason => <p key={reason}>{reason}</p>)}</div>}
      {profile === "seg_expense_base" && <p>The source amount and annotated Amount have unresolved currency and accounting meanings. Petroleum counterparty labels do not identify the source company.</p>}
      <p>Observed scope: {context.scope ? "Published" : "Awaiting publication"}. Accounting use: {context.binding ? context.binding.attributes.source_use.toLowerCase().replaceAll("_", " ") : "Not selected"}.</p>
      {!context.scope && canPropose && <button disabled={busy || !canonicalReady} onClick={() => void run("scope-proposal")}>Propose observed source scope</button>}
      {context.scope && <>
        <label htmlFor={`${prefix}-use`}>Source use</label><select id={`${prefix}-use`} value={use} onChange={event => setUse(event.target.value)}>
          <option value="">Select accounting use</option><option value="STRUCTURAL_REFERENCE">Structural reference</option><option value="REVIEW_CANDIDATE">Review candidate · meaning unresolved</option><option value="ACCOUNTING_INPUT">Accounting input</option>
        </select>
        {use === "REVIEW_CANDIDATE" && <><label htmlFor={`${prefix}-unresolved`}>What still needs resolution?</label><textarea id={`${prefix}-unresolved`} value={unresolved} onChange={event => setUnresolved(event.target.value)} maxLength={2000}/><p>This preserves an open interpretation; it does not authorize calculations.</p></>}
        {(use === "ACCOUNTING_INPUT" || use === "REVIEW_CANDIDATE") && <fieldset><legend>Accounting interpretation</legend>
          {!candidates("Ledger").length && <p>No accepted ledger matches this company and chart. Accounting activation is blocked.</p>}
          {!candidates("MappingVersion").length && <p>No accepted mapping is available. Account and dimension meanings require reviewed mapping references.</p>}
          {choices.map(([key, label, rows]) => select(key, label, rows.map(row => [row.resource_id, row.display_name])))}
          {select("currency_role", "Source amount currency role", [["FUNCTIONAL", "Functional"], ["TRANSACTION", "Transaction"], ["PRESENTATION", "Reporting / presentation"]])}
          {select("currency_policy", "Currency interpretation", [["SOURCE_AMOUNT_ONLY", "Selected source amount only"], ["MULTI_CURRENCY", "Explicit functional, transaction and reporting currencies"]])}
          <p>Blank source currency cells establish no currency. Selecting a currency does not perform conversion.</p>
          {select("granularity", "Source grain", profile === "1c_tb" ? [["PERIOD_ACCOUNT", "Period and account"]] : [["SOURCE_ROW", "Source row"], ["PERIOD_ACCOUNT", "Period and account"]])}
          {select("deepest_valid_drill", "Deepest supported evidence", selection.granularity === "PERIOD_ACCOUNT" ? [["PERIOD_ACCOUNT", "Period and account"]] : [["SOURCE_CELL", "Source cell"], ["SOURCE_ROW", "Source row"], ["PERIOD_ACCOUNT", "Period and account"]])}
          <label htmlFor={`${prefix}-amount-field`}>Amount property in the source contract</label><input id={`${prefix}-amount-field`} value={selection.amount_field ?? ""} onChange={event => change("amount_field", event.target.value)} maxLength={128}/>
          {select("amount_semantics", "Amount meaning", [["DEBIT_CREDIT", "Separate debit and credit"], ["SIGNED_MOVEMENT", "Signed movement"], ["PERIOD_BALANCE", "Period balance"]])}
          <p>The amount property must be supported by source evidence and the reviewed contract. A source label alone does not establish gross/net treatment or VAT recoverability.</p>
          {use === "ACCOUNTING_INPUT" && !complete && <p>Accounting use requires all mappings, compatible currency roles and supported evidence depth. Keep unresolved choices as a review candidate.</p>}
        </fieldset>}
        <label htmlFor={`${prefix}-rationale`}>Basis for this choice</label><textarea id={`${prefix}-rationale`} value={rationale} onChange={event => setRationale(event.target.value)} maxLength={2000}/>
        {canPropose && <button disabled={busy || !canonicalReady || !complete || rationale.trim().length < 10} onClick={() => void run("binding-proposal")}>Propose accounting context for review</button>}
      </>}
    </>}
  </section>;
}
