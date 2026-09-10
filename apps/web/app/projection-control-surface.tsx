"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  ProjectionCatalog,
  ProjectionSelectionEvent,
  WorkspaceProjectionData,
  WorkspaceSelection,
  WorkspaceSelectionResponse,
} from "@finai/contracts";
import ProjectionDataRenderer from "./projection-data-renderer";

type ProjectionDataById = Record<string, WorkspaceProjectionData>;

export default function ProjectionControlSurface({
  token,
  companyId,
  initialWorkspace,
}: {
  token: string;
  companyId: string;
  initialWorkspace?: WorkspaceSelection["workspace"];
}) {
  const [catalog, setCatalog] = useState<ProjectionCatalog | null>(null);
  const [selection, setSelection] = useState<WorkspaceSelection>(() => {
    if (typeof window !== "undefined") {
      try {
        const stored = JSON.parse(
          window.sessionStorage.getItem("g8-workspace-selection") ?? "null",
        ) as Partial<WorkspaceSelection> | null;
        if (stored?.company_id === companyId) {
          return {
            ...stored,
            company_id: companyId,
            workspace: initialWorkspace ?? stored.workspace ?? "BRIDGE_FIRST",
          } as WorkspaceSelection;
        }
      } catch {
        /* A corrupt browser snapshot cannot replace the explicit company context. */
      }
    }
    return { company_id: companyId, workspace: initialWorkspace ?? "BRIDGE_FIRST" };
  });
  const [validated, setValidated] = useState<WorkspaceSelectionResponse | null>(null);
  const [error, setError] = useState("");
  const [dataByProjection, setDataByProjection] = useState<ProjectionDataById>({});
  const loadedProjectionIds = useRef<Set<string>>(new Set());
  const selectionRevision = useRef(0);

  useEffect(() => () => { selectionRevision.current++; }, [token, companyId]);

  function updateSelection(next: WorkspaceSelection) {
    selectionRevision.current++;
    setSelection(next);
    setValidated(null);
    setDataByProjection({});
  }

  useEffect(() => {
    window.sessionStorage.setItem("g8-workspace-selection", JSON.stringify(selection));
  }, [selection]);

  useEffect(() => {
    const receiveSelection = (event: Event) => {
      const detail = (event as CustomEvent<ProjectionSelectionEvent>).detail;
      if (
        !detail ||
        detail.contract !== "workspace-selection-event/1" ||
        detail.selection?.company_id !== companyId
      ) {
        return;
      }
      selectionRevision.current++;
      setSelection(current => ({ ...current, ...detail.selection, company_id: companyId }));
      setValidated(null);
      setDataByProjection({});
    };
    window.addEventListener("g8-workspace-selection", receiveSelection);
    return () => window.removeEventListener("g8-workspace-selection", receiveSelection);
  }, [companyId]);

  useEffect(() => {
    const controller = new AbortController();
    void fetch("/api/workspace/projections/catalog", {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
      signal: controller.signal,
    })
      .then(async response => {
        const result = (await response.json()) as ProjectionCatalog & { detail?: string };
        if (!response.ok) throw new Error(result.detail ?? "Projection registry unavailable");
        setCatalog(result);
      })
      .catch(failure => {
        if (!controller.signal.aborted) {
          setError(failure instanceof Error ? failure.message : "Projection registry unavailable");
        }
      });
    return () => controller.abort();
  }, [token]);

  const fetchProjectionData = useCallback(async function fetchProjectionData(
    projectionId: string,
    requestedSelection: WorkspaceSelection,
    signal?: AbortSignal,
  ): Promise<WorkspaceProjectionData> {
    const response = await fetch("/api/workspace/projections/data", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ projection_id: projectionId, selection: requestedSelection }),
      cache: "no-store",
      signal,
    });
    const result = (await response.json()) as WorkspaceProjectionData & { detail?: string };
    if (!response.ok) throw new Error(result.detail ?? `${projectionId}: projection data unavailable`);
    return result;
  }, [token]);

  useEffect(() => {
    const projectionIds = [...loadedProjectionIds.current];
    if (!projectionIds.length) return undefined;
    const controller = new AbortController();
    const revision = selectionRevision.current;
    void Promise.allSettled(
      projectionIds.map(async projectionId => [
        projectionId,
        await fetchProjectionData(projectionId, selection, controller.signal),
      ] as const),
    )
      .then(results => {
        if (controller.signal.aborted || revision !== selectionRevision.current) return;
        const successful = results.flatMap(result => result.status === "fulfilled" ? [result.value] : []);
        setDataByProjection(Object.fromEntries(successful));
        const failures = results.flatMap((result, index) => result.status === "rejected" ? [projectionIds[index]] : []);
        setError(failures.length ? `Unavailable for this selection: ${failures.join(", ")}` : "");
      })
      .catch(failure => {
        if (!controller.signal.aborted) {
          setError(failure instanceof Error ? failure.message : "Synchronized projections unavailable");
        }
      });
    return () => controller.abort();
  }, [fetchProjectionData, selection]);

  async function validate() {
    const revision = selectionRevision.current;
    setError("");
    try {
      const response = await fetch("/api/workspace/projections/selection", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify(selection),
        cache: "no-store",
      });
      const result = (await response.json()) as WorkspaceSelectionResponse & { detail?: string };
      if (!response.ok) throw new Error(result.detail ?? "Selection refused");
      if (revision === selectionRevision.current) setValidated(result);
    } catch (failure) {
      if (revision === selectionRevision.current) setError(failure instanceof Error ? failure.message : "Selection refused");
    }
  }

  async function loadProjection(projectionId: string) {
    const revision = selectionRevision.current;
    setError("");
    try {
      const result = await fetchProjectionData(projectionId, selection);
      if (revision !== selectionRevision.current) return;
      loadedProjectionIds.current.add(projectionId);
      setDataByProjection(current => ({ ...current, [projectionId]: result }));
    } catch (failure) {
      if (revision === selectionRevision.current) setError(failure instanceof Error ? failure.message : "Projection data unavailable");
    }
  }

  async function loadSynchronizedCanvas() {
    if (!validated) return;
    const revision = selectionRevision.current;
    setError("");
    const projectionIds = validated.eligible_projections.map(item => item.projection_id);
    loadedProjectionIds.current = new Set(projectionIds);
    const results = await Promise.allSettled(
      projectionIds.map(projectionId => fetchProjectionData(projectionId, selection)),
    );
    if (revision !== selectionRevision.current) return;
    const successful: Array<readonly [string, WorkspaceProjectionData]> = [];
    const failures: string[] = [];
    results.forEach((result, index) => {
      const projectionId = projectionIds[index];
      if (result.status === "fulfilled") successful.push([projectionId, result.value]);
      else failures.push(`${projectionId}: ${result.reason instanceof Error ? result.reason.message : "unavailable"}`);
    });
    setDataByProjection(Object.fromEntries(successful));
    if (failures.length) setError(`Some eligible projections were unavailable: ${failures.join("; ")}`);
  }

  const loadedData = Object.values(dataByProjection);

  return (
    <section className="g8-panel" aria-label="Cross-projection control surface">
      <div className="g8-panel-heading">
        <div>
          <p className="overline">PROJECTION FABRIC · EXACT CONTEXT</p>
          <h3>One selection, many governed views</h3>
          <p>
            Operations, planning, evidence, lineage, bridge and NYX projections inherit this
            company-scoped session selection. This control validates scope without changing authority.
          </p>
        </div>
        <span className="g8-badge">{validated?.scope_state ?? "NOT VALIDATED"}</span>
      </div>
      <div className="g8-actionbar">
        <label>Workspace<select value={selection.workspace ?? ""} onChange={event => updateSelection({ ...selection, workspace: (event.target.value || null) as WorkspaceSelection["workspace"] })}><option value="">All workspaces</option><option value="TABLE_FIRST">Table first</option><option value="GRAPH_FIRST">Graph first</option><option value="TIMELINE_FIRST">Timeline first</option><option value="BRIDGE_FIRST">Bridge first</option><option value="COMMAND_EXECUTIVE">Command / executive</option><option value="REPORT">Report</option></select></label>
        <label>Selected object<input value={selection.selected_object_id ?? ""} onChange={event => updateSelection({ ...selection, selected_object_id: event.target.value || null })} placeholder="Object / workflow / resource ID" /></label>
        <label>Facility<input value={selection.facility_id ?? ""} onChange={event => updateSelection({ ...selection, facility_id: event.target.value || null })} placeholder="Optional facility" /></label>
        <label>Tank<input value={selection.tank_id ?? ""} onChange={event => updateSelection({ ...selection, tank_id: event.target.value || null })} placeholder="Optional tank" /></label>
        <label>Product<input value={selection.product_id ?? ""} onChange={event => updateSelection({ ...selection, product_id: event.target.value || null })} placeholder="Optional product" /></label>
        <label>Station<input value={selection.station_id ?? ""} onChange={event => updateSelection({ ...selection, station_id: event.target.value || null })} placeholder="Optional station" /></label>
        <label>Period<input value={selection.period ?? ""} onChange={event => updateSelection({ ...selection, period: event.target.value || null })} placeholder="YYYY-MM" /></label>
        <label>Scenario<input value={selection.scenario_id ?? ""} onChange={event => updateSelection({ ...selection, scenario_id: event.target.value || null })} placeholder="Scenario ID" /></label>
        <label>Version<input value={selection.version_id ?? ""} onChange={event => updateSelection({ ...selection, version_id: event.target.value || null })} placeholder="Version ID" /></label>
        <label>Baseline<input value={selection.comparison_baseline ?? ""} onChange={event => updateSelection({ ...selection, comparison_baseline: event.target.value || null })} placeholder="Comparison baseline" /></label>
        <label>Replay as of<input value={selection.replay_as_of ?? ""} onChange={event => updateSelection({ ...selection, replay_as_of: event.target.value || null })} placeholder="Optional known time" /></label>
        <button onClick={() => void validate()}>Validate exact selection</button>
        <button disabled={!validated?.eligible_projections.length} onClick={() => void loadSynchronizedCanvas()}>Load synchronized canvas</button>
      </div>
      {error && <p className="g8-inline-error" role="alert">{error}</p>}
      {validated && <p role="status">Validated company scope: <strong>{validated.selection.company_id}</strong>. {validated.eligible_projections.length} projections are eligible for this exact context. No authority or business effect was changed.</p>}
      {catalog && <div className="g8-table-scroll"><table><caption>Server-owned projection registry · all cards synchronize through WORKSPACE_SELECTION</caption><thead><tr><th>Projection</th><th>Kind</th><th>Chart</th><th>Workspace</th><th>Status</th><th>Contract</th><th>Data</th></tr></thead><tbody>{catalog.projections.map(item => <tr key={item.projection_id}><th>{item.label}</th><td>{item.kind}</td><td>{item.chart_type ?? "—"}</td><td>{item.workspaces.join(" · ")}</td><td>{item.status}</td><td>{item.backend_contracts.join(" · ")}</td><td><button disabled={!validated?.eligible_projections.some(candidate => candidate.projection_id === item.projection_id)} onClick={() => void loadProjection(item.projection_id)}>Load</button></td></tr>)}</tbody></table></div>}
      {loadedData.length > 0 && <div className="g8-projection-canvas" aria-label="Synchronized governed projection canvas">{loadedData.map(item => <article className="g8-panel" key={item.projection.projection_id}><ProjectionDataRenderer data={item} token={token} /></article>)}</div>}
    </section>
  );
}
