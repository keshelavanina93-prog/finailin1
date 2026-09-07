"use client";

import {Fragment,useEffect,useRef,useState} from "react";
import type {CanonicalResource,ResourceProposal,ResourceProposalDetail,RollbackRequest} from "@finai/contracts";
import "./definition-restoration.css";
import {restorationInstant} from "./definition-restoration-time";

type Props={token:string;selected:CanonicalResource;canPropose?:boolean;onProposal?:(id:string)=>void};
const uuid=(value:unknown)=>typeof value==="string"&&/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value);
const stable=(value:unknown):string=>JSON.stringify(value,(_,item)=>item&&typeof item==="object"&&!Array.isArray(item)?Object.fromEntries(Object.entries(item).sort(([a],[b])=>a.localeCompare(b))):item);
export default function DefinitionRestoration(props:Props) {
 return <Restoration key={`${props.token}:${props.selected.resource_id}:${props.selected.version_id}`} {...props}/>;
}
function Restoration({token,selected,canPropose=false,onProposal}:Props) {
 const [effective,setEffective]=useState("");const [rationale,setRationale]=useState("");
 const [request,setRequest]=useState<RollbackRequest|null>(null);
 const [draft,setDraft]=useState<ResourceProposal|null>(null);const [head,setHead]=useState<CanonicalResource|null>(null);
 const [receipt,setReceipt]=useState<string|null>(null);const [busy,setBusy]=useState(false);const [error,setError]=useState("");
 const active=useRef<AbortController|null>(null);
 useEffect(()=>()=>{active.current?.abort();active.current=null;},[]);
 async function perform(submit=false) {
  if(!canPropose||busy||submit&&(!draft||!head))return;
  let frozen=request;
  if(!submit&&!frozen){
   if(!restorationInstant(effective)||rationale.trim().length<10){setError("Enter a valid calendar timestamp with seconds, timezone, and at most six fractional digits, and a reason of at least ten characters.");return;}
   frozen={proposal_id:crypto.randomUUID(),versions:{[selected.resource_id]:selected.version_id},rationale:rationale.trim(),valid_from:effective};setRequest(frozen);
  }
  const controller=new AbortController();active.current=controller;const timer=setTimeout(()=>controller.abort(),20000);
  setBusy(true);setError("");
  try {
   const response=await fetch(submit?"/api/ontology/proposals":"/api/ontology/rollback-proposal",{method:"POST",headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},body:JSON.stringify(submit?draft:frozen),signal:controller.signal});
   const data=await response.json();
   if(!response.ok)throw Error(typeof data.detail==="string"?data.detail:`Restoration is unavailable (${response.status}).`);
   if(submit){
    const retained=data as ResourceProposalDetail;
    if(retained.proposal?.proposal_id!==draft!.proposal_id)throw Error("The submission response did not identify the exact restoration proposal. Retry the same submission to confirm it.");
    if(active.current===controller&&!controller.signal.aborted){setReceipt(retained.proposal.proposal_id);onProposal?.(retained.proposal.proposal_id);}
   }else{
    const value=data as ResourceProposal;const mutation=value.mutations?.[0];
    if(value.proposal_id!==frozen!.proposal_id||value.mutations?.length!==1||mutation.resource_id!==selected.resource_id||mutation.object_type!=="ObjectSetDefinition"||!uuid(mutation.expected_version_id)||
      value.restores_versions?.[selected.resource_id]!==selected.version_id||Object.keys(value.restores_versions).length!==1||
      mutation.display_name!==selected.display_name||stable(mutation.attributes)!==stable(selected.attributes)||mutation.evidence_class!==selected.evidence_class||
      (!restorationInstant(mutation.valid_from)||restorationInstant(mutation.valid_from)!==restorationInstant(frozen!.valid_from)))throw Error("The draft does not match the selected retained definition and requested effective time.");
    const current=await fetch(`/api/ontology/resources/${selected.resource_id}`,{headers:{Authorization:`Bearer ${token}`},signal:controller.signal,cache:"no-store"});
    const currentData=await current.json();
    if(!current.ok)throw Error("The expected current definition is unavailable; the draft cannot be compared safely.");
    const resource:CanonicalResource=currentData.resource;
    if(resource?.resource_id!==selected.resource_id||resource.version_id!==mutation.expected_version_id||resource.object_type!=="ObjectSetDefinition")throw Error("The current definition changed while preparing the draft. Discard this draft and prepare a new comparison.");
    if(active.current===controller&&!controller.signal.aborted){setDraft(value);setHead(resource);}
   }
  }catch(failure){if(active.current===controller)setError(controller.signal.aborted?"The response timed out. Retry the same request; submission may already be retained.":failure instanceof Error?failure.message:"Restoration unavailable");}
  finally{clearTimeout(timer);if(active.current===controller){active.current=null;setBusy(false);}}
 }
 if(selected.object_type!=="ObjectSetDefinition"||selected.authority_state!=="APPROVED")return null;
 return <details className="definition-restoration"><summary>Restore this saved Object Set through review</summary>
  <p>Restore the selected retained query as a new reviewed version. Historical records remain unchanged. Dependencies are not restored automatically; changed dependencies can block this proposal.</p>
  {!canPropose?<p>This identity does not have permission to propose a restoration.</p>:<>
   <label>Effective from — explicit timezone<input value={effective} disabled={busy||!!request} placeholder="YYYY-MM-DDTHH:mm:ss+04:00" onChange={event=>setEffective(event.target.value)}/></label>
   <label>Reason for restoring this query<textarea value={rationale} disabled={busy||!!request} minLength={10} maxLength={2000} onChange={event=>setRationale(event.target.value)}/></label>
   {!draft&&<button disabled={busy||!effective||rationale.trim().length<10} onClick={()=>void perform()}>{request?"Retry restoration draft":"Prepare restoration draft"}</button>}
   {request&&<button disabled={busy} onClick={()=>{setRequest(null);setDraft(null);setHead(null);setReceipt(null);setError("");}}>Discard local draft and start again</button>}
  </>}
  {busy&&<p role="status">Reading restoration evidence…</p>}{error&&<p role="alert">{error}</p>}
  {draft&&head&&<section aria-label="Restoration draft comparison"><h4>Review the restoration draft</h4>
   <p>Draft only. Independent review is required before any definition is published.</p>
   <div className="definition-restoration-table"><table><thead><tr><th>Definition content</th><th>Current expected head</th><th>Proposed restoration</th></tr></thead><tbody>
    <tr><th scope="row">Name</th><td>{head.display_name}</td><td>{draft.mutations[0].display_name}</td></tr>
    <tr><th scope="row">Effective from</th><td>{head.valid_from}</td><td>{draft.mutations[0].valid_from}</td></tr>

   </tbody></table></div>
   <div className="definition-restoration-queries"><section><h4>Current query</h4><QuerySummary query={head.attributes.definition}/></section><section><h4>Proposed restored query</h4><QuerySummary query={draft.mutations[0].attributes.definition}/></section></div>
   <details><summary>Exact saved queries</summary><h4>Current expected head</h4><pre>{JSON.stringify(head.attributes.definition,null,2)}</pre><h4>Proposed restoration</h4><pre>{JSON.stringify(draft.mutations[0].attributes.definition,null,2)}</pre></details>
   <details><summary>Exact restoration references</summary><dl><dt>Selected historical version</dt><dd>{selected.version_id}</dd><dt>Selected content hash</dt><dd>{selected.content_hash}</dd><dt>Current expected head</dt><dd>{head.version_id}</dd><dt>Draft proposal</dt><dd>{draft.proposal_id}</dd></dl></details>
   {!receipt&&<button disabled={busy||!canPropose} onClick={()=>void perform(true)}>Submit restoration for review</button>}
  </section>}
  {receipt&&<p role="status">Restoration proposal retained for independent review. {onProposal&&<button onClick={()=>onProposal(receipt)}>Open restoration review</button>}</p>}
 </details>;
}


const readableField=(value:string)=>value.replaceAll("_"," ").replace(/([a-z])([A-Z])/g,"$1 $2");
const asRecord=(value:unknown):value is Record<string,unknown>=>!!value&&typeof value==="object"&&!Array.isArray(value);
function QueryValue({value}:{value:unknown}) {
 if(Array.isArray(value))return <>{value.map((item,index)=><Fragment key={index}>{index>0?", ":""}<QueryValue value={item}/></Fragment>)}</>;
 if(typeof value==="string"&&uuid(value))return <details className="restoration-inline-reference"><summary>Exact reference</summary><code>{value}</code></details>;
 if(value===null)return <span>Null</span>;
 if(value===undefined)return <span>Not supplied</span>;
 if(typeof value==="object")return <details><summary>Structured value</summary><pre>{JSON.stringify(value,null,2)}</pre></details>;
 return <span style={{whiteSpace:"pre-wrap"}}>{typeof value==="boolean"?String(value):String(value)||"Empty text"}</span>;
}
function QueryFilters({filters}:{filters:unknown}) {
 if(!Array.isArray(filters))return <p>Predicate details are unavailable; inspect the exact query.</p>;
 if(!filters.length)return <p>No property predicates.</p>;
 const operators:Record<string,string>={eq:"equals",in:"is one of",not_in:"is not one of",lt:"is before / less than",lte:"is on or before / at most",gt:"is after / greater than",gte:"is on or after / at least"};
 return <ul>{filters.map((filter,index)=><li key={index}>{asRecord(filter)&&typeof filter.field==="string"?<><strong>{readableField(filter.field)}</strong> {operators[String(filter.operator??"eq")]??String(filter.operator)} <QueryValue value={filter.value}/></>:"Predicate details unavailable"}</li>)}</ul>;
}
function QuerySummary({query}:{query:unknown}) {
 if(!asRecord(query))return <p>The saved query is unavailable.</p>;
 return <div className="restoration-query-summary">
  <p><strong>Object type:</strong> {typeof query.object_type==="string"?readableField(query.object_type):"Not supplied"}</p>
  <QueryFilters filters={query.filters}/>
  {typeof query.search==="string"&&query.search&&<p><strong>Search:</strong> {query.search}</p>}
  {Array.isArray(query.resource_ids)&&<details><summary>{query.resource_ids.length} exact starting object references</summary>{query.resource_ids.map((id,index)=><p key={index}>{String(id)}</p>)}</details>}
  {(query.interface||query.type_group)?<details><summary>Exact reviewed query root</summary><pre>{JSON.stringify(query.interface??query.type_group,null,2)}</pre></details>:null}
  {Array.isArray(query.traversal)&&query.traversal.length>0&&<section><h5>Relationship steps</h5>{query.traversal.map((step,index)=><div key={index}>{asRecord(step)?<><p>Step {index+1}: {readableField(String(step.name))} · {String(step.direction)} {String(step.kind)}</p><QueryFilters filters={step.filters??[]}/></>:<p>Step details unavailable</p>}</div>)}</section>}
  <p>{query.valid_at?"Fixed effective context retained":"Effective context selected when run"} · {query.known_at?"Fixed knowledge context retained":"Knowledge context selected when run"}</p>
 </div>;
}
