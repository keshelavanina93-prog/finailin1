"use client";

import type { WorkspaceProjectionData } from "@finai/contracts";

type Point = { label: string; value: number };

function points(data: WorkspaceProjectionData): Point[] {
  return data.rows.flatMap((row, index) => {
    const candidate = row.delta ?? row.amount ?? row.scenario_b ?? row.value;
    const value = typeof candidate === "number" ? candidate : Number(candidate);
    return Number.isFinite(value) ? [{ label: String(row.label ?? row.period_id ?? row.dimension ?? `Row ${index + 1}`), value }] : [];
  }).slice(0, 24);
}

function NumericTable({ values }: { values: Point[] }) {
  return <div className="g8-table-scroll"><table><caption>Governed values used by this projection</caption><thead><tr><th>Coordinate</th><th>Value</th></tr></thead><tbody>{values.map(point => <tr key={`${point.label}:${point.value}`}><th>{point.label}</th><td>{point.value}</td></tr>)}</tbody></table></div>;
}

export default function ProjectionDataRenderer({ data }: { data: WorkspaceProjectionData }) {
  const values = points(data);
  if (!values.length) return <p role="status">This exact projection returned no numeric governed rows; no visual has been inferred.</p>;
  const maximum = Math.max(...values.map(point => Math.abs(point.value)), 1);
  const isChart = data.projection.kind === "CHART" || data.projection.kind === "WATERFALL";
  return <div className="g8-projection-result"><h4>{data.projection.label} · {data.data_state}</h4><p>Read-only projection · authority effect: {data.authority_effect} · synchronization: {data.projection.synchronization_group}</p>{data.projection.kind === "KPI" && <div className="g8-facts"><div><strong>{values.length}</strong><small>Governed rows</small></div><div><strong>{values.reduce((sum, point) => sum + point.value, 0).toFixed(2)}</strong><small>Deterministic total</small></div></div>}{isChart && <div className="g8-projection-chart" role="img" aria-label={`${data.projection.label} for the exact selected context`}><svg viewBox="0 0 720 240" preserveAspectRatio="none"><line x1="16" y1="220" x2="704" y2="220" stroke="currentColor" opacity=".35" />{values.map((point, index) => { const width = Math.max(8, 680 / values.length - 6); const height = Math.max(2, Math.abs(point.value) / maximum * 180); const x = 20 + index * (680 / values.length); const y = point.value < 0 ? 220 : 220 - height; return <rect key={`${point.label}:${index}`} x={x} y={y} width={width} height={height} rx="3" data-value={point.value} />; })}</svg></div>}{data.projection.kind !== "KPI" && <NumericTable values={values} />}</div>;
}
