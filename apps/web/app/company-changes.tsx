"use client";
import {Fragment,useEffect,useRef,useState,type FormEvent} from "react";
import type {CanonicalResource,CompanyChangesDescriptor,CompanyChangesRequest,CompanyContextChange} from "@finai/contracts";
import {assertCompanyChanges,priorKnowledge} from "./company-changes-state";
import {recordedFieldChanges,type RecordedChangeValue} from "./company-change-values";
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
   {rows.length?<div className="company-changes-table"><table><thead><tr><th>Company resource</th><th>Recorded change</th><th>Exact evidence</th></tr></thead><tbody>{rows.slice(page*size,(page+1)*size).map(row=><Fragment key={row.resource_id}><tr><th scope="row">{displayName(row.after?.display_name??row.before!.display_name)}<small>{row.after?.object_type??row.before!.object_type}</small></th><td><span data-kind={row.kind}>{labels[row.kind]}</span></td><td><div className="company-change-actions">{row.before&&<button onClick={()=>onInspect(row.before!,result.compare_known_at)}>Inspect before</button>}{row.after&&<button onClick={()=>onInspect(row.after!,result.known_at)}>Inspect after</button>}{onTrace&&row.before&&<button onClick={()=>onTrace(row.before!,result.compare_known_at)}>Trace before</button>}{onTrace&&row.after&&<button onClick={()=>onTrace(row.after!,result.known_at)}>Trace after</button>}</div></td></tr>{row.kind==="CHANGED_VERSION"&&<tr className="company-change-comparison-row"><td colSpan={3}><FieldComparison change={row} beforeKnown={result.compare_known_at} afterKnown={result.known_at}/></td></tr>}</Fragment>)}</tbody></table></div>:<p className="company-changes-empty">{query?"No recorded changes match this search.":"No changed resources were returned within this explicit company context. This does not establish that nothing changed across the business."}</p>}
   {rows.length>size&&<nav className="company-changes-pager" aria-label="Company change pages"><button disabled={page===0} onClick={()=>setPage(value=>value-1)}>Previous</button><span>{page*size+1}–{Math.min((page+1)*size,rows.length)} of {rows.length}</span><button disabled={(page+1)*size>=rows.length} onClick={()=>setPage(value=>value+1)}>Next</button></nav>}
   <details><summary>Comparison coverage & authority</summary>{result.limitations.map((text,index)=><p key={index}>{text}</p>)}<p>Leaving this context does not mean a resource was deleted or an obligation ended.</p></details></>}
 </section>;
}

function RecordedValue({value}:{value:RecordedChangeValue}) {
 return <div className="company-change-value" data-value-kind={value.kind}><small>{value.state==="VALUE"?({text:"Text",number:"Number",boolean:"Boolean",technical:"Technical reference",structured:"Structured value",unavailable:"Precision unavailable"} as Record<string,string>)[value.kind]:value.state==="NULL"?"Explicit null":"Absent field"}</small><span>{value.text}</span>{(value.advanced!==undefined||value.limited)&&<details><summary>Advanced · retained value</summary>{value.advanced!==undefined&&<pre>{value.advanced}</pre>}{value.limited&&<p>{value.limitation??"Inline display is bounded. Use Inspect before or Inspect after for the retained version; the displayed excerpt is not the complete value."}</p>}</details>}</div>;
}
function FieldComparison({change,beforeKnown,afterKnown}:{change:CompanyContextChange;beforeKnown:string;afterKnown:string}) {
 const [visited,setVisited]=useState(false),[page,setPage]=useState(0);
 let rows:ReturnType<typeof recordedFieldChanges>=[],error="";
 if(visited)try{rows=recordedFieldChanges(change);}catch(failure){error=failure instanceof Error?failure.message:"Recorded fields are unavailable for exact comparison.";}
 const size=10,current=Math.min(page,Math.max(0,Math.ceil(rows.length/size)-1));
 return <details className="company-change-comparison" onToggle={event=>{if(event.currentTarget.open)setVisited(true);}}><summary>Compare recorded fields{change.changed_fields.length?` · ${change.changed_fields.length}`:""}</summary>{visited&&(error?<p className="company-changes-error" role="alert">{error}</p>:rows.length?<><p>Fields identified by the retained comparison. Earlier and later values use the same effective time; no financial difference or materiality is calculated.</p><div className="company-change-fields"><table><caption>Recorded values · {displayName(change.after!.display_name)}</caption><thead><tr><th scope="col">Field</th><th scope="col">Earlier knowledge<small>{stamp(beforeKnown)}</small></th><th scope="col">Later knowledge<small>{stamp(afterKnown)}</small></th></tr></thead><tbody>{rows.slice(current*size,(current+1)*size).map(row=><tr key={row.pointer}><th scope="row">{row.label}</th><td><RecordedValue value={row.before}/></td><td><RecordedValue value={row.after}/></td></tr>)}</tbody></table></div>{rows.length>size&&<nav className="company-changes-pager" aria-label="Recorded field pages"><button disabled={current===0} onClick={()=>setPage(current-1)}>Previous fields</button><span>{current*size+1}–{Math.min((current+1)*size,rows.length)} of {rows.length} declared fields</span><button disabled={(current+1)*size>=rows.length} onClick={()=>setPage(current+1)}>Next fields</button></nav>}<details><summary>Advanced · comparison references</summary><p>Earlier knowledge {beforeKnown} · later knowledge {afterKnown}</p><pre>{JSON.stringify({resource_id:change.resource_id,before:{version_id:change.before!.version_id,content_hash:change.before!.content_hash},after:{version_id:change.after!.version_id,content_hash:change.after!.content_hash},displayed_field_paths:rows.slice(current*size,(current+1)*size).map(row=>row.pointer)},null,2)}</pre></details></>:<p>The retained version changed without changes to the compared metadata or top-level attributes. Inspect the exact versions for their evidence; no unchanged-business conclusion is established.</p>)}</details>;
}
