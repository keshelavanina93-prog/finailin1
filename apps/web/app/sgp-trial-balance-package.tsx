"use client";

import { useMemo, useState } from "react";
import type { Principal, ReceiptDetail, TrialBalancePackageReport } from "@finai/contracts";

const MEASURES = [
  ["opening_debit", "Opening Dr"],
  ["opening_credit", "Opening Cr"],
  ["turnover_debit", "Turnover Dr"],
  ["turnover_credit", "Turnover Cr"],
  ["closing_debit", "Closing Dr"],
  ["closing_credit", "Closing Cr"],
] as const;

const amount = (value?: string | null) => {
  if (value === undefined || value === null || value === "") return "—";
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString("en-US", { maximumFractionDigits: 2 }) : value;
};

const monthLabel = (period: string) => {
  const parsed = new Date(`${period}-01T12:00:00`);
  return Number.isNaN(parsed.valueOf()) ? period : parsed.toLocaleDateString("en-US", { month: "long", year: "numeric" });
};

type Props = {
  token: string;
  principal: Principal;
  report: TrialBalancePackageReport;
  onClose: () => void;
};

export default function SgpTrialBalancePackage({ token, principal, report, onClose }: Props) {
  const [selectedPeriod, setSelectedPeriod] = useState(report.months[0]?.period ?? "");
  const [detail, setDetail] = useState<ReceiptDetail | null>(null);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [mappingOpen, setMappingOpen] = useState(false);
  const selectedMonth = report.months.find(month => month.period === selectedPeriod) ?? report.months[0];
  const detailRows = useMemo(() => {
    const rows = detail?.receipt.candidates ?? [];
    const needle = query.trim().toLocaleLowerCase();
    return rows.filter(row => !needle || `${row.values.source_account_code ?? ""} ${row.values.source_account_name ?? ""} ${row.values.source_analytic_label ?? ""} ${row.source_row}`.toLocaleLowerCase().includes(needle));
  }, [detail, query]);
  const pageCount = Math.max(1, Math.ceil(detailRows.length / 50));

  async function openMonth(period: string) {
    const month = report.months.find(item => item.period === period);
    setSelectedPeriod(period); setPage(0); setQuery(""); setError("");
    if (!month?.receipt_id) { setDetail(null); return; }
    setBusy(true);
    try {
      const response = await fetch(`/api/workspace/constructions/${encodeURIComponent(month.receipt_id)}?period=${encodeURIComponent(period)}`, {
        headers: { Authorization: `Bearer ${token}` }, cache: "no-store",
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data?.detail === "string" ? data.detail : `Workbook details unavailable (${response.status})`);
      setDetail(data as ReceiptDetail);
    } catch (failure) { setDetail(null); setError(failure instanceof Error ? failure.message : "Workbook details unavailable"); }
    finally { setBusy(false); }
  }

  const rows = detailRows.slice(page * 50, page * 50 + 50);
  return <section className="tb-package-review" aria-label="2025 SOCAR Georgia Petroleum trial balance intake">
    <header className="tb-package-review-header"><div><button className="quiet" type="button" onClick={onClose}>← Evidence intake</button><p className="overline">HISTORICAL FINANCIAL EVIDENCE</p><h1>2025 Trial Balance Intake</h1><p>{report.entity_label} · SGP 1.xls — SGP 12.xls</p></div><span className={`tb-package-badge ${report.package_evidence_state === "SOURCE_PROOF_PASSED" ? "pass" : "review"}`}>{report.package_evidence_state === "SOURCE_PROOF_PASSED" ? "Source proof passed" : "Source review required"}</span></header>
    <div className="tb-package-metrics"><article><span>Workbooks</span><strong>{report.workbook_count}</strong><small>Jan — Dec 2025</small></article><article><span>Source rows</span><strong>{report.row_count.toLocaleString()}</strong><small>{report.row_count_state === "PASS" ? "Expected 38,137" : `Expected ${report.expected_row_count.toLocaleString()}`}</small></article><article><span>Proof integrity</span><strong>{report.months.filter(month => month.equality_state === "PASS").length} / 12</strong><small>Opening · turnover · closing pairs</small></article><article><span>Mapping status</span><strong className="tb-package-locked">Required</strong><small>Finance remains locked</small></article></div>
    <div className="tb-package-scope"><div><small>VALID TIME</small><strong>January — December 2025</strong></div><div><small>ACTIVE OPERATIONAL SCOPE</small><strong>{String(report.historical_scope_guard.active_runtime_period ?? principal.scope.period)}</strong></div><div><small>SCOPE GUARD</small><strong>Historical periods isolated</strong></div><div><small>CURRENCY</small><strong>{report.currency}</strong></div></div>
    <div className="tb-package-lock"><div><strong>Finance, Planning and Reporting are locked.</strong><p>Account mappings must be reviewed and approved before these observations can become reportable financial facts.</p></div><span>{report.account_codes.length.toLocaleString()} source account codes await mapping</span></div>
    <section className="tb-package-section"><div className="tb-package-section-heading"><div><p className="overline">PACKAGE EVIDENCE</p><h2>Monthly control proof</h2><p>Each workbook keeps its own period, hash, source totals and review state.</p></div><span>{report.carryforward_breaks ? `${report.carryforward_breaks} carryforward breaks` : "Carryforward checks passed"}</span></div><div className="tb-package-months"><table><thead><tr><th>Workbook</th><th>Valid period</th><th>Rows</th><th>Opening equality</th><th>Turnover equality</th><th>Closing equality</th><th>Hierarchy proof</th><th>Carryforward</th><th></th></tr></thead><tbody>{report.months.map((month, index) => { const carry = report.carryforward[index]; return <tr key={month.period}><td><strong>{month.filename}</strong><small>{month.source_sha256.slice(0, 12)}…</small></td><td>{monthLabel(month.period)}</td><td>{month.row_count.toLocaleString()}</td><td className={month.equality.opening_debit === "PASS" && month.equality.opening_credit === "PASS" ? "tb-pass" : "tb-break"}>{month.equality.opening_debit === "PASS" && month.equality.opening_credit === "PASS" ? "Pass" : "Break"}</td><td className={month.equality.turnover_debit === "PASS" && month.equality.turnover_credit === "PASS" ? "tb-pass" : "tb-break"}>{month.equality.turnover_debit === "PASS" && month.equality.turnover_credit === "PASS" ? "Pass" : "Break"}</td><td className={month.equality.closing_debit === "PASS" && month.equality.closing_credit === "PASS" ? "tb-pass" : "tb-break"}>{month.equality.closing_debit === "PASS" && month.equality.closing_credit === "PASS" ? "Pass" : "Break"}</td><td className={month.hierarchy_breaks ? "tb-break" : month.hierarchy_check_count ? "tb-pass" : "tb-muted"}>{month.hierarchy_check_count ? (month.hierarchy_breaks ? `Review · ${month.hierarchy_breaks}` : "Pass") : "—"}</td><td className={carry.state === "BREAK" ? "tb-break" : carry.state === "PASS" ? "tb-pass" : "tb-muted"}>{carry.state === "NOT_APPLICABLE" ? "—" : carry.state === "PASS" ? "Pass" : `Break · ${amount(carry.debit_delta)}`}</td><td><button className="quiet" type="button" disabled={busy} onClick={() => void openMonth(month.period)}>Open rows</button></td></tr>; })}</tbody></table></div></section>
    {error && <p className="error-banner" role="alert">{error}</p>}
    {detail && selectedMonth && <section className="tb-package-section tb-hierarchy-section"><div className="tb-package-section-heading"><div><p className="overline">1C TRIAL BALANCE HIERARCHY</p><h2>{detail.filename} · {monthLabel(selectedMonth.period)}</h2><p>Original source rows with the six retained amount columns. Parent/detail rows remain visible and are not silently added together.</p></div><span>{detailRows.length.toLocaleString()} matching rows</span></div><div className="tb-hierarchy-toolbar"><label>Find account or source row<input type="search" value={query} onChange={event => { setQuery(event.target.value); setPage(0); }} placeholder="Account code, name, analytic label or row" /></label><span>Source sheet: {detail.receipt.candidates[0]?.values.source_sheet ?? "TDSheet"}</span></div><div className="tb-hierarchy-table"><table><thead><tr><th>Account hierarchy</th>{MEASURES.map(([, label]) => <th className="tb-number" key={label}>{label}</th>)}</tr></thead><tbody>{rows.map(row => { const level = Math.min(8, Number(row.values.source_outline_level ?? "0") || 0); return <tr key={row.source_row}><td><div style={{ paddingLeft: `${level * 16}px` }}><strong>{row.values.source_account_code || "—"}</strong><span>{row.values.source_account_name || row.values.source_analytic_label || "Unlabelled source row"}</span><small>Row {row.source_row}{row.values.source_row_role ? ` · ${row.values.source_row_role.replaceAll("_", " ")}` : ""}</small></div></td>{MEASURES.map(([key]) => <td className="tb-number" key={key}>{amount(row.values[key])}</td>)}</tr>; })}</tbody></table>{!rows.length && <p className="tb-empty">No source rows match this search.</p>}</div><div className="tb-pagination"><span>Page {page + 1} of {pageCount}</span><button className="quiet" type="button" disabled={page === 0} onClick={() => setPage(value => value - 1)}>Previous</button><button className="quiet" type="button" disabled={page + 1 >= pageCount} onClick={() => setPage(value => value + 1)}>Next</button></div></section>}
    {!detail && <section className="tb-package-empty"><p>Select a month above to open its retained hierarchy.</p></section>}
    <section className="tb-package-mapping"><div><p className="overline">ACCOUNT MAPPING APPROVAL</p><h2>Review source codes before Finance unlock</h2><p>{report.account_codes.length.toLocaleString()} distinct source account codes are preserved. The package remains source evidence until each code has an accepted canonical account and an independent reviewer approves the mapping proposal.</p>{mappingOpen && <div className="tb-mapping-panel"><strong>Mapping candidate list</strong><p>Exact source codes are shown for governed selection. No account meaning is inferred from code text.</p><div className="tb-mapping-codes">{report.account_codes.slice(0, 120).map(code => <span key={code}>{code}</span>)}{report.account_codes.length > 120 && <span>+ {(report.account_codes.length - 120).toLocaleString()} more</span>}</div><small>Next step: select canonical account versions in the Ontology account-observation workflow, then submit the proposal for independent approval.</small></div>}</div><button className="quiet" type="button" disabled={!principal.permissions.includes("ontology_propose")} onClick={() => setMappingOpen(value => !value)}>{mappingOpen ? "Close mapping review" : "Open mapping review"}</button></section>
  </section>;
}

