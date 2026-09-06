"use client";
import type {ReactNode} from "react";
import {ArrowRight,Buildings,ClockCounterClockwise,ShieldCheck} from "@phosphor-icons/react";
import type {CanonicalResource,HistorySearchResult} from "@finai/contracts";
import type {Context} from "./company-workspace";
import {displayName} from "./display-name";
import "./executive-overview.css";

type ResourceAction=(resource:CanonicalResource,knownAt:string)=>void;
type Props={canonicalContext?:Context|null;recentResult?:HistorySearchResult|null;contextError?:string;recentError?:string;companyId?:string;
 onInspect?:ResourceAction;onTrace?:ResourceAction;onHistory?:ResourceAction;onRegulation?:()=>void;onAccounting?:()=>void;
 onData:()=>void;onCompanies:()=>void;onOntology:()=>void;operationalPanel?:ReactNode;
 company?:string;period?:string;currency?:string;resources?:CanonicalResource[];resourcesAvailable?:boolean};
const human=(value:string)=>value.replace(/([a-z])([A-Z])/g,"$1 $2").replaceAll("_"," ").toLowerCase();
const stamp=(value:string)=>Number.isFinite(Date.parse(value))?new Date(value).toLocaleString():"Not retained";

export default function ExecutiveOverview({canonicalContext=null,recentResult=null,contextError="",recentError="",companyId="",onInspect,onTrace,onHistory,onRegulation,onAccounting,onData,onCompanies,onOntology,operationalPanel}:Props) {
 const context=canonicalContext?.company.resource_id===companyId?canonicalContext:null;
 const incompleteLedgers=context?.ledgers.filter(row=>!row.ready)??[];
 const issues=context?[
  ...(!context.ledgers.length?[{title:"Accounting context is not established",reason:"No accepted ledger is linked to this company. Books, periods and monetary meaning need governed configuration.",action:"Review accounting context",run:onAccounting??onCompanies}]:[]),
  ...(incompleteLedgers.length?[{title:"Ledger dependencies need review",reason:"A linked ledger has incomplete chart, calendar, currency, book or period context. Inspect its exact dependencies before financial use.",action:"Inspect accounting dependencies",run:onAccounting??onCompanies}]:[]),
  ...(!context.accounting_sources.length?[{title:"Company accounting sources are not bound",reason:"No source accounting scope is linked to this company. An uploaded file alone does not establish its accounting use.",action:"Explore retained evidence",run:onData}]:[]),
  ...(context.accounting_sources.some(row=>!row.bindings.length)?[{title:"Source interpretation remains unresolved",reason:"A linked source scope has no reviewed accounting-use binding. Review what its amounts and dimensions represent before consuming them.",action:"Review source interpretation",run:onData}]:[]),
  ...(context.accounting_sources.some(row=>row.bindings.some(binding=>binding.attributes.source_use==="ACCOUNTING_INPUT"&&row.binding_eligibility?.[binding.version_id]?.eligible_for_accounting!==true))?[{title:"Declared accounting inputs require a current-use check",reason:"At least one accounting-input declaration is blocked or has no eligibility result. Its reviewed declaration alone cannot authorize financial use.",action:"Inspect source eligibility",run:onData}]:[]),
 ]:[];
 function actions(resource:CanonicalResource,knownAt:string){return <div className="briefing-row-actions">{onInspect&&<button onClick={()=>onInspect(resource,knownAt)}>Inspect</button>}{onTrace&&<button onClick={()=>onTrace(resource,knownAt)}>Trace</button>}{onHistory&&<button onClick={()=>onHistory(resource,knownAt)}>History</button>}</div>;}
 return <div className="executive-briefing">
  <section className="briefing-panel" aria-label="Company briefing">
   <header><div><p className="briefing-eyebrow">COMPANY BRIEFING</p><h2>What needs attention</h2></div><button onClick={onCompanies}><Buildings size={14}/>Company workspace<ArrowRight size={13}/></button></header>
   {!companyId?<div className="briefing-state"><h3>Select the company behind your work</h3><p>Its accepted accounting context, source bindings and retained versions will define this briefing.</p><button onClick={onCompanies}>Choose company</button></div>:contextError?<div className="briefing-state briefing-error" role="alert"><h3>Company readiness unavailable</h3><p>{contextError}</p><button onClick={onCompanies}>Open company context</button></div>:!context?<p className="briefing-state" role="status">Resolving the selected company’s accepted context…</p>:<>
    <div className="briefing-context"><strong>{displayName(context.company.display_name)}</strong><span><ShieldCheck size={13}/>{human(context.accounting_state)}</span></div>
    <div className="briefing-columns"><div className="briefing-priorities">{issues.length?<ul>{issues.map(issue=><li key={issue.title}><h3>{issue.title}</h3><p>{issue.reason}</p><button className="briefing-link" onClick={issue.run}>{issue.action}<ArrowRight size={13}/></button></li>)}</ul>:<div className="briefing-state"><h3>No missing configuration identified by this briefing</h3><p>Financial values and certification require their own source and execution checks.</p><button onClick={onAccounting??onCompanies}>Inspect accounting authority</button></div>}</div>
     <div className="briefing-source-readiness"><h3>How linked sources may be used</h3>{context.accounting_sources.length?<div className="briefing-bindings">{context.accounting_sources.map(source=><section key={source.scope.version_id}><strong>{displayName(source.scope.display_name)}</strong>{source.bindings.length?source.bindings.map(binding=>{const status=source.binding_eligibility?.[binding.version_id];return <div className="briefing-binding" key={binding.version_id}><span>{human(String(binding.attributes.source_use??"Use not declared"))}</span><p className={status?.eligible_for_accounting?"briefing-eligible":"briefing-unresolved"}>{status?human(status.state):"Eligibility not checked"}</p>{status?.reason&&<p>{status.reason}</p>}{status?.checked_at&&<small>Checked {stamp(status.checked_at)}</small>}</div>;}):<p className="briefing-unresolved">No reviewed accounting-use declaration</p>}</section>)}</div>:<p>No accounting source scopes are linked. Source coverage remains to be established.</p>}<button className="briefing-link" onClick={onData}>Investigate sources in Data<ArrowRight size={13}/></button></div>
    </div><footer><span>Configuration readiness is not financial performance or certification. Source eligibility is rechecked at execution.</span><div>{onRegulation&&<button onClick={onRegulation}>Regulatory readiness</button>}<button onClick={onOntology}>Company objects & relationships</button></div></footer>
   </>}
  </section>
  <section className="briefing-panel briefing-records" aria-label="Retained company resources">
   <header><div><p className="briefing-eyebrow">RECORDED EVIDENCE</p><h2>{(recentResult as (HistorySearchResult&{sort?:string})|null)?.sort==="recorded_desc"?"Latest retained versions":"Recorded company resources"}</h2></div><ClockCounterClockwise size={18}/></header>
   {!companyId?<p className="briefing-state">Choose a company to inspect its retained resources.</p>:recentError?<div className="briefing-state briefing-error" role="alert"><p>{recentError}</p><button onClick={onData}>Open resource history</button></div>:!recentResult?<p className="briefing-state" role="status">Loading recorded company versions…</p>:<>
    <p className="briefing-record-note">A newly retained resource or definition is not, by itself, a verified business or financial change.</p>
    {!recentResult.resources.length?<p className="briefing-state">No company resources were returned at this effective/known-time cutoff.</p>:<div className="briefing-table-wrap"><table><thead><tr><th scope="col">Business resource</th><th scope="col">Recorded</th><th scope="col">Definition review</th><th scope="col">Investigate</th></tr></thead><tbody>{recentResult.resources.slice(0,12).map(resource=><tr key={resource.version_id}><th scope="row">{displayName(resource.display_name)}<small>{human(resource.object_type)}</small></th><td><time dateTime={resource.system_from}>{stamp(resource.system_from)}</time><small>Effective {stamp(resource.valid_from)}</small></td><td>{human(resource.authority_state)}<small>{human(resource.evidence_class)}</small></td><td>{actions(resource,recentResult.known_at)}</td></tr>)}</tbody></table></div>}
    <footer><span>Effective {stamp(recentResult.effective_at)} · known at {stamp(recentResult.known_at)}. Up to 12 versions shown.</span><button onClick={onData}>Explore company history<ArrowRight size={13}/></button></footer>
   </>}
  </section>
  {operationalPanel&&<section className="briefing-operational" aria-label="Company operating context">{operationalPanel}</section>}
 </div>;
}
