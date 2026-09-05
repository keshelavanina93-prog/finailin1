"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import type { CanonicalDetail, CanonicalResource, Principal, ProposalSummary, ResourceMutation, ResourceProposalDetail, SchemaField } from "@finai/contracts";
import IdentityHistory from "./identity-history";
import ProposalImpact, { SchemaChangeDetails } from "./proposal-impact";

const metadata = new Set(["SchemaDefinition", "SemanticContract", "LinkType"]);
const label = (value: string) => value.replaceAll("_", " ").replace(/([a-z])([A-Z])/g, "$1 $2");
const message = (error: unknown) => error instanceof Error ? error.message : "Request failed";
type Draft = { type: string; current?: CanonicalResource; attributes: Record<string, unknown>; name: string };

export default function OntologyWorkspace({ token, principal }: { token: string; principal: Principal }) {
  const [catalog, setCatalog] = useState<CanonicalResource[]>([]);
  const [nodes, setNodes] = useState<CanonicalResource[]>([]);
  const [queue, setQueue] = useState<ProposalSummary[]>([]);
  const [tab, setTab] = useState<"graph" | "resources" | "review" | "registry">("graph");
  const [detail, setDetail] = useState<CanonicalDetail | null>(null);
  const [proposal, setProposal] = useState<ResourceProposalDetail | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [kind, setKind] = useState("");
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(true);
  const [effectiveFrom] = useState(() => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16));
  const [bounded, setBounded] = useState(false);
  const [revision, setRevision] = useState(0);
  const selection = useRef(0);
  const canPropose = principal.permissions.includes("ontology_propose");
  const canReview = principal.permissions.includes("ontology_review");
  const admin = principal.permissions.includes("ontology_admin");
  const api = useCallback(async <T,>(path: string, body?: unknown): Promise<T> => {
    const response = await fetch(`/api/ontology/${path}`, { method: body === undefined ? "GET" : "POST", cache: "no-store",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? response.status));
    return data as T;
  }, [token]);
  useEffect(() => {
    let cancelled = false;
    const selectionRef = selection;
    Promise.all([api<CanonicalResource[]>("catalog"), api<{ resources: CanonicalResource[]; bounded: boolean }>("graph"), api<ProposalSummary[]>("proposals")])
      .then(([definitions, graph, proposals]) => { if (!cancelled) { setCatalog(definitions); setNodes(graph.resources); setBounded(graph.bounded); setQueue(proposals); } })
      .catch(error => { if (!cancelled) setError(message(error)); }).finally(() => { if (!cancelled) setBusy(false); });
    return () => { cancelled = true; selectionRef.current++; };
  }, [api, revision]);
  const names = new Map([...catalog, ...nodes].map(node => [node.resource_id, node.display_name]));
  const schemas = catalog.filter(node => node.object_type === "SchemaDefinition");
  const fields = draft ? schemas.find(schema => schema.identity_key === draft.type)?.attributes.fields as Record<string, SchemaField> | undefined : undefined;
  const visible = (tab === "registry" ? catalog : nodes.filter(node => !metadata.has(node.object_type)))
    .filter(node => (!kind || node.object_type === kind) && `${node.display_name} ${node.identity_key}`.toLowerCase().includes(search.toLowerCase()));
  const graphNodes = nodes.filter(node => !metadata.has(node.object_type) && !["Relationship", "Alias", "IdentityResolution", "SemanticBinding", "ContextBinding"].includes(node.object_type));
  const positions = new Map(graphNodes.map((node, index) => [node.resource_id, { x: 24 + index % 3 * 270, y: 30 + Math.floor(index / 3) * 150 }]));

  async function inspect(id: string) {
    const request = ++selection.current; setError("");
    try { const result = await api<CanonicalDetail>(`resources/${id}`); if (selection.current === request) { setDetail(result); setDraft(null); setProposal(null); } }
    catch (error) { if (selection.current === request) setError(message(error)); }
  }
  async function openProposal(id: string) {
    const request = ++selection.current; setError("");
    try { const result = await api<ResourceProposalDetail>(`proposals/${id}`); if (selection.current === request) { setProposal(result); setDetail(null); setDraft(null); } }
    catch (error) { if (selection.current === request) setError(message(error)); }
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!draft) return;
    const data = new FormData(event.currentTarget); setBusy(true); setError("");
    try {
      const attributes: Record<string, unknown> = {};
      if (fields) for (const [name, spec] of Object.entries(fields)) {
        const value = String(data.get(name) ?? "");
        if (!value && !spec.required) continue;
        attributes[name] = spec.kind === "boolean" ? value === "true" : spec.kind === "integer" ? Number(value) : ["money", "quantity"].includes(spec.kind) ? JSON.parse(value) : value;
      } else Object.assign(attributes, JSON.parse(String(data.get("attributes"))));
      let identityKey = draft.current?.identity_key ?? String(data.get("identity_key"));
      if (draft.type === "Alias") {
        const target = nodes.find(node => node.resource_id === attributes.target_id);
        if (!target) throw new Error("Choose a visible target identity");
        const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify([attributes.source_system, target.object_type, attributes.external_id])));
        identityKey = "alias:" + Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, "0")).join("");
      }
      if (draft.type === "IdentityResolution") identityKey = `identity:${attributes.source_id}`;
      if (draft.type === "ContextBinding") {
        const context = await api<{ source_scope_key: string }>("context");
        attributes.source_scope_key = context.source_scope_key; identityKey = `context:${context.source_scope_key}`;
      }
      const mutation: ResourceMutation = { resource_id: draft.current?.resource_id ?? crypto.randomUUID(), expected_version_id: draft.current?.version_id,
        object_type: draft.type, identity_key: identityKey, display_name: String(data.get("display_name")), attributes,
        valid_from: new Date(String(data.get("valid_from"))).toISOString(),
        evidence_class: draft.current?.evidence_class === "PLATFORM_DEFINITION" ? "USER_ASSERTED" : draft.current?.evidence_class ?? "USER_ASSERTED" };
      const result = await api<ResourceProposalDetail>("proposals", { proposal_id: crypto.randomUUID(), title: `${draft.current ? "Update" : "Create"} ${mutation.display_name}`,
        rationale: String(data.get("rationale")), access_entity: draft.current?.access_entity ?? (metadata.has(draft.type) ? "__PLATFORM__" : principal.scope.legal_entity_id), mutations: [mutation] });
      setProposal(result); setDraft(null); setDetail(null); setRevision(value => value + 1); setNotice("Proposal retained. A separate reviewer must approve it before it becomes accepted state.");
    } catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  async function review(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!proposal) return;
    const data = new FormData(event.currentTarget); setBusy(true); setError("");
    try { setProposal(await api<ResourceProposalDetail>(`proposals/${proposal.proposal.proposal_id}/decision`, { decision: data.get("decision"), rationale: data.get("rationale") })); setRevision(value => value + 1); setNotice("Review recorded with its immutable change history."); }
    catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  async function referenceProposal() {
    setBusy(true); setError("");
    try { setProposal(await api<ResourceProposalDetail>("reference-proposal", {})); setDetail(null); setDraft(null); setRevision(value => value + 1); }
    catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  function edit(resource: CanonicalResource, attributes = resource.attributes) {
    setDraft({ type: resource.object_type, current: resource, name: resource.display_name, attributes }); setDetail(null); setProposal(null);
  }
  function renderValue(value: unknown): string {
    if (typeof value === "string") return names.get(value) ?? value;
    return JSON.stringify(value);
  }

  return <section className="ontology-workspace">
    <div className="section-heading"><div><p className="overline">SHARED ENTERPRISE RESOURCES</p><h1>Enterprise & ontology</h1><p className="muted">Explore typed relationships, govern identity and review changes to shared business meaning.</p></div><button className="quiet" disabled={busy} onClick={() => setRevision(value => value + 1)}>Refresh</button></div>
    <div className="ontology-tabs">{(["graph", "resources", "review", "registry"] as const).map(id => <button className={tab === id ? "active" : "quiet"} key={id} onClick={() => { setTab(id); setKind(""); }}>{id === "graph" ? "Enterprise graph" : id === "review" ? `Change review (${queue.filter(row => row.decision === "PENDING").length})` : label(id)}</button>)}</div>
    {error && <p className="error-banner" role="alert">{error}</p>}{notice && <p className="success-banner" role="status">{notice}</p>}
    {bounded && <p className="error-banner">This graph is limited to 1,000 visible resources. It is not a complete enterprise inventory.</p>}
    <div className="ontology-layout"><div>
      {tab === "graph" && <section className="data-panel"><div className="toolbar"><div><h2>Enterprise relationships</h2><p className="muted">Legal ownership, operating domains and participation remain distinct.</p></div>{admin && canPropose && <button className="quiet" disabled={busy} onClick={() => void referenceProposal()}>Propose SOCAR reference graph</button>}</div>
        {!graphNodes.length ? <div className="empty-state"><h3>No accepted enterprise resources</h3><p>Create resources and typed relationships, then approve them with an independent reviewer. The SOCAR template is explicitly hypothetical reference data.</p></div> : <div className="enterprise-graph"><svg role="img" aria-label="Accepted enterprise relationship graph" viewBox={`0 0 840 ${Math.max(300, Math.ceil(graphNodes.length / 3) * 150)}`}>
          <defs><marker id="relation-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7" fill="#49757a" /></marker></defs>
          {nodes.filter(node => node.object_type === "Relationship").map(edge => { const from = positions.get(String(edge.attributes.source_id)), to = positions.get(String(edge.attributes.target_id)); return from && to ? <g key={edge.resource_id}><path d={`M${from.x + 110},${from.y + 86} Q${from.x + 245},${to.y + 120} ${to.x + 110},${to.y}`} stroke="#49757a" fill="none" strokeWidth="1.5" markerEnd="url(#relation-arrow)" /><title>{edge.display_name}</title></g> : null; })}
          {graphNodes.map(node => { const pos = positions.get(node.resource_id)!; return <foreignObject key={node.resource_id} x={pos.x} y={pos.y} width="235" height="106"><button className="graph-node" onClick={() => void inspect(node.resource_id)}><small>{label(node.object_type)}</small><strong>{node.display_name}</strong><span>{node.evidence_class === "REFERENCE_TEMPLATE" ? "Reference example" : label(node.evidence_class)}</span></button></foreignObject>; })}
        </svg></div>}
      </section>}
      {(tab === "resources" || tab === "registry") && <section className="data-panel"><div className="toolbar"><input aria-label="Find resource" placeholder="Find a resource" value={search} onChange={event => setSearch(event.target.value)} /><select aria-label="Resource type" value={kind} onChange={event => setKind(event.target.value)}><option value="">All types</option>{(tab === "registry" ? [...metadata] : schemas.map(schema => schema.identity_key)).map(type => <option key={type}>{type}</option>)}</select></div>
        <div className="data-scroll"><table><thead><tr><th>Resource</th><th>Type</th><th>Evidence</th></tr></thead><tbody>{visible.map(node => <tr key={node.resource_id}><td><button className="text-link" onClick={() => void inspect(node.resource_id)}>{node.display_name}</button></td><td>{label(node.object_type)}</td><td>{label(node.evidence_class)}</td></tr>)}</tbody></table>{!visible.length && <p className="empty-state">No resources match this view.</p>}</div></section>}
      {tab === "review" && <section className="data-panel"><div className="toolbar"><h2>Immutable change proposals</h2></div><div className="data-scroll"><table><thead><tr><th>Proposal</th><th>Author</th><th>Decision</th></tr></thead><tbody>{queue.map(row => <tr key={row.proposal_id}><td><button className="text-link" onClick={() => void openProposal(row.proposal_id)}>{row.title}</button></td><td>{row.submitted_by}</td><td><span className={`status ${row.decision.toLowerCase()}`}>{row.decision}</span></td></tr>)}</tbody></table>{!queue.length && <p className="empty-state">No change proposals yet.</p>}</div></section>}
      {canPropose && <div className="upload-strip"><div><h3>Create a governed resource</h3><p>Typed fields and references are validated before review.</p></div><select aria-label="New resource type" defaultValue="" onChange={event => { if (event.target.value) { setDraft({ type: event.target.value, attributes: {}, name: "" }); setDetail(null); setProposal(null); event.target.value = ""; } }}><option value="">Choose a type…</option>{schemas.map(schema => <option key={schema.resource_id} value={schema.identity_key}>{label(schema.identity_key)}</option>)}</select></div>}
    </div>
    {(detail || proposal || draft) && <aside className="ontology-inspector data-panel"><button className="quiet close-inspector" onClick={() => { selection.current++; setDetail(null); setProposal(null); setDraft(null); }}>Close</button>
      {detail && <><p className="overline">{label(detail.resource.object_type)}</p><h2>{detail.resource.display_name}</h2><span className="status observed">{label(detail.resource.evidence_class)}</span><dl className="resource-fields">{Object.entries(detail.resource.attributes).map(([key, value]) => <div key={key}><dt>{label(key)}</dt><dd>{typeof value === "string" && names.has(value) ? <button className="text-link" onClick={() => void inspect(value)}>{names.get(value)}</button> : renderValue(value)}</dd></div>)}</dl>
        <IdentityHistory key={detail.resource.resource_id} resourceId={detail.resource.resource_id} token={token} />
        {canPropose && (!metadata.has(detail.resource.object_type) || admin) && <button onClick={() => edit(detail.resource)}>Propose a new version</button>}
        <h3>Version history</h3>{detail.versions.map(version => <details key={version.version_id}><summary>{new Date(version.system_from).toLocaleString()} · {version.authority_state}</summary><p>Effective {new Date(version.valid_from).toLocaleString()}</p><pre>{JSON.stringify(version.attributes, null, 2)}</pre>{canPropose && (!metadata.has(detail.resource.object_type) || admin) && <button className="quiet" onClick={() => edit(detail.resource, version.attributes)}>Propose restoring these values</button>}</details>)}
        <h3>Dependent versions</h3>{detail.dependents.length ? detail.dependents.map((row, i) => <p key={`${row.version_id}:${row.relation}:${i}`}><button className="text-link" onClick={() => void inspect(row.resource_id)}>{row.display_name}</button><small> · {row.relation}</small></p>) : <p className="muted">No recorded dependent versions.</p>}
        <details><summary>Identity & provenance</summary><p>Identity {detail.resource.resource_id}</p><p>Version {detail.resource.version_id}</p><p>Hash {detail.resource.content_hash}</p><p>Access: {detail.resource.access_entity}</p></details></>}
      {draft && <form key={draft.current?.resource_id ?? draft.type} className="resource-form" onSubmit={submit}><p className="overline">{draft.current ? "PROPOSE VERSION" : "NEW RESOURCE"}</p><h2>{label(draft.type)}</h2><label>Display name<input name="display_name" defaultValue={draft.name} required maxLength={200} /></label>
        {!draft.current && !["Alias", "IdentityResolution", "ContextBinding"].includes(draft.type) && <label>Stable business key<input name="identity_key" required maxLength={256} placeholder="A stable identifier from your resource register" /></label>}
        {fields ? Object.entries(fields).filter(([name]) => !(draft.type === "ContextBinding" && name === "source_scope_key")).map(([name, spec]) => <label key={name}>{label(name)}{spec.required ? " *" : ""}{spec.kind === "reference" ? <select name={name} required={spec.required} defaultValue={String(draft.attributes[name] ?? "")}><option value="">Choose a resource…</option>{[...catalog, ...nodes.filter(node => !metadata.has(node.object_type))].filter(node => !spec.target_type || spec.target_type === "*" || node.object_type === spec.target_type).map(node => <option key={node.resource_id} value={node.resource_id}>{node.display_name} · {label(node.object_type)}</option>)}</select> : spec.kind === "boolean" ? <select name={name} defaultValue={String(draft.attributes[name] ?? false)}><option value="false">No</option><option value="true">Yes</option></select> : <input name={name} required={spec.required} type={spec.kind === "date" ? "date" : spec.kind === "integer" ? "number" : "text"} defaultValue={draft.attributes[name] === undefined ? "" : typeof draft.attributes[name] === "object" ? JSON.stringify(draft.attributes[name]) : String(draft.attributes[name])} placeholder={spec.kind === "datetime" ? "2026-09-05T00:00:00Z" : spec.kind === "money" ? '{"amount":"0.00","currency_id":"…"}' : spec.kind === "quantity" ? '{"amount":"0","unit":"…"}' : label(spec.kind)} />}</label>) : <label>Registry definition<textarea name="attributes" rows={16} defaultValue={JSON.stringify(draft.attributes, null, 2)} required /></label>}
        <label>Effective from<input type="datetime-local" name="valid_from" required defaultValue={effectiveFrom} /></label><label>Reason and evidence<textarea name="rationale" required minLength={10} maxLength={2000} rows={3} /></label><button disabled={busy}>{busy ? "Validating…" : "Validate & submit for review"}</button></form>}
      {proposal && <><p className="overline">CHANGE REVIEW</p><h2>{proposal.proposal.title}</h2><p>{proposal.proposal.rationale}</p><p>Submitted by {proposal.submitted_by}</p><span className="status observed">{proposal.decision ?? "PENDING"}</span><h3>Validated impact</h3>{proposal.validation.impact.map(item => <div className="impact-item" key={item.resource_id}><strong>{item.name}</strong><small>{item.operation} · {item.fields_changed.map(label).join(", ")}</small><SchemaChangeDetails item={item} /></div>)}<ProposalImpact key={proposal.proposal.proposal_id} validation={proposal.validation} /><details><summary>Proposed values</summary><pre>{JSON.stringify(proposal.proposal.mutations, null, 2)}</pre></details>
        {proposal.decision ? <p>Reviewed by {proposal.reviewed_by}: {proposal.review_rationale}</p> : canReview && proposal.submitted_by !== principal.actor_id ? <form className="resource-form" onSubmit={review}><label>Decision<select name="decision" defaultValue={proposal.validation.downstream_impact?.status === "COMPLETE" ? "APPROVED" : "REJECTED"}><option value="APPROVED" disabled={proposal.validation.downstream_impact?.status !== "COMPLETE"}>Approve</option><option value="REJECTED">Reject</option></select></label><label>Review rationale<textarea name="rationale" minLength={10} maxLength={2000} required /></label><button disabled={busy}>Record review</button></form> : <p className="muted">An independent reviewer identity is required.</p>}</>}
    </aside>}
    </div>
  </section>;
}
