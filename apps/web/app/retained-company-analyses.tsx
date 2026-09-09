"use client";
import {useCallback,useEffect,useRef,useState} from "react";
import type {AnalysisProjection,RetainedAnalysisPage,RetainedAnalysisReference} from "@finai/contracts";
import {assertRetainedAnalysisPage,retainedAnalysisTarget,retainedAnalysisRequestCurrent} from "./retained-company-analyses-state";
import {projectionEndpoint} from "./analysis-projection-identity";
import {useSourceReview} from "./source-review-navigation";
import {displayName} from "./display-name";
import "./retained-company-analyses.css";
const stamp=(value:string)=>new Date(value).toLocaleString();
type Props={token:string;companyId:string};
export default function RetainedCompanyAnalyses(props:Props){return <RetainedAnalyses key={JSON.stringify([props.token,props.companyId])} {...props}/>;}
function RetainedAnalyses({token,companyId}:Props){
 const open=useSourceReview(),generation=useRef(0),request=useRef<AbortController|null>(null);
 const [pages,setPages]=useState<RetainedAnalysisPage[]>([]),[index,setIndex]=useState(0),[busy,setBusy]=useState(true),[opening,setOpening]=useState<string|null>(null),[error,setError]=useState("");
 const cancel=useCallback(()=>{generation.current++;request.current?.abort();request.current=null;},[]);
 const load=useCallback(async(cursor:string|null,recordedBefore:string|null,reset=false)=>{
  cancel();const ticket=generation.current,controller=new AbortController();request.current=controller;
  setOpening(null);setBusy(true);setError("");if(reset){setPages([]);setIndex(0);}const timer=setTimeout(()=>controller.abort(),25000);
  try{const query=new URLSearchParams({company_id:companyId});if(cursor)query.set("cursor",cursor);
   const response=await fetch(`/api/ontology/retained-analyses?${query}`,{headers:{Authorization:`Bearer ${token}`},cache:"no-store",signal:controller.signal});
   const page=await response.json();if(!response.ok)throw Error(typeof page.detail==="string"?page.detail:"Retained analysis discovery is unavailable.");
   assertRetainedAnalysisPage(page,companyId,cursor&&recordedBefore?{cursor,recordedBefore}:undefined);
   if(retainedAnalysisRequestCurrent(ticket,generation.current,controller.signal)){setPages(previous=>reset?[page]:[...previous,page]);if(!reset)setIndex(previous=>previous+1);}
  }catch(failure){if(ticket===generation.current)setError(controller.signal.aborted?"Retained analysis discovery timed out. Retry the same company.":failure instanceof Error?failure.message:"Retained analyses are unavailable.");}
  finally{clearTimeout(timer);if(ticket===generation.current)setBusy(false);}
 },[cancel,token,companyId]);
 useEffect(()=>{let disposed=false;queueMicrotask(()=>{if(!disposed)void load(null,null,true);});return()=>{disposed=true;cancel();};},[load,cancel]);
 const page=pages[index];
 function visit(next:number){cancel();setOpening(null);setError("");setBusy(false);setIndex(next);}
 async function review(item:RetainedAnalysisReference){
  if(busy||!page?.items.includes(item))return;cancel();const ticket=generation.current,controller=new AbortController();request.current=controller;setOpening(item.invocation_id);setError("");const timer=setTimeout(()=>controller.abort(),25000);
  try{const response=await fetch(projectionEndpoint(),{method:"POST",headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},body:JSON.stringify({company_id:companyId,invocation_id:item.invocation_id}),cache:"no-store",signal:controller.signal});
   const value=await response.json();if(!response.ok)throw Error(typeof value.detail==="string"?value.detail:"This retained source review could not be opened.");
   const target=retainedAnalysisTarget(value as AnalysisProjection,item,companyId);
   if(retainedAnalysisRequestCurrent(ticket,generation.current,controller.signal))open(target);
  }catch(failure){if(ticket===generation.current)setError(controller.signal.aborted?"Source review verification timed out. The retained reference remains available.":failure instanceof Error?failure.message:"Source review is unavailable.");}
  finally{clearTimeout(timer);if(ticket===generation.current)setOpening(null);}
 }
 return <section className="retained-company-analyses" aria-label="Discover retained company analyses"><header><div><h3>Retained company analyses</h3><p>Find existing analyses, including results not pinned on this device.</p></div><button onClick={()=>void load(null,null,true)}>Refresh discovery</button></header>
  <p className="retained-analysis-limit">Object tables and grouped source observations only. Each result retains its own company version and effective / known times, separate from the company workspace snapshot. Opening source review verifies the exact retained result and shows available evidence and its limitations. Discovery grants no financial or current-use authority.</p>
  {error&&<p role="alert">{error} <button onClick={()=>void load(null,null,true)}>Restart discovery</button></p>}
  {busy?<p role="status">Reading a bounded page of retained invocation references...</p>:page&&<>
   <p className="retained-analysis-coverage">Page {index+1}: inspected {page.inspected_count} retained candidates; listed {page.returned_count}; not listed {page.not_listed_count}. Observed {stamp(page.observed_at)}. Scan includes records retained by {stamp(page.recorded_before)}.</p>
   {page.items.length?<ul>{page.items.map(item=><li key={item.invocation_id}><div><h4>{displayName(item.title)}</h4><p>{item.projection_contract==="semantic-analysis/2"?"Object table":"Grouped source observations"} · Retained {stamp(item.recorded_at)}</p><p>Effective {stamp(item.valid_at)} · Known {stamp(item.known_at)}</p></div><button disabled={opening!==null} onClick={()=>void review(item)}>{opening===item.invocation_id?"Verifying exact source review...":"Open source review"}</button><details><summary>Advanced: exact retained references</summary><dl><dt>Invocation</dt><dd>{item.invocation_id}</dd><dt>Function</dt><dd>{item.function.resource_id} / {item.function.version_id} / {item.function.content_hash}</dd><dt>Company</dt><dd>{item.company.resource_id} / {item.company.version_id} / {item.company.content_hash}</dd><dt>Receipt / run</dt><dd>{item.receipt_hash} / {item.run_id}</dd></dl></details></li>)}</ul>:<p>No eligible analysis was listed in this bounded scan. Other retained analyses or unsupported result shapes may exist.{page.next_cursor?" Continue to the next scan page.":" This scan has no continuation; it does not establish complete company coverage."}</p>}
   <nav aria-label="Retained analysis pages"><button disabled={index===0} onClick={()=>visit(index-1)}>Previous page</button><span>Page {index+1}</span><button disabled={!pages[index+1]&&!page.next_cursor} onClick={()=>pages[index+1]?visit(index+1):void load(page.next_cursor,page.recorded_before)}>Next scan page</button></nav>
  </>}
 </section>;
}
