"use client";

import type { WorkspaceProjectionData } from "@finai/contracts";

type Point = { label: string; value: number };

type Edge = { source_id: string; target_id: string; relation?: string };

function points(data: WorkspaceProjectionData): Point[] {
  return data.rows.flatMap((row, index) => {
    const candidate = row.delta ?? row.amount ?? row.scenario_b ?? row.value;
    const value = typeof candidate === "number" ? candidate : Number(candidate);
    return Number.isFinite(value) ? [{ label: String(row.label ?? row.period_id ?? row.dimension ?? `Row ${index + 1}`), value }] : [];
  }).slice(0, 24);
}

function edges(data: WorkspaceProjectionData): Edge[] {
  return data.rows.filter((row): row is Record<string, unknown> & Edge => typeof row.source_id === "string" && typeof row.target_id === "string").map(row => ({ source_id: row.source_id, target_id: row.target_id, relation: typeof row.relation === "string" ? row.relation : undefined })).slice(0, 120);
}

function NumericTable({ values }: { values: Point[] }) {
  return <div className="g8-table-scroll"><table><caption>Governed values used by this projection</caption><thead><tr><th>Coordinate</th><th>Value</th></tr></thead><tbody>{values.map(point => <tr key={`${point.label}:${point.value}`}><th>{point.label}</th><td>{point.value}</td></tr>)}</tbody></table></div>;
}

export default function ProjectionDataRenderer({ data }: { data: WorkspaceProjectionData }) {
  const values = points(data);
  const graph = edges(data);
  if ((data.projection.kind === "NETWORK" || data.projection.kind === "HIERARCHY") && graph.length) {
    const nodes = [...new Set(graph.flatMap(edge => [edge.source_id, edge.target_id]))].slice(0, 40);
    return <div className="g8-projection-result"><h4>{data.projection.label} · {data.data_state}</h4><p>Explicit directed connectivity only · authority effect: {data.authority_effect}.</p><div className="g8-projection-chart" role="img" aria-label={`${data.projection.label} for the exact selected context`}><svg viewBox="0 0 720 280" preserveAspectRatio="none">{graph.map((edge, index) => { const source = nodes.indexOf(edge.source_id); const target = nodes.indexOf(edge.target_id); const x1 = 30 + (source % 8) * 90; const y1 = 30 + Math.floor(source / 8) * 48; const x2 = 30 + (target % 8) * 90; const y2 = 30 + Math.floor(target / 8) * 48; return <line key={`${edge.source_id}:${edge.target_id}:${index}`} x1={x1} y1={y1} x2={x2} y2={y2} stroke="currentColor" opacity=".5" />; })}{nodes.map((node, index) => <g key={node}><circle cx={30 + (index % 8) * 90} cy={30 + Math.floor(index / 8) * 48} r="8" /><text x={42 + (index % 8) * 90} y={34 + Math.floor(index / 8) * 48} fontSize="9">{node.slice(0, 12)}</text></g>)}</svg></div><div className="g8-table-scroll"><table><caption>Explicit edges returned by the governed connection service</caption><thead><tr><th>Source</th><th>Relation</th><th>Target</th></tr></thead><tbody>{graph.map((edge, index) => <tr key={`${edge.source_id}:${edge.target_id}:${index}`}><td>{edge.source_id}</td><td>{edge.relation ?? "—"}</td><td>{edge.target_id}</td></tr>)}</tbody></table></div></div>;
  }
  if (!values.length) return <p role="status">This exact projection returned no numeric governed rows; no visual has been inferred.</p>;
  const maximum = Math.max(...values.map(point => Math.abs(point.value)), 1);
  const isChart = data.projection.kind === "CHART" || data.projection.kind === "WATERFALL";
  return <div className="g8-projection-result"><h4>{data.projection.label} · {data.data_state}</h4><p>Read-only projection · authority effect: {data.authority_effect} · synchronization: {data.projection.synchronization_group}</p>{data.projection.kind === "KPI" && <div className="g8-facts"><div><strong>{values.length}</strong><small>Governed rows</small></div><div><strong>{values.reduce((sum, point) => sum + point.value, 0).toFixed(2)}</strong><small>Deterministic total</small></div></div>}{isChart && <div className="g8-projection-chart" role="img" aria-label={`${data.projection.label} for the exact selected context`}><svg viewBox="0 0 720 240" preserveAspectRatio="none"><line x1="16" y1="220" x2="704" y2="220" stroke="currentColor" opacity=".35" />{values.map((point, index) => { const width = Math.max(8, 680 / values.length - 6); const height = Math.max(2, Math.abs(point.value) / maximum * 180); const x = 20 + index * (680 / values.length); const y = point.value < 0 ? 220 : 220 - height; return <rect key={`${point.label}:${index}`} x={x} y={y} width={width} height={height} rx="3" data-value={point.value} />; })}</svg></div>}{data.projection.kind !== "KPI" && <NumericTable values={values} />}</div>;
}
