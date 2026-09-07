"use client";

import {useEffect,useRef,useState,type FormEvent} from "react";
import type {AccountDimensionPolicyResponse,AccountDimensionPolicyProposalRequest,AccountDimensionPolicyProposalResponse} from "@finai/contracts";
import type {SourceAccountNavigation} from "./seg-account-observations";
import "./account-dimension-policy-workbench.css";

type Account={resource_id:string;version_id:string;display_name:string};
type Props={token:string;companyId:string;account:Account;canPropose:boolean;onProposal:(id:string)=>void;onClose:()=>void}&SourceAccountNavigation;
const pin=(resource:{resource_id:string;version_id:string})=>({resource_id:resource.resource_id,version_id:resource.version_id});
const uuid=(value:unknown)=>typeof value==="string"&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
export default function AccountDimensionPolicyWorkbench(props:Props){
 return <PolicyPanel key={JSON.stringify([props.token,props.companyId,props.account.resource_id,props.account.version_id])} {...props}/>;
}
function PolicyPanel({token,companyId,account,canPropose,onProposal,onClose,onInspectResource,onTraceResource}:Props){
 const dialog=useRef<HTMLDialogElement>(null);
 const [result,setResult]=useState<AccountDimensionPolicyResponse|null>(null);
 const [loading,setLoading]=useState(true);
 const [error,setError]=useState("");
 const [revision,setRevision]=useState(0);
 const [reason,setReason]=useState("");
 const [frozen,setFrozen]=useState<AccountDimensionPolicyProposalRequest|null>(null);
 const [receipt,setReceipt]=useState<AccountDimensionPolicyProposalResponse|null>(null);
 const [submitting,setSubmitting]=useState(false);
 const active=useRef<AbortController|null>(null);
 useEffect(()=>{const node=dialog.current;node?.showModal();return()=>{node?.close();active.current?.abort();active.current=null;};},[]);
 useEffect(()=>{
  const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),20000);let disposed=false;
  const query=new URLSearchParams({company_id:companyId,account_id:account.resource_id,account_version_id:account.version_id});
  void fetch(`/api/ontology/account-dimension-policy?${query}`,{headers:{Authorization:`Bearer ${token}`},cache:"no-store",signal:controller.signal}).then(async response=>{
   const data=await response.json();if(!response.ok)throw Error(typeof data.detail==="string"?data.detail:`Analytical policy unavailable (${response.status}).`);
   if(data.current_use_authorized!==false||data.company?.resource_id!==companyId||data.account?.resource_id!==account.resource_id||data.account?.version_id!==account.version_id||data.account?.object_type!=="LocalAccount"||data.account?.attributes?.chart_id!==data.chart?.resource_id||!["CURRENT","STALE","UNESTABLISHED"].includes(data.state))throw Error("The policy response does not match the selected company, chart and exact account. Reopen the current canonical account before continuing.");
   if(!disposed)setResult(data);
  }).catch(failure=>{if(!disposed)setError(controller.signal.aborted?"Policy read timed out. Its current state is unavailable.":String(failure));}).finally(()=>{clearTimeout(timer);if(!disposed)setLoading(false);});
  return()=>{disposed=true;controller.abort();clearTimeout(timer);};
 },[token,companyId,account.resource_id,account.version_id,revision]);
 function refresh(){setResult(null);setError("");setLoading(true);setRevision(value=>value+1);}
 async function propose(event:FormEvent<HTMLFormElement>){
  event.preventDefault();if(submitting||!canPropose||!result||!result.rules_complete||receipt||(!frozen&&reason.trim().length<10))return;
  const request=frozen??{request_id:crypto.randomUUID(),expected_version_id:result.policy?.version_id??null,company:pin(result.company),chart:pin(result.chart),account:pin(result.account),rules:result.rules.map(item=>pin(item.rule)),reason:reason.trim()};
  setFrozen(request);setSubmitting(true);setError("");const controller=new AbortController();active.current=controller;const timer=setTimeout(()=>controller.abort(),20000);
  try{
   const response=await fetch("/api/ontology/account-dimension-policy/proposal",{method:"POST",headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},body:JSON.stringify(request),cache:"no-store",signal:controller.signal});
   const data=await response.json();if(!response.ok)throw Error(typeof data.detail==="string"?data.detail:`Policy proposal refused (${response.status}).`);
   if(data.proposal_id!==request.request_id||!uuid(data.policy_id)||![null,"APPROVED","REJECTED"].includes(data.decision)||data.review_required!==(data.decision===null)||result.policy&&data.policy_id!==result.policy.resource_id)throw Error("The retained policy proposal does not match this request.");
   if(active.current===controller&&!controller.signal.aborted)setReceipt(data);
  }catch(failure){if(active.current===controller)setError(controller.signal.aborted?"Response timed out. Retry uses the same request; a proposal may already be retained.":String(failure));}
  finally{clearTimeout(timer);if(active.current===controller)setSubmitting(false);}
 }
 function actions(resource:Account){return <span className="account-policy-actions">{onInspectResource&&<button onClick={()=>{onClose();onInspectResource(pin(resource));}}>Inspect</button>}{onTraceResource&&<button onClick={()=>{onClose();onTraceResource(pin(resource));}}>Trace</button>}</span>;}
 return <dialog ref={dialog} className="account-policy-dialog" onCancel={onClose} aria-labelledby="account-policy-title">
  <header><div><h2 id="account-policy-title">Account analytical requirements</h2><p>{account.display_name}</p></div><button onClick={onClose}>Close</button></header>
  <p>Review the complete existing rule set for this exact account. Source-code matches remain candidates; opening this workbench does not accept a mapping.</p>
  <button disabled={loading||submitting||Boolean(frozen&&!receipt)} onClick={refresh}>Refresh current policy</button>
  {loading&&<p role="status">Validating company, chart and account policy…</p>}{error&&<p role="alert">{error}</p>}
  {result&&<><p><strong>{result.company.display_name}</strong> · {result.chart.display_name} · {result.account.display_name}</p><p><strong>{result.state.toLowerCase()}</strong> · {result.reason}</p><p>Checked {new Date(result.checked_at).toLocaleString()}. Policy review does not authorize accounting amounts or posting.</p>
   {!result.rules_complete&&<p role="status">The existing rule inventory is incomplete. A policy proposal is unavailable.</p>}
   <div className="account-policy-table"><table><thead><tr><th>Existing account rule</th><th>Analytical dimension</th><th>Reviewed definition</th></tr></thead><tbody>{result.rules.map(item=><tr key={item.rule.version_id}><th scope="row">{item.rule.display_name}{actions(item.rule)}</th><td>{item.dimension.display_name}{actions(item.dimension)}</td><td><p>{item.rule.attributes.required===true?"Required dimension":item.rule.attributes.required===false?"Optional dimension":"Requirement flag unavailable"}</p><details><summary>Rule requirements and exact version</summary><pre>{JSON.stringify(item.rule.attributes,null,2)}</pre><p>{item.rule.resource_id} · {item.rule.version_id}</p></details></td></tr>)}</tbody></table></div>
   {!result.rules.length&&<p>No existing rules were returned. An empty allowed-rule policy still requires an explicit proposal and independent review.</p>}
   <p>Every returned required or optional rule is included. Change canonical account rules separately before proposing a different full rule set.</p>
   {result.policy&&<p>Current retained policy: {result.policy.display_name}{actions(result.policy)}</p>}
   {canPropose&&result.rules_complete?<form onSubmit={propose}><label>Reason for reviewing this complete rule set<textarea required minLength={10} maxLength={2000} disabled={submitting||Boolean(frozen)} value={reason} onChange={event=>setReason(event.target.value)}/></label>
    {!receipt&&<div className="account-policy-actions"><button disabled={loading||submitting||(!frozen&&reason.trim().length<10)}>{submitting?"Submitting proposal…":frozen?"Retry exact proposal":result.rules.length?"Propose complete rule policy":"Propose explicitly empty rule policy"}</button>{frozen&&!submitting&&<button type="button" onClick={()=>{setFrozen(null);setError("");}}>Discard local retry draft</button>}</div>}
    {frozen&&!receipt&&<p>Retry preserves the exact rule versions and rationale. Discarding the draft does not withdraw a retained proposal.</p>}
    {receipt&&<p role="status">{receipt.decision===null?"Policy proposal retained; independent review required.":`Recorded decision: ${receipt.decision.toLowerCase()}. Refresh to inspect the current policy.`}<button type="button" onClick={()=>{onClose();onProposal(receipt.proposal_id);}}>Open proposal review</button><button type="button" onClick={()=>{setFrozen(null);setReceipt(null);setReason("");refresh();}}>Start another review</button></p>}
   </form>:<p>A policy proposal requires complete rule coverage and proposal permission.</p>}
   <details><summary>Exact selected context</summary><p>Company: {result.company.resource_id} · {result.company.version_id}</p><p>Chart: {result.chart.resource_id} · {result.chart.version_id}</p><p>Account: {result.account.resource_id} · {result.account.version_id}</p></details>
  </>}
 </dialog>;
}
