"use client";
import { useState } from "react";
import type { ResourceProposalDetail } from "@finai/contracts";

export default function ProposalImpact({ validation }: { validation: ResourceProposalDetail["validation"] }) {
  const [page, setPage] = useState(0);
  const impact = validation.downstream_impact;
  if (!impact) return <p className="warning">This proposal predates dependency impact snapshots. A fresh proposal is required for controlled promotion.</p>;
  if (impact.status === "RESTRICTED") return <p className="warning">The impact includes restricted resources. An authorized tenant steward must inspect the protected snapshot and review this change.</p>;
  const unique = new Set(impact.affected.map(item => item.resource_id));
  return <section aria-label="Downstream change impact"><h3>Downstream impact · {unique.size} resources</h3>
    <p>Current accepted consumers and proposed changes are pinned to this review. A changed dependency chain requires a fresh review before promotion.</p>
    {impact.affected.length ? <><div className="data-scroll"><table><thead><tr><th>Affected resource</th><th>Distance</th><th>Version state</th></tr></thead><tbody>
      {impact.affected.slice(page * 25, (page + 1) * 25).map(item => <tr key={`${item.root_resource_id}:${item.resource_id}:${item.state}`}><td>{item.display_name}<small className="hash-caption">{item.object_type}</small><details><summary>Version trace</summary><p>Changed root {item.root_resource_id}</p><p>Resource {item.resource_id}</p><p>Version {item.version_id}</p></details></td><td>{item.depth === 1 ? "Direct" : `${item.depth} links`}</td><td>{item.state === "PROPOSED" ? "In this change" : "Accepted"}</td></tr>)}
    </tbody></table></div><div className="pagination"><button className="quiet" disabled={page === 0} onClick={() => setPage(value => value - 1)}>Previous</button><span>Page {page + 1}</span><button className="quiet" disabled={(page + 1) * 25 >= impact.affected.length} onClick={() => setPage(value => value + 1)}>Next</button></div></> : <p>No downstream consumers were found in the accepted dependency graph.</p>}
    <small>Complete within enforced limits: {impact.max_depth} links, {impact.max_resources} resources. Incomplete or restricted impact prevents promotion.</small>
  </section>;
}
