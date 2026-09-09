"use client";

import {useEffect, useState} from "react";
import {Badge} from "./g8-ui";
import {operationsRequest} from "./operations-model";

type Row = {movement_resource_id: string; journal_line_resource_id: string | null; dimensions: Record<string, string>; movement_quantity: string | null; journal_quantity: string | null; status: string; reason: string};
type Result = {rows: Row[]; counts: Record<string, number>; warning: string};

export default function MovementJournalReconciliationPanel({token, companyId}: {token: string; companyId?: string}) {
  const [result, setResult] = useState<Result | null>(null); const [error, setError] = useState("");
  useEffect(() => { const controller = new AbortController(); const query = companyId ? `?company_id=${encodeURIComponent(companyId)}` : "";
    void operationsRequest<Result>(`petroleum/movement-journal-reconciliation${query}`, token, controller.signal).then(setResult).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Journal reconciliation unavailable"); });
    return () => controller.abort();
  }, [companyId, token]);
  return <section className="g8-panel petroleum-margin" aria-label="Movement to journal reconciliation"><header className="g8-panel-heading"><div><p className="overline">MOVEMENTS · JOURNAL COVERAGE</p><h3>Physical movement to booked line</h3><p>Evidence and document identity are checked against accepted JournalLine resources. A match is reference coverage, never posting authority.</p></div><Badge>{result ? `${result.rows.length} movements` : "Reading accepted facts"}</Badge></header>{error && <p className="g8-inline-error" role="alert">{error}</p>}{result && <>{result.rows.length ? <div className="g8-table-scroll"><table><thead><tr><th>Movement dimensions</th><th>Movement qty</th><th>Journal qty</th><th>Status</th><th>Reason</th></tr></thead><tbody>{result.rows.map(row => <tr key={row.movement_resource_id}><td>{Object.entries(row.dimensions).filter(([, value]) => value).map(([key, value]) => `${key}: ${value}`).join(" · ")}</td><td>{row.movement_quantity ?? "Unavailable"}</td><td>{row.journal_quantity ?? "Unavailable"}</td><td><Badge tone={row.status === "MATCHED" ? "good" : "warning"}>{row.status}</Badge></td><td>{row.reason}</td></tr>)}</tbody></table></div> : <p>No accepted PhysicalMovement resources are available in this scope.</p>}<small>{result.warning} Accounting authorized: false · Business effect authorized: false</small></>}</section>;
}
