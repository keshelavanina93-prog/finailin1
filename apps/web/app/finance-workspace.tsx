"use client";

import {useEffect,useState} from "react";
import type {CanonicalResource} from "@finai/contracts";
import type {Context} from "./company-workspace";
import PostedMovementReport,{type PostedFunction} from "./posted-movement-report";
import {Badge,Empty} from "./g8-ui";
import "./finance-workspace.css";

import type {FinanceReportReference} from "./finance-report-reference";

type ReviewedContext={scope:CanonicalResource|null;binding:CanonicalResource|null;observed:Record<string,string>;posted_movement_functions?:PostedFunction[];candidates:Record<string,CanonicalResource[]>;accounting_eligibility?:{eligible_for_accounting:boolean;reason:string};company_binding?:{accepted:boolean;company:{resource_id:string}|null}};
type Reference={resource_id:string;version_id:string;known_at?:string};
export default function FinanceWorkspace({active=false,onClearReport,initialReport,token,companyId,context,contextError,onContext,onInspect,onTrace}:{active?:boolean;onClearReport:()=>void;initialReport:FinanceReportReference|null;token:string;companyId:string;context:Context|null;contextError:string;onContext:()=>void;onInspect:(reference:Reference)=>void;onTrace:(reference:Reference)=>void}){
  const sources=context?.company.resource_id===companyId?context.accounting_sources.filter(item=>item.scope.attributes.source_profile==="seg_expense_base"):[];
  const [choice,setChoice]=useState("");const [loaded,setLoaded]=useState<{key:string;context:ReviewedContext}|null>(null);
  const [error,setError]=useState("");const [revision,setRevision]=useState(0);
  const source=sources.find(item=>item.scope.resource_id===(choice||(initialReport?.companyId===companyId?initialReport.scopeId:"")))??(sources.length===1?sources[0]:null);
  const key=JSON.stringify([companyId,source?.scope.resource_id,source?.scope.version_id,revision]);
  const accounting=loaded?.key===key?loaded.context:null;
  useEffect(()=>{
    if(!source)return;
    const controller=new AbortController();const scope=source.scope;
    void fetch(`/api/ontology/source-documents/${encodeURIComponent(String(scope.attributes.document_id))}/accounting-context/inspect`,{method:"POST",headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},body:JSON.stringify({company_id:companyId,sheet:scope.attributes.worksheet,profile:scope.attributes.source_profile}),signal:controller.signal}).then(async response=>{
      const data=await response.json();if(!response.ok)throw Error(typeof data.detail==="string"?data.detail:`Reviewed accounting context unavailable (${response.status}).`);
      if(data.scope?.resource_id!==scope.resource_id||data.scope?.attributes.legal_entity_id!==companyId||data.company_binding?.accepted!==true||data.company_binding?.company?.resource_id!==companyId)throw Error("The reviewed source does not match the selected company. Refresh its accounting context.");
      if(!controller.signal.aborted){setLoaded({key,context:data});setError("");}
    }).catch(cause=>{if(!controller.signal.aborted)setError(String(cause));});
    return()=>controller.abort();
  },[token,companyId,key,source]);
  if(!companyId)return <Empty title="Choose a company">Select the company whose reviewed financial sources you want to analyse.</Empty>;
  if(contextError)return <p role="alert">{contextError}<button onClick={onContext}>Review company context</button></p>;
  if(!context)return <p role="status">Loading the company’s reviewed reporting context…</p>;
  if(initialReport&&initialReport.companyId!==companyId)return <Empty title="This report belongs to another company" action="Return to this company’s reports" onAction={onClearReport}>Select its original company to open the retained report. No report values have been shown in this company context.</Empty>;
  if(!sources.length)return <Empty title="No reviewed account-movement source is connected" action="Review company accounting context" onAction={onContext}>This company has no supported retained source for this report. No substitute company or financial values have been selected.</Empty>;
  const name=(field:string,type:string)=>accounting?.candidates[type]?.find(item=>item.resource_id===accounting.binding?.attributes[field])?.display_name??"Not established";
  const binding=accounting?.binding;
  return <section className="finance-workspace" aria-label="Company finance reports">
    <header><div><h2>Account movements</h2><p>Reviewed source postings, account breakdown and original evidence.</p></div><button onClick={onContext}>Review accounting context</button></header>
    <label>Source and observed period<select value={source?.scope.resource_id??""} onChange={event=>{setChoice(event.target.value);onClearReport();setError("");}}><option value="">Choose a retained source</option>{sources.map(item=><option key={item.scope.version_id} value={item.scope.resource_id}>{item.scope.display_name} · {String(item.scope.attributes.worksheet)} · {String(item.scope.attributes.observed_from)}–{String(item.scope.attributes.observed_through)}</option>)}</select></label>
    {source&&!accounting&&!error&&<p role="status">Checking the source’s reviewed accounting interpretation…</p>}
    {error&&<p role="alert">{error}<button onClick={()=>{setError("");setRevision(value=>value+1);}}>Retry source context</button></p>}
    {accounting&&binding&&<>
      <dl className="finance-report-context"><div><dt>Ledger</dt><dd>{name("ledger_id","Ledger")}</dd></div><div><dt>Book</dt><dd>{name("book_id","AccountingBook")}</dd></div><div><dt>Period</dt><dd>{name("period_id","FiscalPeriod")}</dd></div><div><dt>Currency</dt><dd>{name("currency_id","Currency")}</dd></div></dl>
      <p><Badge tone={accounting.accounting_eligibility?.eligible_for_accounting?"good":"warning"}>{accounting.accounting_eligibility?.eligible_for_accounting?"Reviewed for guarded use":"Accounting use unavailable"}</Badge> {accounting.accounting_eligibility?.reason}</p>
      <PostedMovementReport active={active} key={`${key}:${binding.version_id}`} initialInvocationId={initialReport?.scopeId===source?.scope.resource_id?initialReport?.invocationId:undefined} token={token} contextKey={`${key}:${binding.version_id}`} currency={name("currency_id","Currency")} functions={accounting.posted_movement_functions??[]} eligible={accounting.accounting_eligibility?.eligible_for_accounting===true} expectedSource={{company_id:companyId,ledger_id:String(binding.attributes.ledger_id),book_id:String(binding.attributes.book_id),period_id:String(binding.attributes.period_id),currency_id:String(binding.attributes.currency_id),document_id:String(source!.scope.attributes.document_id),scope_id:source!.scope.resource_id,binding_id:binding.resource_id,binding_version_id:binding.version_id}} onInspectFunction={onInspect} onTraceFunction={onTrace}/>
      <details><summary>Reviewed source interpretation</summary><p>{String(binding.attributes.rationale??"No rationale retained")}</p><button onClick={()=>onTrace(binding)}>Show accounting context trace</button></details>
    </>}
    {accounting&&!binding&&<p role="status">A reviewed accounting-use decision is required before this source can produce a financial result.</p>}
  </section>;
}
