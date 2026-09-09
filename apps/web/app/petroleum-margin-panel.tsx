"use client";

import {useEffect, useState} from "react";
import {Badge} from "./g8-ui";
import {operationsRequest} from "./operations-model";

type Row = {dimensions: Record<string, string>; volume: string; revenue: string; cogs: string | null; gross_margin: string | null; status: string; source_resource_ids: string[]};
type Result = {rows: Row[]; counts: Record<string, number>; accounting_authorized: boolean; business_effect_authorized: boolean; warning: string};

export default function PetroleumMarginPanel({token, companyId}: {token: string; companyId?: string}) {
  const [result, setResult] = useState<Result | null>(null); const [error, setError] = useState("");
  useEffect(() => { const controller = new AbortController(); const query = companyId ? `?company_id=${encodeURIComponent(companyId)}` : "";
    void operationsRequest<Result>(`petroleum/margin${query}`, token, controller.signal).then(setResult).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Margin bridge unavailable"); });
    return () => controller.abort();
  }, [companyId, token]);
  return <section className="g8-panel petroleum-margin" aria-label="Petroleum revenue and margin bridge"><header className="g8-panel-heading"><div><p className="overline">PETROLEUM · REVENUE / COGS BRIDGE</p><h3>Sales volume to gross margin</h3><p>Accepted RetailSale and ProductCost resources are joined by exact operating dimensions. Missing COGS remains visible as a gap.</p></div><Badge>{result ? `${result.rows.length} dimensions` : "Reading accepted facts"}</Badge></header>{error && <p className="g8-inline-error" role="alert">{error}</p>}{result && <>{result.rows.length ? <div className="g8-table-scroll"><table><thead><tr><th>Dimensions</th><th>Volume</th><th>Revenue</th><th>COGS</th><th>Gross margin</th><th>Status</th></tr></thead><tbody>{result.rows.map(row => <tr key={JSON.stringify(row.dimensions)}><td>{Object.entries(row.dimensions).filter(([, value]) => value).map(([key, value]) => `${key}: ${value}`).join(" · ")}</td><td>{row.volume}</td><td>{row.revenue}</td><td>{row.cogs ?? "Unavailable"}</td><td>{row.gross_margin ?? "Unavailable"}</td><td><Badge tone={row.status === "COMPLETE" ? "good" : "warning"}>{row.status}</Badge></td></tr>)}</tbody></table></div> : <p>No accepted RetailSale resources are available in this scope.</p>}<small>{result.warning} Accounting authorized: {String(result.accounting_authorized)} · Business effect authorized: {String(result.business_effect_authorized)}</small></>}</section>;
}
