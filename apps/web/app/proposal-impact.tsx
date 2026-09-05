"use client";
import { useState } from "react";
import type { ResourceProposalDetail } from "@finai/contracts";

export function SchemaChangeDetails({ item }: { item: ResourceProposalDetail["validation"]["impact"][number] }) {
  if (!item.compatibility) return null;
  return <details><summary>{item.compatibility === "INITIAL" ? "Initial schema" : "Backward-compatible schema change"} · {item.semantic_changes?.length ?? 0} field changes</summary>
    {item.semantic_changes?.map((change, index) => <div key={`${change.field_id}:${change.change}:${index}`}><strong>{change.field_name}</strong><p>{change.change.toLowerCase().replaceAll("_", " ")}</p>
      <details><summary>Before and after</summary><p>Before</p><pre>{JSON.stringify(change.before, null, 2)}</pre><p>After</p><pre>{JSON.stringify(change.after, null, 2)}</pre>{change.field_id && <code className="full-hash">Field identity {change.field_id}</code>}</details>
    </div>)}
  </details>;
}

function ChangeValue({ value }: {value: {present: boolean; value?: unknown}}) {
  if (!value.present) return <em>Not present</em>;
  if (value.value === null) return <code>null</code>;
  if (typeof value.value === "object") return <details><summary>View structured value</summary><pre>{JSON.stringify(value.value, null, 2)}</pre></details>;
  return <span>{JSON.stringify(value.value)}</span>;
}
function RetainedChanges({validation}: {validation: ResourceProposalDetail["validation"]}) {
 return <section aria-label="Retained before and after changes"><h3>What this change alters</h3>{validation.impact.map(item=><details key={item.resource_id}><summary>{item.name} · {item.semantic_diff?.changes.length ?? "Unrecorded"} changes</summary>{item.semantic_diff?<><p>Compared with {item.semantic_diff.base_version_id?"the accepted version at submission":"a new resource"}. This comparison is retained with the proposal.</p><div className="data-scroll"><table><thead><tr><th>Property</th><th>Before</th><th>After</th></tr></thead><tbody>{item.semantic_diff.changes.map(change=><tr key={change.path}><td>{change.path.split("/").slice(1).map(part=>part.replaceAll("~1","/").replaceAll("~0","~").replaceAll("_"," ")).join(" / ")}<small className="hash-caption">{change.category.toLowerCase().replaceAll("_"," ")} · {change.operation.toLowerCase()}</small></td><td><ChangeValue value={change.before}/></td><td><ChangeValue value={change.after}/></td></tr>)}</tbody></table></div></>:<p>Detailed diff was not retained for this earlier proposal.</p>}</details>)}</section>;
}
export default function ProposalImpact({ validation }: { validation: ResourceProposalDetail["validation"] }) {
  const [page, setPage] = useState(0);
  const impact = validation.downstream_impact;
  if (!impact) return <p className="warning">This proposal predates dependency impact snapshots. A fresh proposal is required for controlled promotion.</p>;
  if (impact.status === "RESTRICTED") return <p className="warning">The impact includes restricted resources. An authorized tenant steward must inspect the protected snapshot and review this change.</p>;
  const unique = new Set(impact.affected.map(item => item.resource_id));
  return <section aria-label="Downstream change impact"><RetainedChanges validation={validation}/><h3>Downstream impact · {unique.size} resources</h3>
    <p>Current accepted consumers and proposed changes are pinned to this review. A changed dependency chain requires a fresh review before promotion.</p>
    {impact.affected.length ? <><div className="data-scroll"><table><thead><tr><th>Affected resource</th><th>Distance</th><th>Version state</th></tr></thead><tbody>
      {impact.affected.slice(page * 25, (page + 1) * 25).map(item => <tr key={`${item.root_resource_id}:${item.resource_id}:${item.state}`}><td>{item.display_name}<small className="hash-caption">{item.object_type}</small><details><summary>Version trace</summary><p>Changed root {item.root_resource_id}</p><p>Resource {item.resource_id}</p><p>Version {item.version_id}</p></details></td><td>{item.depth === 1 ? "Direct" : `${item.depth} links`}</td><td>{item.state === "PROPOSED" ? "In this change" : "Accepted"}</td></tr>)}
    </tbody></table></div><div className="pagination"><button className="quiet" disabled={page === 0} onClick={() => setPage(value => value - 1)}>Previous</button><span>Page {page + 1}</span><button className="quiet" disabled={(page + 1) * 25 >= impact.affected.length} onClick={() => setPage(value => value + 1)}>Next</button></div></> : <p>No downstream consumers were found in the accepted dependency graph.</p>}
    <small>Complete within enforced limits: {impact.max_depth} links, {impact.max_resources} resources. Incomplete or restricted impact prevents promotion.</small>
  </section>;
}
