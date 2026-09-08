"use client";
import {useEffect,useRef,useState,type FormEvent} from "react";
import type {CanonicalResource,CompanyChangesDescriptor,CompanyChangesRequest} from "@finai/contracts";
import {assertCompanyChanges,priorKnowledge} from "./company-changes-state";
import {displayName} from "./display-name";
import "./company-changes.css";

type Props={token:string;companyId:string;validAt:string;knownAt:string;onInspect:(node:CanonicalResource,knownAt:string)=>void;onTrace?:(node:CanonicalResource,knownAt:string)=>void;compact?:boolean};
const labels={ADDED_TO_CONTEXT:"Added to context",REMOVED_FROM_CONTEXT:"No longer in context",CHANGED_VERSION:"Recorded version changed"};
const stamp=(at:string)=>new Date(at).toLocaleString();
export default function CompanyChanges(props:Props){return <Comparison key={`${props.token}:${props.companyId}:${props.validAt}:${props.knownAt}`} {...props}/>;}
function Comparison({token,companyId,validAt,knownAt,onInspect,onTrace,compact=false}:Props){
 const [baseline,setBaseline]=useState(()=>priorKnowledge(knownAt,1)),[query,setQuery]=useState("");
 const [result,setResult]=useState<CompanyChangesDescriptor|null>(null),[error,setError]=useState("");
 const [busy,setBusy]=useState(false),[page,setPage]=useState(0);
 const pending=useRef<AbortController|null>(null);
 useEffect(()=>()=>pending.current?.abort(),[]);
 async function compare(event:FormEvent){
  event.preventDefault();pending.current?.abort();const controller=new AbortController();pending.current=controller;
  const timer=setTimeout(()=>controller.abort(),25000);setBusy(true);setError("");setResult(null);setPage(0);
  const request:CompanyChangesRequest={company_id:companyId,valid_at:validAt,known_at:knownAt,compare_known_at:baseline};
  try{
   const response=await fetch("/api/ontology/company-changes",{method:"POST",headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},body:JSON.stringify(request),cache:"no-store",signal:controller.signal});
   const data=await response.json();if(!response.ok)throw Error(typeof data.detail==="string"?data.detail:"Company comparison is unavailable.");
   assertCompanyChanges(data,request);if(!controller.signal.aborted)setResult(data);
  }catch(failure){if(pending.current===controller)setError(controller.signal.aborted?"Comparison timed out. Retry the same cutoffs.":String(failure));}
  finally{clearTimeout(timer);if(pending.current===controller)setBusy(false);}
 }
 const rows=result?.changes.filter(row=>`${row.before?.display_name??""} ${row.after?.display_name??""} ${row.after?.object_type??row.before?.object_type??""}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))??[];
 const size=compact?5:15;
 return <section className="company-changes" aria-label="Recorded company changes"><header><div><p className="overline">WHAT CHANGED</p><h3>Recorded company context</h3></div><span>Knowledge comparison · effective {stamp(validAt)}</span></header>
  <p>Compare what was known about this company at the same effective time. These changes do not measure financial or operational materiality.</p>
  <form onSubmit={event=>void compare(event)}><label>Earlier knowledge<select aria-label="Earlier knowledge interval" defaultValue="1" onChange={event=>setBaseline(priorKnowledge(knownAt,Number(event.target.value)))}><option value="1">24 hours earlier</option><option value="7">7 days earlier</option><option value="30">30 days earlier</option></select></label><button disabled={busy} type="submit">{busy?"Comparing…":"Compare recorded context"}</button><details><summary>Exact comparison cutoff</summary><label>Known before (with timezone)<input value={baseline} onChange={event=>setBaseline(event.target.value)} maxLength={40}/></label><p>Known after: {knownAt}. Effective time stays {validAt}.</p></details></form>
  {error&&<p className="company-changes-error" role="alert">{error} No no-change conclusion is established.</p>}
  {result&&<><div className="company-changes-toolbar"><span>{stamp(result.compare_known_at)} → {stamp(result.known_at)}</span><label>Find changed resource<input value={query} onChange={event=>{setQuery(event.target.value);setPage(0);}} placeholder="Name or resource type"/></label></div>
   {rows.length?<div className="company-changes-table"><table><thead><tr><th>Company resource</th><th>Recorded change</th><th>Exact evidence</th></tr></thead><tbody>{rows.slice(page*size,(page+1)*size).map(row=><tr key={row.resource_id}><th scope="row">{displayName(row.after?.display_name??row.before!.display_name)}<small>{row.after?.object_type??row.before!.object_type}</small></th><td><span data-kind={row.kind}>{labels[row.kind]}</span>{row.changed_fields.length>0&&<details><summary>Changed fields</summary><ul>{row.changed_fields.map(field=><li key={field}>{field.replace(/^\/attributes\//,"").replace(/^\//,"").replaceAll("~1","/").replaceAll("~0","~").replaceAll("_"," ")}</li>)}</ul></details>}</td><td><div className="company-change-actions">{row.before&&<button onClick={()=>onInspect(row.before!,result.compare_known_at)}>Before</button>}{row.after&&<button onClick={()=>onInspect(row.after!,result.known_at)}>After</button>}{onTrace&&<button onClick={()=>onTrace((row.after??row.before)!,row.after?result.known_at:result.compare_known_at)}>Trace {row.after?"after":"before"}</button>}</div></td></tr>)}</tbody></table></div>:<p className="company-changes-empty">{query?"No recorded changes match this search.":"No changed resources were returned within this explicit company context. This does not establish that nothing changed across the business."}</p>}
   {rows.length>size&&<nav className="company-changes-pager" aria-label="Company change pages"><button disabled={page===0} onClick={()=>setPage(value=>value-1)}>Previous</button><span>{page*size+1}–{Math.min((page+1)*size,rows.length)} of {rows.length}</span><button disabled={(page+1)*size>=rows.length} onClick={()=>setPage(value=>value+1)}>Next</button></nav>}
   <details><summary>Comparison coverage & authority</summary>{result.limitations.map((text,index)=><p key={index}>{text}</p>)}<p>Leaving this context does not mean a resource was deleted or an obligation ended.</p></details></>}
 </section>;
}
