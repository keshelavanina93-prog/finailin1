import type { ObjectDetail } from "@finai/contracts";
import CanonicalTrace from "./canonical-trace";

export default function ObjectPanel({ detail, onClose }: { detail: ObjectDetail; onClose: () => void }) {
  return <aside className="object-inspector" aria-label="Object evidence inspector">
    <div className="section-heading"><div><p className="overline">OBJECT & EVIDENCE</p><h2>{detail.object.values.account_code ?? detail.object.object_type}</h2></div><button className="quiet" onClick={onClose}>Close</button></div>
    <div className="identity-line"><span className="status approved">APPROVED</span><span>{detail.is_current ? "Current version" : "Historical version"}</span></div>
    <h3>{detail.object.object_type}</h3><dl className="value-list">{Object.entries(detail.object.values).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl>
    <CanonicalTrace references={detail.object.canonical_references} />
    <h3>Why this object exists</h3><p>{detail.object.epistemic_state === "DERIVED" ? `Calculated by ${detail.object.function}.` : "Observed in the retained source row."}</p>
    <p>Source row {detail.object.source_row} · {detail.scope.legal_entity_id} · {detail.scope.period} · {detail.scope.currency}</p>
    <dl className="value-list">{Object.entries(detail.source_row_values).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl>
    <h3>Approval</h3><p>{detail.decision.reason}</p><small>{detail.decision.actor_id} · {new Date(detail.decision.decided_at).toLocaleString()}</small>
    <h3>Retained source hash</h3><code className="full-hash">{detail.source_sha256}</code>
    <p className="warning">Drill depth stops at this source row. This approval does not certify underlying transactions.</p>
  </aside>;
}
