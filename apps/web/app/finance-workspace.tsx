"use client";

import {useEffect,useState} from "react";
import type {CompanyFinancialResults} from "@finai/contracts";
import type {Context} from "./company-workspace";
import PostedMovementReport from "./posted-movement-report";
import SemanticAnalysisWorkspace from "./semantic-analysis-workspace";
import {useSourceReview} from "./source-review-navigation";
import {assertFinanceDiscovery,financeLinkedSelection,type FinanceSelection} from "./finance-discovery-state";
import {sameMetricPin} from "./metric-observation-state";
import {Badge,Empty} from "./g8-ui";
import type {FinanceReportReference} from "./finance-report-reference";
import "./finance-workspace.css";

const recorded=(value:string)=>new Intl.DateTimeFormat(undefined,{dateStyle:"medium",timeStyle:"short"}).format(new Date(value));

type Reference={resource_id:string;version_id:string;known_at?:string};
type Page={valid_at?:string;known_at?:string;after_function_id?:string;after_invocation_id?:string;revision:number};
export default function FinanceWorkspace({active=false,onClearReport,initialReport,token,companyId,context,onContext,onInspect,onTrace}:{active?:boolean;onClearReport:()=>void;initialReport:FinanceReportReference|null;token:string;companyId:string;context:Context|null;contextError:string;onContext:()=>void;onInspect:(reference:Reference)=>void;onTrace:(reference:Reference)=>void}){
 const openSourceReview=useSourceReview();
 const [page,setPage]=useState<Page>({revision:0});
 const [response,setResponse]=useState<{key:string;data:CompanyFinancialResults|null;error:string}|null>(null);
 const [selection,setSelection]=useState<FinanceSelection|null>(null);
 const [selectionError,setSelectionError]=useState("");
 const [capabilityId,setCapabilityId]=useState("");
 const key=JSON.stringify([companyId,page]);
 const data=response?.key===key?response.data:null,error=response?.key===key?response.error:"";
 useEffect(()=>{
  if(!active||!companyId)return;
  const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),25000);
  const params=new URLSearchParams({company_id:companyId});
  for(const field of ["valid_at","known_at","after_function_id","after_invocation_id"] as const){const value=page[field];if(value)params.set(field,value);}
  void fetch(`/api/ontology/company-financial-results?${params}`,{headers:{Authorization:`Bearer ${token}`},cache:"no-store",signal:controller.signal}).then(async result=>{
   const value=await result.json();if(!result.ok)throw Error(result.status===401||result.status===403||result.status===404?"Financial results are unavailable in this company and access scope.":typeof value.detail==="string"?value.detail:`Financial discovery unavailable (${result.status}).`);
   assertFinanceDiscovery(value,companyId,page.valid_at&&page.known_at?{valid_at:page.valid_at,known_at:page.known_at}:undefined);
   if(!controller.signal.aborted)setResponse({key,data:value,error:""});
  }).catch(cause=>{if(!controller.signal.aborted)setResponse({key,data:null,error:String(cause)});else if(controller.signal.reason!=="inactive")setResponse({key,data:null,error:"Financial discovery timed out. Retry this company."});}).finally(()=>clearTimeout(timer));
  return()=>{clearTimeout(timer);controller.abort("inactive");};
 },[active,token,companyId,key,page]);
 useEffect(()=>{
  if(!active)return;let disposed=false;
  const restore=()=>{if(location.pathname!=="/")return;try{setSelection(financeLinkedSelection(new URL(location.href),companyId,initialReport));setSelectionError("");setCapabilityId(new URL(location.href).searchParams.get("finance_function")??"");}catch(cause){setSelection(null);setSelectionError(String(cause));}};
  queueMicrotask(()=>{if(!disposed)restore();});window.addEventListener("popstate",restore);
  return()=>{disposed=true;window.removeEventListener("popstate",restore);};
 },[active,companyId,initialReport]);
 function choose(invocationId:string,functionVersion=""){
  if(!active)return;window.dispatchEvent(new Event("g8:capture-source-review"));
  const result=data?.results.find(item=>item.invocation_id===invocationId);
  const url=new URL(location.href);url.searchParams.delete("finance_analysis_view");url.searchParams.delete("finance_result");url.searchParams.delete("finance_function");
  if(result)url.searchParams.set("finance_result",JSON.stringify({companyId,invocationId,receiptHash:result.receipt_hash}));
  if(functionVersion)url.searchParams.set("finance_function",functionVersion);
  history.pushState(history.state,"",url);
  setSelection(result?{invocationId,receiptHash:result.receipt_hash}:null);setSelectionError("");setCapabilityId(functionVersion);onClearReport();
 }
 const retained=data?.results.find(item=>item.invocation_id===selection?.invocationId);
 const capability=data?.capabilities.find(item=>item.function.version_id===capabilityId);
 const source=capability?.source_scope?data?.sources.find(item=>sameMetricPin(item.scope,capability.source_scope)):null;
 const binding=source?.bindings.find(item=>sameMetricPin(item,capability?.accounting_binding));
 if(!companyId)return <Empty title="Choose a company">Select a company to review its available financial results.</Empty>;
 if(selectionError)return <Empty title="Retained result reference unavailable" action="Clear invalid result reference" onAction={()=>choose("")}>{selectionError}</Empty>;
 if(error)return <section role="alert"><p>{error}</p><button onClick={()=>setPage(p=>({...p,revision:p.revision+1}))}>Retry financial discovery</button><button onClick={onContext}>Review company context</button></section>;
 if(!data)return <p role="status">Loading retained financial results and available calculations…</p>;
 const name=(id:unknown)=>context?.company.resource_id===companyId?context.ledgers.find(item=>item.currency_id?.resource_id===id)?.currency_id?.display_name??"Declared currency":"Declared currency";
 return <section className="finance-workspace" aria-label="Company financial results">
  <header><label>Retained result<select value={selection?.invocationId??""} onChange={event=>choose(event.target.value)}><option value="">Choose a retained result</option>{selection&&!retained&&<option value={selection.invocationId}>Linked retained result · original context</option>}{data.results.map(result=><option key={result.invocation_id} value={result.invocation_id}>{result.reopen==="SEMANTIC_ANALYSIS"?"Source movements":"Accepted journal movements"} · {result.source.sheet??"Retained evidence"} · {recorded(result.recorded_at)}</option>)}</select></label><button onClick={onContext}>Accounting context</button></header>
  {(data.next_function_cursor||data.next_invocation_cursor)&&<div className="finance-pagination"><span>More discovery entries are available. This page is not complete company coverage.</span>{data.next_invocation_cursor&&<button onClick={()=>setPage(p=>({...p,valid_at:data.valid_at,known_at:data.known_at,after_invocation_id:data.next_invocation_cursor!}))}>More retained results</button>}{data.next_function_cursor&&<button onClick={()=>setPage(p=>({...p,valid_at:data.valid_at,known_at:data.known_at,after_function_id:data.next_function_cursor!}))}>More available calculations</button>}</div>}
  <details className="finance-capabilities"><summary>Available calculations ({data.capabilities.length}) · reviewed source context</summary>
   <p>New calculations recheck their exact dependencies. Opening a retained result above never runs a calculation again.</p>
   {data.capabilities.map(item=><div key={item.function.version_id}><strong>{item.display_name}</strong> <Badge tone={item.state==="DISCOVERED"?"neutral":"warning"}>{item.state==="DISCOVERED"?"Available for guarded review":"Accounting binding blocked"}</Badge><p>{item.reason??(item.required_input==="EXACT_ACCEPTED_MOVEMENTS_INPUT"?"Select exact accepted journal movements in accounting context before running this calculation.":"Uses the reviewed source and accounting binding returned by the canonical catalog.")}</p>{item.required_input==="REVIEWED_SOURCE_CONTEXT"&&<button disabled={item.state!=="DISCOVERED"} onClick={()=>{choose("",item.function.version_id);}}>Review new calculation</button>}{item.required_input==="EXACT_ACCEPTED_MOVEMENTS_INPUT"&&<button onClick={onContext}>Review accepted journal input</button>}<details><summary>Advanced capability reference</summary><pre>{JSON.stringify(item,null,2)}</pre><button onClick={()=>onInspect(item.function)}>Inspect Function definition</button></details></div>)}
   {!data.capabilities.length&&<p>No supported calculation was found in this catalog page.</p>}
   {data.unavailable_capabilities.map((item,index)=><p key={index} role="status">Calculation unavailable: {item.reason}</p>)}
  </details>
  {selection&&(retained?.reopen!=="FUNCTION_HISTORY")&&<div className="finance-retained-result"><SemanticAnalysisWorkspace key={selection.invocationId} owner="finance" active={active} expectedReceiptHash={selection.receiptHash} token={token} companyId={companyId} invocationId={selection.invocationId} onInspect={onInspect} onOpenSourceReview={openSourceReview}/></div>}
  {selection&&retained?.reopen==="FUNCTION_HISTORY"&&<section><h3>Retained accepted journal calculation</h3><p>This calculation has no supported worksheet projection yet. Its original receipt and cutoffs remain available below; no replacement source calculation has been run.</p><details><summary>Advanced · retained calculation reference</summary><pre>{JSON.stringify(retained,null,2)}</pre><button onClick={()=>onInspect({...retained.function,known_at:retained.known_at})}>Inspect retained Function definition</button></details></section>}
  {!selection&&capability&&source&&binding&&<PostedMovementReport active={active} key={capability.function.version_id} token={token} contextKey={capability.function.version_id} functions={[{...capability.function,display_name:capability.display_name}]} currency={name(binding.attributes.currency_id)} eligible={capability.state==="DISCOVERED"} expectedSource={{company_id:companyId,document_id:capability.document_id!,scope_id:source.scope.resource_id,binding_id:binding.resource_id,binding_version_id:binding.version_id,ledger_id:String(binding.attributes.ledger_id),book_id:String(binding.attributes.book_id),period_id:String(binding.attributes.period_id),currency_id:String(binding.attributes.currency_id)}} onInspectFunction={onInspect} onTraceFunction={onTrace}/>}
  {!selection&&!capability&&<Empty title={data.results.length?"Choose a retained financial result":"No retained financial result in this page"}>{data.results.length?"Open its worksheet to review rows, filters and original evidence.":"Review the available calculations or connect a supported financial source. No financial values have been substituted."}</Empty>}
 </section>;
}
