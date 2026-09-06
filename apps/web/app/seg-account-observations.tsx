"use client";

import { useEffect, useRef, useState } from "react";
import type { CanonicalResource } from "@finai/contracts";

export type SourceAccountNavigation = {
  onInspectResource?: (reference: Pick<CanonicalResource, "resource_id" | "version_id">) => void;
  onTraceResource?: (reference: Pick<CanonicalResource, "resource_id" | "version_id">) => void;
};

type Definition = {
  resource_id: string;
  version_id: string;
  display_name: string;
  evidence_class: string;
  attributes: Record<string, unknown>;
};
type Observation = {
  code: string;
  debit_count: number;
  credit_count: number;
  coordinates: { coordinate: string; side: string }[];
  coordinate_count: number;
  coordinates_truncated: boolean;
  definitions: Definition[];
};
type Result = {
  source_sha256: string;
  accounting_use_authorized: false;
  mapping_state: "CANDIDATE_REVIEW";
  observed_code_count: number;
  row_count: number;
  rows: Observation[];
  blockers: string[];
};

export default function SegAccountObservations({ token, documentId, sheet, profile, companyId, onInspectResource, onTraceResource }: {
  token: string; documentId: string; sheet: string; profile: string; companyId: string;
} & SourceAccountNavigation) {
  const identity = JSON.stringify([token, documentId, sheet, profile, companyId]);
  const [state, setState] = useState<{ key: string; busy: boolean; result: Result | null; error: string } | null>(null);
  const request = useRef<AbortController | null>(null);
  const current = state?.key === identity ? state : null;
  useEffect(() => () => request.current?.abort(), [identity]);

  async function inspect() {
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    setState({ key: identity, busy: true, result: null, error: "" });
    try {
      const response = await fetch(`/api/ontology/source-documents/${documentId}/accounting-context/account-observations`, {
        method: "POST", signal: controller.signal,
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ sheet, profile, company_id: companyId }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Source account observations unavailable");
      if (data.mapping_state !== "CANDIDATE_REVIEW" || data.accounting_use_authorized !== false) throw new Error("The source account review contract is unavailable");
      if (!controller.signal.aborted) setState({ key: identity, busy: false, result: data, error: "" });
    } catch (failure) {
      if (!controller.signal.aborted) setState({ key: identity, busy: false, result: null, error: failure instanceof Error ? failure.message : "Source account observations unavailable" });
    }
  }

  return <section aria-label="Source account code observations">
    <h4>Account codes recorded by the source</h4>
    <p>Compare exact source codes with retained account definitions. Matches remain review candidates; they do not select a chart or authorize accounting.</p>
    <button disabled={current?.busy} onClick={() => void inspect()}>Inspect source account codes</button>
    {current?.busy && <p role="status">Reading source account codes and retained definitions…</p>}
    {current?.error && <p role="alert">{current.error}</p>}
    {current?.result && <>
      <p>{current.result.observed_code_count} observed codes across {current.result.row_count} source rows · candidate review</p>
      {current.result.blockers.map(blocker => <p key={blocker}>{blocker}</p>)}
      <details><summary>Original source reference</summary><p>SHA-256: <code>{current.result.source_sha256}</code></p></details>
      <div className="source-table"><table><thead><tr><th>Exact source code</th><th>Debit observations</th><th>Credit observations</th><th>Source cells</th><th>Definition candidates</th></tr></thead><tbody>
        {current.result.rows.map(row => <tr key={row.code}>
          <th scope="row"><code>{row.code}</code></th><td>{row.debit_count}</td><td>{row.credit_count}</td>
          <td><details><summary>{row.coordinates.length} of {row.coordinate_count} source coordinates</summary>{row.coordinates_truncated && <p>The coordinate preview reached its limit. The original source retains the remaining cells.</p>}<ul>{row.coordinates.map((cell, index) => <li key={`${cell.coordinate}:${cell.side}:${index}`}><code>{cell.coordinate}</code> · {cell.side.toLowerCase()}</li>)}</ul></details></td>
          <td>{row.definitions.length ? row.definitions.map(definition => <details key={`${definition.resource_id}:${definition.version_id}`}>
            <summary>{definition.display_name}</summary>
            <p>Exact-code candidate · {definition.evidence_class.toLowerCase().replaceAll("_", " ")}</p>
            {typeof definition.attributes.source_name === "string" && <p>{definition.attributes.source_name}</p>}
            {(onInspectResource || onTraceResource) && <div>
              {onInspectResource && <button className="g8-link" onClick={() => onInspectResource({ resource_id: definition.resource_id, version_id: definition.version_id })}>Inspect retained definition</button>}
              {onTraceResource && <button className="g8-link" onClick={() => onTraceResource({ resource_id: definition.resource_id, version_id: definition.version_id })}>Trace source evidence</button>}
            </div>}
            <details><summary>Source provenance and exact version</summary>
              <dl><dt>Definition identity</dt><dd><code>{definition.resource_id}</code></dd><dt>Retained version</dt><dd><code>{definition.version_id}</code></dd>
                {typeof definition.attributes.source_record_id === "string" && <><dt>Source record</dt><dd><code>{definition.attributes.source_record_id}</code></dd></>}
              </dl>
              {definition.attributes.definition != null && <pre>{JSON.stringify(definition.attributes.definition, null, 2)}</pre>}
            </details>
          </details>) : <span>No retained definition candidate for this exact code</span>}</td>
        </tr>)}
      </tbody></table></div>
      {!current.result.rows.length && <p>No account code observations were returned for this source.</p>}
    </>}
  </section>;
}
