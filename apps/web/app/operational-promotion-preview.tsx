"use client";

import {useEffect, useState} from "react";
import {Badge, Empty} from "./g8-ui";
import {operationsRequest} from "./operations-model";

type PreviewCandidate = {object_type: string; source_row: number; identity_key: string; values: Record<string, string>; evidence: {receipt_id: string; source_record_id: string; source_hash: string; valid_at: string}};
type Preview = {status: string; proposal_required: boolean; canonical_mutation: boolean; candidates: PreviewCandidate[]};

export default function OperationalPromotionPreview({token, receiptId, profile}: {token: string; receiptId: string; profile?: string}) {
  const [preview, setPreview] = useState<Preview | null>(null); const [error, setError] = useState("");
  const operational = Boolean(profile?.startsWith("orpak-") || profile?.startsWith("scada-") || profile?.startsWith("gas-telemetry-") || profile?.startsWith("retail-cash-register-"));
  useEffect(() => { if (!operational) return; const controller = new AbortController();
    void operationsRequest<Preview>(`petroleum/intake/${encodeURIComponent(receiptId)}/promotion-preview`, token, controller.signal).then(setPreview).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Promotion preview unavailable"); });
    return () => controller.abort();
  }, [operational, receiptId, token]);
  if (!operational || error) return error ? <p className="g8-inline-error" role="alert">{error}</p> : null;
  if (!preview) return <p role="status">Preparing the governed promotion preview…</p>;
  return <section className="source-detail" aria-label="Operational promotion preview"><h3>Governed promotion preview</h3><p><Badge tone={preview.candidates.length ? "good" : "warning"}>{preview.status}</Badge> This is a proposal packet only; no canonical mutation or accounting effect has occurred.</p>{!preview.candidates.length ? <Empty title="No eligible operational rows">Resolve grain, evidence, and accepted semantic bindings before preparing a governed proposal.</Empty> : <div className="source-table"><table><thead><tr><th>Row</th><th>Candidate</th><th>Identity</th><th>Evidence</th></tr></thead><tbody>{preview.candidates.map(candidate => <tr key={`${candidate.object_type}:${candidate.source_row}`}><th scope="row">{candidate.source_row}</th><td>{candidate.object_type}</td><td>{candidate.identity_key}</td><td>{candidate.evidence.source_record_id}<br/><small>{candidate.evidence.source_hash}</small></td></tr>)}</tbody></table></div>}<p className="g8-context-note">Proposal required: {preview.proposal_required ? "yes" : "no"}. Canonical mutation: {preview.canonical_mutation ? "enabled" : "disabled"}.</p></section>;
}
