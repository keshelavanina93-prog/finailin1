"use client";

import { useState } from "react";
import type { CanonicalResource } from "@finai/contracts";
export type OntologyConnection = { id: string; source: string; target: string; label: string; state: string; target_version: string | null };
export type OntologySourceConnection = { receipt_id: string; source_sha256: string; target: string; target_version: string; label: string; binding_state: string };
export default function OntologyConnections({ nodes, connections, sourceConnections, onInspect }: { nodes: CanonicalResource[]; connections: OntologyConnection[]; sourceConnections: OntologySourceConnection[]; onInspect: (id: string) => void }) {
  const [focus, setFocus] = useState("");
  const [search, setSearch] = useState("");
  const objects = nodes.filter(node => !["SchemaDefinition", "SemanticContract", "LinkType", "Relationship"].includes(node.object_type));
  const current = objects.find(node => node.resource_id === focus) ?? objects.find(node => node.object_type === "LegalEntity") ?? objects[0];
  const lookup = new Map(objects.map(node => [node.resource_id, node]));
  const matches = objects.filter(node => `${node.display_name} ${node.object_type}`.toLowerCase().includes(search.toLowerCase()));
  const neighbors = (incoming: boolean) => connections.filter(edge => (incoming ? edge.target : edge.source) === current?.resource_id && lookup.has(incoming ? edge.source : edge.target));
  function side(incoming: boolean) {
    const edges = neighbors(incoming);
    return <div className="ontology-neighbors"><h4>{incoming ? "Connected from" : "Connected to"}</h4>{edges.slice(0, 30).map(edge => { const neighbor = lookup.get(incoming ? edge.source : edge.target)!; return <div className="ontology-edge" key={edge.id}><span>{edge.label.replaceAll("_", " ")}</span><button className="quiet" onClick={() => setFocus(neighbor.resource_id)}><small>{neighbor.object_type}</small><strong>{neighbor.display_name}</strong></button>{edge.state === "PINNED_PRIOR_VERSION" && <p className="warning">Uses an earlier version. Review the dependency before recalculation.</p>}</div>; })}{edges.length > 30 && <p>Showing 30 of {edges.length} connections.</p>}{!edges.length && <p className="muted">No connections in this authorized graph.</p>}</div>;
  }
  const evidence = sourceConnections.filter(edge => edge.target === current?.resource_id);
  return <section aria-label="Live ontology connections"><label>Find an object<input type="search" placeholder="Company, account, product or report" value={search} onChange={event => setSearch(event.target.value)} /></label>{search && <div className="ontology-match-list">{matches.slice(0, 20).map(node => <button className="quiet" key={node.resource_id} onClick={() => { setFocus(node.resource_id); setSearch(""); }}>{node.display_name}</button>)}{!matches.length && <p>No matching objects.</p>}</div>}
    {current ? <div className="ontology-live-grid">{side(true)}<article className="ontology-focus"><small>{current.object_type}</small><h3>{current.display_name}</h3><p>{current.evidence_class === "REFERENCE_TEMPLATE" ? "Reference example" : "Accepted resource"}</p><button onClick={() => onInspect(current.resource_id)}>Open properties & history</button><p className="muted">Select a connected object to follow its relationships.</p><details><summary>Version identity</summary><small>{current.version_id}</small></details></article>{side(false)}</div> : <p>No accepted objects yet. New source evidence must resolve to reviewed identities before creating business relationships.</p>}
    {current && <div><h4>Connected source evidence · {evidence.length}</h4><p className="muted">Connections appear from retained canonical bindings in the latest 50 uploads. Binding alone does not approve financial amounts.</p>{evidence.map((edge, index) => <details key={`${edge.receipt_id}:${index}`}><summary>{edge.label.replaceAll("_", " ")} · {edge.source_sha256.slice(0, 12)}…</summary><p>Source receipt: {edge.receipt_id}</p><p>Pinned object version: {edge.target_version}</p>{edge.target_version !== current.version_id && <p className="warning">Source uses an earlier object version.</p>}</details>)}</div>}
  </section>;
}
