"use client";

import {useEffect, useState} from "react";
import {Badge, Empty} from "./g8-ui";
import {operationsRequest} from "./operations-model";

type BindingRow = {source_row: number; status: string; bindings: Record<string, boolean>; reasons: string[]; promotion_eligible: boolean};
type BindingResult = {profile: string; status: string; promotion_eligible: boolean; canonical_promotion: string; rows: BindingRow[]};

export default function OperationalBindingReview({token, receiptId, profile}: {token: string; receiptId: string; profile?: string}) {
  const [result, setResult] = useState<BindingResult | null>(null); const [error, setError] = useState("");
  const operational = Boolean(profile?.startsWith("orpak-") || profile?.startsWith("scada-") || profile?.startsWith("gas-telemetry-"));
  useEffect(() => { if (!operational) return; const controller = new AbortController();
    void operationsRequest<BindingResult>(`petroleum/intake/${encodeURIComponent(receiptId)}/validation`, token, controller.signal).then(setResult).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Binding validation unavailable"); });
    return () => controller.abort();
  }, [operational, profile, receiptId, token]);
  if (!operational) return null; if (error) return <p className="g8-inline-error" role="alert">{error}</p>; if (!result) return <p role="status">Resolving operational identifiers against accepted ontology objects…</p>;
  return <section className="source-detail" aria-label="Operational semantic binding validation"><h3>Operational grain and semantic bindings</h3><p>{result.profile} · one source row is checked as one governed operational event. Technical validity does not create a canonical business object.</p><div className="source-quality-grid"><div><small>Binding status</small><strong><Badge tone={result.status === "VALIDATED" ? "good" : "warning"}>{result.status}</Badge></strong></div><div><small>Rows checked</small><strong>{result.rows.length}</strong></div><div><small>Canonical promotion</small><strong>{result.promotion_eligible ? "Eligible" : "Review required"}</strong></div></div>{!result.rows.length ? <Empty title="No operational source rows">The retained receipt contains no SourceRecord candidates for semantic binding.</Empty> : <div className="source-table"><table><thead><tr><th>Source row</th><th>Identifier bindings</th><th>Reasons</th></tr></thead><tbody>{result.rows.map(row => <tr key={row.source_row}><th scope="row">{row.source_row}<br/><Badge tone={row.status === "VALIDATED" ? "good" : "warning"}>{row.status}</Badge></th><td>{Object.entries(row.bindings).map(([key, bound]) => <div key={key}>{key}: {bound ? "bound" : "unbound"}</div>)}</td><td>{row.reasons.length ? row.reasons.join(", ") : "No binding or structural findings"}</td></tr>)}</tbody></table></div>}<p className="g8-context-note">{result.canonical_promotion}. Accounting authority and business effect remain disabled until governed mapping and approval.</p></section>;
}
