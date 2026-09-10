"use client";

/* eslint-disable @next/next/no-img-element -- verified retained evidence is rendered from an authenticated local blob. */
import { useEffect, useState } from "react";
import type { ProjectionSelectionEvent, WorkspaceProjectionData, WorkspaceSelection } from "@finai/contracts";

type Point = { label: string; value: number; row_id?: string };

type Edge = { source_id: string; target_id: string; relation?: string };

type Feature = { geometry?: { type?: string; coordinates?: unknown }; properties?: { resource?: { display_name?: string; object_type?: string } } };

const selectionDimensions = ["facility_id", "tank_id", "product_id", "station_id", "period", "scenario_id", "version_id", "comparison_baseline", "replay_as_of"] as const;

function publishProjectionSelection(data: WorkspaceProjectionData, patch: Partial<WorkspaceSelection>) {
  const sourceRow = data.normalized_rows?.find(row => row.row_id === patch.selected_object_id);
  const rowSelection = sourceRow ? Object.fromEntries(
    selectionDimensions.flatMap(dimension => {
      const value = sourceRow.coordinates[dimension];
      return value ? [[dimension, value]] : [];
    }),
  ) as Partial<WorkspaceSelection> : {};
  window.dispatchEvent(new CustomEvent<ProjectionSelectionEvent>("g8-workspace-selection", {
    detail: {
      contract: "workspace-selection-event/1",
      source_projection_id: data.projection.projection_id,
      source_row_id: patch.selected_object_id,
      selection: { ...rowSelection, ...patch, company_id: data.selection.company_id },
    },
  }));
}

function points(data: WorkspaceProjectionData): Point[] {
  const sourceRows = data.normalized_rows?.map(row => ({ ...row.labels, ...row.measures, ...row.coordinates })) ?? data.rows;
  return sourceRows.flatMap((row, index) => {
    const attributes = typeof row.attributes === "object" && row.attributes !== null ? row.attributes as Record<string, unknown> : {};
    const candidate = row.delta ?? row.amount ?? row.scenario_b ?? row.value ?? attributes.amount;
    const value = typeof candidate === "number" ? candidate : Number(candidate);
    return Number.isFinite(value) ? [{ label: String(row.label ?? row.period_id ?? attributes.period_id ?? row.dimension ?? `Row ${index + 1}`), value, row_id: typeof row.row_id === "string" ? row.row_id : undefined }] : [];
  }).slice(0, 24);
}

function edges(data: WorkspaceProjectionData): Edge[] {
  return data.rows.filter((row): row is Record<string, unknown> & Edge => typeof row.source_id === "string" && typeof row.target_id === "string").map(row => ({ source_id: row.source_id, target_id: row.target_id, relation: typeof row.relation === "string" ? row.relation : undefined })).slice(0, 120);
}

function features(data: WorkspaceProjectionData): Feature[] {
  return data.rows.filter((row): row is Feature => typeof row.geometry === "object" && row.geometry !== null).slice(0, 100);
}

function NumericTable({ data, values }: { data: WorkspaceProjectionData; values: Point[] }) {
  return <div className="g8-table-scroll"><table><caption>Governed values used by this projection</caption><thead><tr><th>Coordinate</th><th>Value</th></tr></thead><tbody>{values.map(point => <tr key={`${point.label}:${point.value}`} onClick={() => point.row_id && publishProjectionSelection(data, { selected_object_id: point.row_id })}><th>{point.label}</th><td>{point.value}</td></tr>)}</tbody></table></div>;
}

function ChartFigure({ data, values }: { data: WorkspaceProjectionData; values: Point[] }) {
  const chartType = data.projection.chart_type ?? "WATERFALL";
  const maximum = Math.max(...values.map(point => Math.abs(point.value)), 1);
  const coordinates = values.map((point, index) => ({ point, x: 24 + index * (672 / Math.max(values.length - 1, 1)), y: 220 - (point.value / maximum) * 180 }));
  const line = coordinates.map(item => `${item.x},${item.y}`).join(" ");
  if (chartType === "GANTT") {
    const intervals = (data.normalized_rows ?? []).filter(row => row.interval_start && row.interval_end).map(row => ({ row_id: row.row_id, label: row.labels.label ?? row.labels.period_id ?? row.row_id, start: Date.parse(row.interval_start as string), end: Date.parse(row.interval_end as string) })).filter(row => Number.isFinite(row.start) && Number.isFinite(row.end) && row.end >= row.start).slice(0, 24);
    if (!intervals.length) return <div role="status">Gantt requires governed start and end interval coordinates; the numeric audit table remains below.</div>;
    const minimum = Math.min(...intervals.map(item => item.start)), maximumDate = Math.max(...intervals.map(item => item.end)), span = Math.max(maximumDate - minimum, 1);
    return <svg viewBox={`0 0 720 ${Math.max(120, intervals.length * 28)}`} preserveAspectRatio="none" aria-label="Gantt timeline projection">{intervals.map((item, index) => { const x = 150 + (item.start - minimum) / span * 540; const width = Math.max(4, (item.end - item.start) / span * 540); const y = 16 + index * 28; return <g key={`${item.label}:${item.start}`}><text x="4" y={y + 12} fontSize="10">{item.label.slice(0, 22)}</text><rect x={x} y={y} width={width} height="16" rx="3" data-start={item.start} data-end={item.end} onClick={() => publishProjectionSelection(data, { selected_object_id: item.row_id })}><title>{item.label}: {new Date(item.start).toISOString()} — {new Date(item.end).toISOString()}</title></rect></g>; })}</svg>;
  }
  if (["DOT", "SCATTER", "BUBBLE"].includes(chartType)) return <svg viewBox="0 0 720 240" preserveAspectRatio="none" aria-label={`${chartType} projection`}><line x1="16" y1="220" x2="704" y2="220" stroke="currentColor" opacity=".35" />{coordinates.map(({ point, x, y }, index) => <circle key={`${point.label}:${index}`} cx={x} cy={y} r={chartType === "BUBBLE" ? Math.max(5, Math.min(18, Math.abs(point.value) / maximum * 18)) : 5} data-value={point.value} onClick={() => publishProjectionSelection(data, { selected_object_id: point.row_id ?? null })}><title>{point.label}: {point.value}</title></circle>)}</svg>;
  if (["LINE", "AREA"].includes(chartType)) return <svg viewBox="0 0 720 240" preserveAspectRatio="none" aria-label={`${chartType} projection`}><line x1="16" y1="220" x2="704" y2="220" stroke="currentColor" opacity=".35" />{chartType === "AREA" && <polygon points={`16,220 ${line} 704,220`} opacity=".15" />}{chartType === "LINE" ? <polyline points={line} fill="none" stroke="currentColor" strokeWidth="3" /> : <polyline points={line} fill="none" stroke="currentColor" strokeWidth="2" />}{coordinates.map(({ point, x, y }, index) => <circle key={`${point.label}:${index}`} cx={x} cy={y} r="3" onClick={() => publishProjectionSelection(data, { selected_object_id: point.row_id ?? null })}><title>{point.label}: {point.value}</title></circle>)}</svg>;
  if (chartType === "WATERFALL") {
    const cumulative = values.reduce<number[]>((result, point) => [...result, (result.at(-1) ?? 0) + point.value], []);
    const extent = Math.max(...[0, ...cumulative].map(value => Math.abs(value)), 1);
    return <svg viewBox="0 0 720 260" preserveAspectRatio="none" aria-label="Waterfall projection"><line x1="16" y1="220" x2="704" y2="220" stroke="currentColor" opacity=".35" />{values.map((point, index) => { const previous = index ? cumulative[index - 1] : 0; const next = cumulative[index]; const scale = 180 / extent; const y = 220 - Math.max(previous, next) * scale; const height = Math.max(2, Math.abs(point.value) * scale); const x = 20 + index * (680 / values.length); return <g key={`${point.label}:${index}`} onClick={() => publishProjectionSelection(data, { selected_object_id: point.row_id ?? null })}><rect x={x} y={y} width={Math.max(8, 680 / values.length - 6)} height={height} rx="3" data-delta={point.value} /><line x1={x + Math.max(8, 680 / values.length - 6)} y1={220 - next * scale} x2={x + 680 / values.length + 2} y2={220 - next * scale} stroke="currentColor" opacity=".35" /><title>{point.label}: change {point.value}; cumulative {next}</title></g>; })}<text x="18" y="250" fontSize="10">Sequential governed changes · cumulative total {cumulative.at(-1) ?? 0}</text></svg>;
  }
  if (chartType === "COMBINATION") {
    const secondary = values.map((_, index) => { const row = data.normalized_rows?.[index]; const raw = row?.measures.scenario_b ?? data.rows[index]?.scenario_b; const value = Number(raw); return Number.isFinite(value) ? value : null; });
    const secondaryValues = secondary.filter((value): value is number => value !== null);
    if (!secondaryValues.length) return <div role="status">Combination projection requires a second governed numeric series; the primary series remains below.</div>;
    const secondaryMaximum = Math.max(...secondaryValues.map(value => Math.abs(value)), 1);
    const secondaryCoordinates = secondary.map((value, index) => value === null ? null : { x: 24 + index * (672 / Math.max(values.length - 1, 1)), y: 220 - (value / secondaryMaximum) * 180 }).filter((value): value is { x: number; y: number } => value !== null);
    return <svg viewBox="0 0 720 240" preserveAspectRatio="none" aria-label="Combination projection"><line x1="16" y1="220" x2="704" y2="220" stroke="currentColor" opacity=".35" />{values.map((point, index) => { const width = Math.max(8, 680 / values.length - 6); const height = Math.max(2, Math.abs(point.value) / maximum * 180); const x = 20 + index * (680 / values.length); return <rect key={`${point.label}:${index}`} x={x} y={point.value < 0 ? 220 : 220 - height} width={width} height={height} rx="3" onClick={() => publishProjectionSelection(data, { selected_object_id: point.row_id ?? null })}><title>{point.label}: primary {point.value}</title></rect>; })}<polyline points={secondaryCoordinates.map(point => `${point.x},${point.y}`).join(" ")} fill="none" stroke="currentColor" strokeWidth="3" strokeDasharray="6 3" /><text x="18" y="238" fontSize="10">Bars: primary series · dashed line: scenario_b series</text></svg>;
  }
  if (chartType === "PIE") {
    const positive = values.every(point => point.value >= 0), total = values.reduce((sum, point) => sum + point.value, 0);
    if (!positive || total <= 0) return <div role="status">Pie projection requires non-negative governed values; the numeric audit table remains below.</div>;
     return <svg viewBox="0 0 240 240" aria-label="Pie projection">{values.map((point, index) => { const portion = point.value / total * 100; const offset = values.slice(0, index).reduce((sum, prior) => sum + prior.value / total * 100, 0); const dash = `${portion} ${100 - portion}`; return <circle key={`${point.label}:${index}`} cx="120" cy="120" r="80" fill="none" stroke="currentColor" strokeWidth="40" strokeDasharray={dash} strokeDashoffset={-offset} pathLength="100" onClick={() => publishProjectionSelection(data, { selected_object_id: point.row_id ?? null })}><title>{point.label}: {point.value}</title></circle>; })}</svg>;
  }
  return <svg viewBox="0 0 720 240" preserveAspectRatio="none" aria-label={`${chartType} projection`}><line x1="16" y1="220" x2="704" y2="220" stroke="currentColor" opacity=".35" />{values.map((point, index) => { const width = Math.max(8, 680 / values.length - 6); const height = Math.max(2, Math.abs(point.value) / maximum * 180); const x = 20 + index * (680 / values.length); const y = point.value < 0 ? 220 : 220 - height; return <rect key={`${point.label}:${index}`} x={x} y={y} width={width} height={height} rx="3" data-value={point.value} onClick={() => publishProjectionSelection(data, { selected_object_id: point.row_id ?? null })}><title>{point.label}: {point.value}</title></rect>; })}</svg>;
}

export default function ProjectionDataRenderer({ data, token }: { data: WorkspaceProjectionData; token?: string }) {
  const [imageSrc, setImageSrc] = useState<string | null>(null);
  const [imageKey, setImageKey] = useState<string | null>(null);
  const [imageError, setImageError] = useState("");
  useEffect(() => {
    let objectUrl: string | null = null;
    if (data.projection.kind !== "IMAGE" || !data.media) return () => undefined;
    const controller = new AbortController();
    void fetch(data.media.data_url, { cache: "no-store", signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error("Retained image unavailable in the exact source scope");
        const bytes = await response.arrayBuffer();
        const digest = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), value => value.toString(16).padStart(2, "0")).join("");
        if (digest !== data.media?.sha256) throw new Error("Image integrity check failed; display withheld");
        objectUrl = URL.createObjectURL(new Blob([bytes], { type: data.media?.media_type }));
        setImageSrc(objectUrl);
        setImageKey(data.media?.data_url ?? null);
      })
      .catch(error => { if (!controller.signal.aborted) setImageError(error instanceof Error ? error.message : "Retained image unavailable"); });
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [data.media, data.projection.kind, token]);
  const values = points(data);
  const graph = edges(data);
  const mapFeatures = features(data);
  if (data.projection.kind === "MAP" && mapFeatures.length) {
    const pointsForMap = mapFeatures.flatMap(feature => {
      const coordinates = feature.geometry?.coordinates;
      return feature.geometry?.type === "Point" && Array.isArray(coordinates) && typeof coordinates[0] === "number" && typeof coordinates[1] === "number" ? [{ x: coordinates[0], y: coordinates[1], label: feature.properties?.resource?.display_name ?? "Accepted asset" }] : [];
    });
    if (pointsForMap.length) {
      const xs = pointsForMap.map(point => point.x), ys = pointsForMap.map(point => point.y), minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
      return <div className="g8-projection-result"><h4>{data.projection.label} · {data.data_state}</h4><p>Accepted geometry only · authority effect: {data.authority_effect}.</p><div className="g8-projection-chart" role="img" aria-label="Accepted operational assets for the exact selected context"><svg viewBox="0 0 720 280" preserveAspectRatio="none">{pointsForMap.map((point, index) => { const x = 30 + ((point.x - minX) / (maxX - minX || 1)) * 660; const y = 250 - ((point.y - minY) / (maxY - minY || 1)) * 220; return <g key={`${point.label}:${index}`} onClick={() => publishProjectionSelection(data, { selected_object_id: (data.normalized_rows ?? [])[index]?.row_id ?? null })}><circle cx={x} cy={y} r="5" /><title>{point.label}</title></g>; })}</svg></div><p>{pointsForMap.length} accepted point geometries returned. Non-point and unmapped assets remain in the operations map&apos;s governed evidence view.</p></div>;
    }
  }
  if (data.projection.kind === "ACTION" && ["CONTEXT_ONLY", "ACCEPTED_CANONICAL"].includes(data.data_state)) {
    return <div className="g8-projection-result"><h4>{data.projection.label} · governed capability</h4><p>Read-only action status for the exact selected scope · authority effect: {data.authority_effect}.</p><dl>{data.rows.filter(row => typeof row.field === "string").map(row => <div key={String(row.field)}><dt>{String(row.label ?? row.field)}</dt><dd>{String(row.value ?? "Not recorded")}</dd></div>)}</dl><p role="status">This projection cannot execute an action. Use the governed workflow workbench for maker/checker approval, adapter execution, and external readback.</p></div>;
  }
  if (data.projection.kind === "IMAGE") {
    if (imageSrc && imageKey === data.media?.data_url) return <div className="g8-projection-result"><h4>{data.projection.label} · {data.data_state}</h4><figure>{/* The source is a verified local blob URL, not an external image host. */}<img src={imageSrc} alt="Retained evidence source" style={{ maxWidth: "100%", maxHeight: 520 }} /><figcaption>Integrity-verified retained evidence · {data.media?.media_type} · SHA-256 {data.media?.sha256}</figcaption></figure><p role="status">Image is displayed as retained evidence only. It cannot change canonical facts or authority.</p></div>;
    return <div className="g8-projection-result"><h4>{data.projection.label}</h4><p role="status">{imageError || "Loading integrity-verified retained image…"}</p><strong>{data.data_state}</strong></div>;
  }
  if (data.projection.kind === "ACTION") {
    return <div className="g8-projection-result"><h4>{data.projection.label}</h4><p role="status">This projection is registered for the exact context, but its authoritative payload is not available in this read-only data contract. No input mutation, image substitution, or business action was performed.</p><strong>{data.data_state}</strong></div>;
  }
  if (data.projection.kind === "TEXT") {
    const explanation = data.rows.find(row => row.field === "answer");
    if (explanation) return <div className="g8-projection-result"><h4>{data.projection.label} · {data.data_state}</h4><p>{String(explanation.value)}</p><dl>{data.rows.filter(row => row.field !== "answer").map(row => <div key={String(row.field)}><dt>{String(row.label ?? row.field)}</dt><dd>{String(row.value ?? "Not recorded")}</dd></div>)}</dl><p role="status">Citation-bound explanation only. This response does not establish financial authority or permission to act.</p></div>;
    return <div className="g8-projection-result"><h4>{data.projection.label}</h4><p>Governed narrative projection for the selected company and object.</p><dl><dt>Data state</dt><dd>{data.data_state}</dd><dt>Authority effect</dt><dd>{data.authority_effect}</dd><dt>Synchronization</dt><dd>{data.projection.synchronization_group}</dd></dl><p>NYX narrative generation remains citation-bound to the returned evidence and is not inferred by this renderer.</p></div>;
  }
  if (data.projection.kind === "FIELD") {
    const fields = data.rows.filter(row => typeof row.field === "string");
    return <div className="g8-projection-result"><h4>{data.projection.label} · {data.data_state}</h4><p>Exact selection context only · authority effect: {data.authority_effect}.</p><dl>{fields.map(row => <div key={String(row.field)}><dt>{String(row.label ?? row.field)}</dt><dd>{String(row.value ?? "Not recorded")}</dd></div>)}</dl><p role="status">This card displays governed context. Editing canonical facts requires the owning review workflow.</p></div>;
  }
  if ((data.projection.kind === "NETWORK" || data.projection.kind === "HIERARCHY") && graph.length) {
    const nodes = [...new Set(graph.flatMap(edge => [edge.source_id, edge.target_id]))].slice(0, 40);
    return <div className="g8-projection-result"><h4>{data.projection.label} · {data.data_state}</h4><p>Explicit directed connectivity only · authority effect: {data.authority_effect}.</p><div className="g8-projection-chart" role="img" aria-label={`${data.projection.label} for the exact selected context`}><svg viewBox="0 0 720 280" preserveAspectRatio="none">{graph.map((edge, index) => { const source = nodes.indexOf(edge.source_id); const target = nodes.indexOf(edge.target_id); const x1 = 30 + (source % 8) * 90; const y1 = 30 + Math.floor(source / 8) * 48; const x2 = 30 + (target % 8) * 90; const y2 = 30 + Math.floor(target / 8) * 48; return <line key={`${edge.source_id}:${edge.target_id}:${index}`} x1={x1} y1={y1} x2={x2} y2={y2} stroke="currentColor" opacity=".5" />; })}{nodes.map((node, index) => <g key={node} onClick={() => publishProjectionSelection(data, { selected_object_id: node })}><circle cx={30 + (index % 8) * 90} cy={30 + Math.floor(index / 8) * 48} r="8" /><text x={42 + (index % 8) * 90} y={34 + Math.floor(index / 8) * 48} fontSize="9">{node.slice(0, 12)}</text></g>)}</svg></div><div className="g8-table-scroll"><table><caption>Explicit edges returned by the governed connection service</caption><thead><tr><th>Source</th><th>Relation</th><th>Target</th></tr></thead><tbody>{graph.map((edge, index) => <tr key={`${edge.source_id}:${edge.target_id}:${index}`}><td>{edge.source_id}</td><td>{edge.relation ?? "—"}</td><td>{edge.target_id}</td></tr>)}</tbody></table></div></div>;
  }
  if (!values.length) return <p role="status">This exact projection returned no numeric governed rows; no visual has been inferred.</p>;
  const isChart = data.projection.kind === "CHART" || data.projection.kind === "WATERFALL";
  return <div className="g8-projection-result"><h4>{data.projection.label} · {data.data_state}</h4><p>Read-only projection · authority effect: {data.authority_effect} · synchronization: {data.projection.synchronization_group}</p>{data.projection.kind === "KPI" && <div className="g8-facts"><div><strong>{values.length}</strong><small>Governed rows</small></div><div><strong>{values.reduce((sum, point) => sum + point.value, 0).toFixed(2)}</strong><small>Deterministic total</small></div></div>}{isChart && <div className="g8-projection-chart"><ChartFigure data={data} values={values} /></div>}{data.projection.kind !== "KPI" && <NumericTable data={data} values={values} />}</div>;
}
