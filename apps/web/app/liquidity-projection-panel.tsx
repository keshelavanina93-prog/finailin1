"use client";

import { useState } from "react";

type Liquidity = { contract: "liquidity-projection/1"; rows: Array<{ period_id: string; currency_id: string; inflow: string; outflow: string; net: string }>; coverage: string; treasury_authority: boolean };

export default function LiquidityProjectionPanel({ token, scenarioId }: { token: string; scenarioId: string }) {
  const [result, setResult] = useState<Liquidity | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function project() {
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/ontology/planning/liquidity?scenario_id=${encodeURIComponent(scenarioId)}`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
      const data = await response.json() as Liquidity & { detail?: string };
      if (!response.ok) throw new Error(data.detail ?? "Liquidity projection unavailable");
      setResult(data);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Liquidity projection unavailable"); }
    finally { setBusy(false); }
  }
  return <section className="g8-panel" aria-label="Liquidity projection"><div className="g8-panel-heading"><div><p className="overline">TREASURY · ACCEPTED CASH FACTS</p><h3>Liquidity projection</h3><p>Aggregates accepted cash planning cells by period and currency. It is an analytical projection, not a treasury posting or cash authority.</p></div><button onClick={() => void project()} disabled={busy || !scenarioId}>{busy ? "Projecting…" : "Project liquidity"}</button></div>{error && <p className="g8-inline-error" role="alert">{error}</p>}{result && <><p role="status">{result.coverage} · treasury authority: {String(result.treasury_authority)}</p>{result.rows.length ? <div className="g8-table-scroll"><table><thead><tr><th>Period</th><th>Currency</th><th>Inflow</th><th>Outflow</th><th>Net</th></tr></thead><tbody>{result.rows.map(row => <tr key={`${row.period_id}:${row.currency_id}`}><td>{row.period_id}</td><td>{row.currency_id}</td><td>{row.inflow}</td><td>{row.outflow}</td><td>{row.net}</td></tr>)}</tbody></table></div> : <p>No accepted cash planning cells were found.</p>}</>}</section>;
}
