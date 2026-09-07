"use client";

import {useEffect,useRef,useState,type FormEvent} from "react";
import type {CanonicalResource,JournalSelection,PeriodControlResponse,PeriodControlProposalRequest,PeriodControlProposalResponse} from "@finai/contracts";
import "./company-period-control.css";

const fields=["legal_entity_id","ledger_id","book_id","period_id","chart_id","currency_id","calendar_id"] as const;
type Props={token:string;selection:Record<string,{resource_id:string;version_id:string}>;canPropose:boolean;onProposal:(id:string)=>void;onInspect?:(resource:CanonicalResource,knownAt:string)=>void;onTrace?:(resource:CanonicalResource,knownAt:string)=>void};
function matches(actual:unknown,expected:Props["selection"]){
 if(!actual||typeof actual!=="object")return false;
 const values=actual as Record<string,unknown>;
 return fields.every(field=>{const pin=values[field];return Boolean(expected[field]&&pin&&typeof pin==="object"&&"resource_id" in pin&&"version_id" in pin&&pin.resource_id===expected[field].resource_id&&pin.version_id===expected[field].version_id);});
}
export default function CompanyPeriodControl(props:Props){
 return <ControlPanel key={JSON.stringify([props.token,fields.map(field=>[field,props.selection[field]?.resource_id,props.selection[field]?.version_id])])} {...props}/>;
}
function ControlPanel({token,selection,canPropose,onProposal,onInspect,onTrace}:Props){
 const [result,setResult]=useState<PeriodControlResponse|null>(null);
 const [error,setError]=useState("");
 const [revision,setRevision]=useState(0);
 const [loading,setLoading]=useState(true);
 const [state,setState]=useState<""|"OPEN"|"LOCKED">("");
 const [reason,setReason]=useState("");
 const [frozen,setFrozen]=useState<PeriodControlProposalRequest|null>(null);
 const [receipt,setReceipt]=useState<PeriodControlProposalResponse|null>(null);
 const [submitting,setSubmitting]=useState(false);
 const write=useRef<AbortController|null>(null);
 useEffect(()=>()=>{write.current?.abort();write.current=null;},[]);
 useEffect(()=>{
  const controller=new AbortController();let disposed=false;
  const timer=setTimeout(()=>controller.abort(),20000);
  const params=new URLSearchParams({company_id:selection.legal_entity_id.resource_id,ledger_id:selection.ledger_id.resource_id,book_id:selection.book_id.resource_id,period_id:selection.period_id.resource_id});
  void fetch(`/api/ontology/period-control?${params}`,{headers:{Authorization:`Bearer ${token}`},cache:"no-store",signal:controller.signal}).then(async response=>{
   const data=await response.json();if(!response.ok)throw Error(typeof data.detail==="string"?data.detail:`Posting control unavailable (${response.status}).`);
   if(!matches(data.selection,selection)||data.current_use_authorized!==false||data.financial_close_certified!==false||data.erp_posted!==false||!["OPEN","LOCKED","UNESTABLISHED"].includes(data.state))throw Error("Posting control does not match the validated accounting context. Refresh company context before continuing.");
   if(!disposed)setResult(data);
  }).catch(failure=>{if(!disposed)setError(controller.signal.aborted?"Posting control timed out; its current state is unavailable.":String(failure));}).finally(()=>{clearTimeout(timer);if(!disposed)setLoading(false);});
  return()=>{disposed=true;controller.abort();clearTimeout(timer);};
 },[token,selection,revision]);
 function refresh(){setResult(null);setLoading(true);setError("");setRevision(value=>value+1);}
 async function propose(event:FormEvent<HTMLFormElement>){
  event.preventDefault();if(submitting||!canPropose||receipt||!result||(!frozen&&(!state||reason.trim().length<10)))return;
  const request=frozen??{selection:result.selection as JournalSelection,request_id:crypto.randomUUID(),expected_version_id:result.control?.version_id??null,state:state as "OPEN"|"LOCKED",reason:reason.trim()};
  setFrozen(request);setSubmitting(true);setError("");
  const controller=new AbortController();write.current=controller;const timer=setTimeout(()=>controller.abort(),20000);
  try{
   const response=await fetch("/api/ontology/period-control/proposal",{method:"POST",headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},cache:"no-store",signal:controller.signal,body:JSON.stringify(request)});
   const data=await response.json();if(!response.ok)throw Error(typeof data.detail==="string"?data.detail:`Posting control proposal refused (${response.status}).`);
   if(data.proposal_id!==request.request_id||typeof data.control_id!=="string"||!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(data.control_id)||![null,"APPROVED","REJECTED"].includes(data.decision)||data.review_required!==(data.decision===null)||result.control&&data.control_id!==result.control.resource_id)throw Error("The proposal response did not match this posting control request.");
   if(write.current===controller&&!controller.signal.aborted)setReceipt(data);
  }catch(failure){if(write.current===controller)setError(controller.signal.aborted?"Response timed out. Retry preserves the exact request; a proposal may already be retained.":String(failure));}
  finally{clearTimeout(timer);if(write.current===controller)setSubmitting(false);}
 }
 return <section className="company-period-control" aria-label="Period posting control">
  <header><div><h3>Period posting control</h3><p>Controls whether journals and changes can be approved for this period. Existing journals remain available for inspection.</p></div><button disabled={submitting||loading||Boolean(frozen&&!receipt)} onClick={refresh}>Refresh posting control</button></header>
  {loading&&<p role="status">Reading current posting control…</p>}{error&&<p role="alert">{error}</p>}
  {result&&<><p><strong>{result.state==="OPEN"?"Open for journal changes":result.state==="LOCKED"?"Locked for journal changes":"Posting control not established"}</strong> · {result.reason}</p><small>Checked {new Date(result.checked_at).toLocaleString()}. Journal changes still require complete evidence, a balanced entry and independent review.</small>
   <p>This is a posting control, not a completed or certified financial close. It does not post to an ERP.</p>
   {result.control&&<div className="period-control-actions">{onInspect&&<button onClick={()=>onInspect(result.control!,result.checked_at)}>Inspect reviewed control</button>}{onTrace&&<button onClick={()=>onTrace(result.control!,result.checked_at)}>Trace control</button>}</div>}
   {canPropose?<details><summary>Propose a posting-control change</summary><form onSubmit={propose}>
    <label>Requested state<select value={state} required disabled={submitting||Boolean(frozen)} onChange={event=>setState(event.target.value as ""|"OPEN"|"LOCKED")}><option value="">Choose a reviewed change</option><option value="OPEN">{result.state==="LOCKED"?"Reopen period for journal changes":"Open period for journal changes"}</option><option value="LOCKED">Lock period against journal changes</option></select></label>
    <label>Reason for this change<textarea required minLength={10} maxLength={2000} disabled={submitting||Boolean(frozen)} value={reason} onChange={event=>setReason(event.target.value)}/></label>
    {!receipt&&<div className="period-control-actions"><button disabled={submitting||loading||(!frozen&&(!state||reason.trim().length<10))}>{submitting?"Submitting proposal…":frozen?"Retry exact proposal":"Propose for independent review"}</button>{frozen&&!submitting&&<button type="button" onClick={()=>{setFrozen(null);setError("");}}>Discard local retry draft</button>}</div>}
    {frozen&&!receipt&&<p>Retry retains the same request and expected version. Discarding the local draft does not withdraw a proposal already recorded.</p>}
    {receipt&&<p role="status">{receipt.decision===null?"Proposal retained; independent review required.":`Recorded proposal decision: ${receipt.decision.toLowerCase()}. Refresh current control to read its present state.`}<button type="button" onClick={()=>onProposal(receipt.proposal_id)}>Open proposal review</button><button type="button" disabled={submitting||loading} onClick={()=>{setFrozen(null);setReceipt(null);setState("");setReason("");refresh();}}>Start another change</button></p>}
   </form></details>:<p>This identity cannot propose posting-control changes.</p>}
   <details><summary>Exact control references</summary><p>{result.control?`${result.control.resource_id} · ${result.control.version_id}`:"No currently available reviewed control"}</p>{frozen&&<p>Request: {frozen.request_id}</p>}{receipt&&<p>Proposal: {receipt.proposal_id}</p>}</details>
  </>}
 </section>;
}
