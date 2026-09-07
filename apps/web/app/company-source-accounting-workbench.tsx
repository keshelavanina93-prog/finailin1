"use client";

import { useEffect, useState } from "react";
import type { CanonicalResource } from "@finai/contracts";
import type { Context } from "./company-workspace";
import type { SourceAccountNavigation } from "./seg-account-observations";
import SourceAccountingContext from "./source-accounting-context";
import "./company-source-accounting-workbench.css";

type Props = {
  token: string; context: Context; viewStateKey?: string; canPropose: boolean;
  onProposal: (id: string) => void;
  onInspect: (resource: CanonicalResource) => void;
  onTrace?: (resource: CanonicalResource) => void;
  onHistory?: (resource: CanonicalResource) => void;
} & SourceAccountNavigation;
const text = (value: unknown) => typeof value === "string" ? value : "";
const readable = (value: string) => value.toLowerCase().replaceAll("_", " ");

export default function CompanySourceAccountingWorkbench(props: Props) {
  return <SourceWorkbench key={`${props.token}:${props.context.company.resource_id}`} {...props}/>;
}
function SourceWorkbench({token,context,viewStateKey,canPropose,onProposal,onInspect,onTrace,onHistory,onInspectResource,onTraceResource}: Props) {
  const companyId = context.company.resource_id;
  const storageKey = viewStateKey ? `${viewStateKey}:source-accounting` : undefined;
  const [selectedId,setSelectedId] = useState(() => {
    try {
      const saved = storageKey ? JSON.parse(sessionStorage.getItem(storageKey) ?? "null") : null;
      return saved?.companyId === companyId && typeof saved.scopeId === "string" ? saved.scopeId : "";
    } catch { return ""; }
  });
  useEffect(() => {
    if(storageKey) try {sessionStorage.setItem(storageKey,JSON.stringify({companyId,scopeId:selectedId}));} catch { /* Navigation remains available without storage. */ }
  },[storageKey,companyId,selectedId]);
  const selected = context.accounting_sources.find(source => source.scope.resource_id === selectedId);
  const attrs = selected?.scope.attributes;
  const documentId = text(attrs?.document_id);
  const worksheet = text(attrs?.worksheet);
  const profile = text(attrs?.source_profile);
  const matchingCompany = text(attrs?.legal_entity_id) === companyId;
  const supported = ["1c_tb","1c_journal","seg_expense_base"].includes(profile);
  const available = matchingCompany && supported && Boolean(documentId && worksheet);
  return <section className="company-source-accounting" aria-label="Company source accounting review">
    <header><h3>Company-bound source accounting</h3><p>{context.company.display_name} · Choose the retained source scope to inspect its accounting use and structure.</p></header>
    {!context.accounting_sources.length ? <p>No accounting source scope is linked to this company. Retained files alone do not establish accounting coverage.</p> : <label>Source scope
      <select value={selected?.scope.resource_id ?? ""} onChange={event=>setSelectedId(event.target.value)}>
        <option value="">Choose a company-linked source</option>
        {context.accounting_sources.map(source=><option key={source.scope.resource_id} value={source.scope.resource_id}>{source.scope.display_name} · {text(source.scope.attributes.worksheet)} · {text(source.scope.attributes.observed_from)} to {text(source.scope.attributes.observed_through)}</option>)}
      </select>
    </label>}
    {selected && <>
      <h4>{selected.scope.display_name}</h4>
      <p>Worksheet: {worksheet || "Not retained"} · Observed dates: {text(attrs?.observed_from) || "Not retained"} to {text(attrs?.observed_through) || "Not retained"}. Date extent does not establish completeness.</p>
      {selected.bindings.length ? selected.bindings.map(binding=>{
        const status=selected.binding_eligibility?.[binding.version_id];
        return <p key={binding.version_id}><strong>{readable(status?.state ?? "ELIGIBILITY_NOT_CHECKED")}</strong> · {status?.reason ?? "Current accounting eligibility has not been checked."}{status?.checked_at && ` Checked ${new Date(status.checked_at).toLocaleString()}.`}</p>;
      }) : <p>No reviewed accounting use is linked to this source scope.</p>}
      <div className="company-source-accounting-actions"><button type="button" onClick={()=>onInspect(selected.scope)}>Inspect source scope</button>{onTrace&&<button type="button" onClick={()=>onTrace(selected.scope)}>Trace evidence</button>}{onHistory&&<button type="button" onClick={()=>onHistory(selected.scope)}>Scope history</button>}</div>
      <details><summary>Retained source references</summary><p>Scope: {selected.scope.resource_id} · {selected.scope.version_id}</p><p>Source: {documentId || "Not retained"} · Profile: {profile || "Not retained"}</p></details>
      {!available ? <p role="status">{!matchingCompany ? "The retained scope does not establish this selected company. Accounting context cannot be opened." : !supported ? "This retained source profile is not supported by the accounting context workbench." : "The retained source document or worksheet reference is missing."}</p> :
        <SourceAccountingContext key={`${companyId}:${selected.scope.version_id}:${documentId}:${worksheet}:${profile}`} token={token} documentId={documentId} sheet={worksheet} profile={profile} companyId={companyId} canPropose={canPropose} onProposal={onProposal} onInspectResource={onInspectResource} onTraceResource={onTraceResource} compactCompanyIdentity/>}
    </>}
  </section>;
}
