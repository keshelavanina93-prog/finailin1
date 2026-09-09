"use client";

import {useEffect, useState} from "react";
import {Badge} from "./g8-ui";
import {operationsRequest} from "./operations-model";

type Row = {dimensions: Record<string, string>; reading_count: number; invalid_readings: number; first_timestamp: string | null; last_timestamp: string | null; minimum_value: string; maximum_value: string; gap_count: number; basis_state: string; status: string};
type Result = {rows: Row[]; measurement_count: number; live_connector: boolean; warning: string};

export default function PetroleumTelemetryPanel({token, companyId}: {token: string; companyId?: string}) {
  const [result, setResult] = useState<Result | null>(null); const [error, setError] = useState("");
  useEffect(() => { const controller = new AbortController(); const query = companyId ? `?company_id=${encodeURIComponent(companyId)}` : "";
    void operationsRequest<Result>(`petroleum/telemetry${query}`, token, controller.signal).then(setResult).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Telemetry unavailable"); });
    return () => controller.abort();
  }, [companyId, token]);
  return <section className="g8-panel petroleum-margin" aria-label="Petroleum telemetry series"><header className="g8-panel-heading"><div><p className="overline">PETROLEUM · MEASUREMENT SERIES</p><h3>Meter telemetry quality</h3><p>Accepted measurements are grouped by meter, asset, location, unit and measurement basis. Gaps and quality issues remain visible for review.</p></div><Badge>{result ? `${result.measurement_count} readings` : "Reading accepted facts"}</Badge></header>{error && <p className="g8-inline-error" role="alert">{error}</p>}{result && <>{result.rows.length ? <div className="g8-table-scroll"><table><thead><tr><th>Series</th><th>Readings</th><th>Window</th><th>Range</th><th>Basis</th><th>Status</th></tr></thead><tbody>{result.rows.map(row => <tr key={JSON.stringify(row.dimensions)}><td>{Object.entries(row.dimensions).filter(([, value]) => value).map(([key, value]) => `${key}: ${value}`).join(" · ")}</td><td>{row.reading_count}{row.invalid_readings ? ` · ${row.invalid_readings} invalid` : ""}</td><td>{row.first_timestamp ?? "—"}<br/>{row.last_timestamp ?? "—"}</td><td>{row.minimum_value} – {row.maximum_value}</td><td><Badge tone={row.basis_state === "COMPLETE" ? "good" : "warning"}>{row.basis_state}</Badge></td><td><Badge tone={row.status === "SERIES_ORDERED" ? "good" : "warning"}>{row.status}{row.gap_count ? ` · ${row.gap_count} gaps` : ""}</Badge></td></tr>)}</tbody></table></div> : <p>No accepted PhysicalMeasurement resources are available in this scope.</p>}<small>{result.warning} Live connector: {String(result.live_connector)} · Accounting authorized: false</small></>}</section>;
}
