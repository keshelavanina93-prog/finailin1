"use client";

import { useEffect, useRef, useState } from "react";
import AccountDimensionPolicyWorkbench from "./account-dimension-policy-workbench";
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

export default function SegAccountObservations({ token, documentId, sheet, profile, companyId, onInspectResource, onTraceResource, canPropose=false, onProposal }: {
  token: string; documentId: string; sheet: string; profile: string; companyId: string; canPropose?:boolean; onProposal?:(id:string)=>void;
} & SourceAccountNavigation) {
  const [policyAccount,setPolicyAccount]=useState<{context:string;account:Definition}|null>(null);
  const identity = JSON.stringify([token, documentId, sheet, profile, companyId]);
  const [selection, setSelection] = useState<{ key: string; choices: Record<string, string>; rationale: string }>({ key: identity, choices: {}, rationale: "" });
  const choices = selection.key === identity ? selection.choices : {};
  const rationale = selection.key === identity ? selection.rationale : "";
  const [state, setState] = useState<{ key: string; busy: boolean; result: Result | null; error: string } | null>(null);
  const request = useRef<AbortController | null>(null);
  const current = state?.key === identity ? state : null;
  useEffect(() => () => request.current?.abort(), [identity]);

  async function inspect() {
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    setState({ key: identity, busy: true, result: null, error: "" });
    setSelection({ key: identity, choices: {}, rationale: "" });
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

  async function proposeChart() {
    if (!current?.result || !onProposal) return;
    const result = current.result;
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    setState({ key: identity, busy: true, result, error: "" });
    try {
      const accounts = result.rows.flatMap(row => {
        const definition = row.definitions.find(item => `${item.resource_id}:${item.version_id}` === choices[row.code]);
        return definition ? [{ code: row.code, definition_id: definition.resource_id, definition_version_id: definition.version_id }] : [];
      });
      const response = await fetch(`/api/ontology/source-documents/${documentId}/accounting-context/chart-proposal`, {
        method: "POST", signal: controller.signal,
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ sheet, profile, company_id: companyId, selection: { source_sha256: result.source_sha256, accounts, rationale: rationale.trim() } }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Chart review could not be prepared");
      if (!controller.signal.aborted) {
        setState({ key: identity, busy: false, result, error: "" });
        onProposal(data.proposal.proposal_id);
      }
    } catch (failure) {
      if (!controller.signal.aborted) setState({ key: identity, busy: false, result, error: failure instanceof Error ? failure.message : "Chart review unavailable" });
    }
  }

  return <section aria-label="Source account code observations">
    {policyAccount?.context===identity&&<AccountDimensionPolicyWorkbench token={token} companyId={companyId} account={policyAccount.account} canPropose={canPropose&&Boolean(onProposal)} onProposal={onProposal??(()=>{})} onClose={()=>setPolicyAccount(null)} onInspectResource={onInspectResource} onTraceResource={onTraceResource}/>}
    <h4>Account codes recorded by the source</h4>
    <p>Compare exact source codes with retained account definitions. Matches remain review candidates; they do not select a chart or authorize accounting.</p>
    <button disabled={current?.busy} onClick={() => void inspect()}>Inspect source account codes</button>
    {current?.busy && <p role="status">Reading source account codes and retained definitions…</p>}
    {current?.error && <p role="alert">{current.error}</p>}
    {current?.result && <>
      <p>{current.result.observed_code_count} observed codes across {current.result.row_count} source rows · candidate review</p>
      {current.result.blockers.map(blocker => <p key={blocker}>{blocker}</p>)}
      {canPropose && onProposal && <fieldset disabled={current.busy}>
        <legend>Prepare company chart review</legend>
        <p>Select the retained definition that applies to each source code below, up to 20 accounts per proposal. Nothing is selected automatically. Unselected codes remain unresolved.</p>
        <label>Why these definitions apply to this company source
          <textarea maxLength={1700} value={rationale} onChange={event => setSelection({ key: identity, choices, rationale: event.target.value })}/>
        </label>
        <p>This review establishes account identities only. Amounts, currencies, reporting classification and period completeness require their own reviewed context.</p>
        <button disabled={!Object.values(choices).filter(Boolean).length || Object.values(choices).filter(Boolean).length > 20 || rationale.trim().length < 10} onClick={() => void proposeChart()}>Review selected accounts ({Object.values(choices).filter(Boolean).length})</button>
      </fieldset>}
      <details><summary>Original source reference</summary><p>SHA-256: <code>{current.result.source_sha256}</code></p></details>
      <div className="source-table"><table><thead><tr><th>Exact source code</th><th>Debit observations</th><th>Credit observations</th><th>Source cells</th><th>Definition candidates</th></tr></thead><tbody>
        {current.result.rows.map(row => <tr key={row.code}>
          <th scope="row"><code>{row.code}</code></th><td>{row.debit_count}</td><td>{row.credit_count}</td>
          <td><details><summary>{row.coordinates.length} of {row.coordinate_count} source coordinates</summary>{row.coordinates_truncated && <p>The coordinate preview reached its limit. The original source retains the remaining cells.</p>}<ul>{row.coordinates.map((cell, index) => <li key={`${cell.coordinate}:${cell.side}:${index}`}><code>{cell.coordinate}</code> · {cell.side.toLowerCase()}</li>)}</ul></details></td>
          <td>{canPropose && onProposal && row.definitions.length > 0 && <label>Definition for {row.code}
            <select disabled={current.busy} value={choices[row.code] ?? ""} onChange={event => setSelection({ key: identity, choices: { ...choices, [row.code]: event.target.value }, rationale })}>
              <option value="">Leave unresolved</option>
              {row.definitions.map(definition => <option key={`${definition.resource_id}:${definition.version_id}`} value={`${definition.resource_id}:${definition.version_id}`}>{definition.display_name}</option>)}
            </select>
          </label>}{row.definitions.length ? row.definitions.map(definition => <details key={`${definition.resource_id}:${definition.version_id}`}>
            <summary>{definition.display_name}</summary>
            <button onClick={()=>setPolicyAccount({context:identity,account:definition})}>Review analytical requirements for this definition</button>
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
