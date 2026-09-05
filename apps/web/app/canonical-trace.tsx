import type { IngestReceipt } from "@finai/contracts";

export default function CanonicalTrace({ references }: { references: IngestReceipt["canonical_references"] }) {
  const entries = Object.entries(references ?? {});
  if (!entries.length) return <p className="muted">Source observation only · shared business identity has not been bound.</p>;
  return <details className="canonical-trace"><summary>Trace shared identity · {entries.length} pinned references</summary>
    <p>These are the exact shared resources used in this construction. Later changes do not rewrite this evidence.</p>
    <dl className="value-list">{entries.map(([role, reference]) => <div key={role}><dt>{role}</dt><dd><span>{reference.resource_id}</span><small>Version {reference.version_id}</small></dd></div>)}</dl>
  </details>;
}
