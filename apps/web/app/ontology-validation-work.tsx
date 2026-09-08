"use client";

import {useEffect,useMemo,useRef,useState} from "react";
import type {Principal,ResourceProposalDetail} from "@finai/contracts";
import {createOntologyValidationClient,type ExternalDocument,type ExternalOntologyPin,type ValidationRead} from "@g8/ontology-client";
import {Badge,Empty} from "./g8-ui";
import {canProposeValidationReport,validationRequestId,validationSummary,type ActionItem} from "./action-model";
import PromotionReadiness from "./promotion-readiness";
import "./ontology-validation-work.css";

const label=(value:string)=>value.toLowerCase().replaceAll("_"," ");
const retainedState:Record<ValidationRead["state"],string>={INTENT_RETAINED:"Request retained",RUNNING:"Validation started",COMPLETED:"Report retained",PUBLISHED:"Execution evidence published",CANCELLED:"Cancelled"};
const graphName=(iri:string)=>iri.split(/[#/]/).filter(Boolean).at(-1)??iri;
const object=(value:unknown):value is Record<string,unknown>=>value!==null&&typeof value==="object"&&!Array.isArray(value);

function PinnedMeaning({title,pin,onInspect}:{title:string;pin:ExternalOntologyPin;onInspect:(id:string)=>void}){
 return <div className="g8-validation-pin"><button className="g8-link" onClick={()=>onInspect(pin.resource_id)}>{title}</button><details><summary>Exact reviewed version</summary><dl><dt>Resource</dt><dd>{pin.resource_id}</dd><dt>Version</dt><dd>{pin.version_id}</dd><dt>Content hash</dt><dd>{pin.content_hash}</dd></dl></details></div>;
}

export default function OntologyValidationWork({item,token,principal,expectedScope,revision,onInspect}:{item:ActionItem;token:string;principal:Principal;expectedScope:Principal["scope"];revision:number;onInspect:(id:string)=>void}){
 const {tenant_id,legal_entity_id,period,currency}=expectedScope;
 const client=useMemo(()=>createOntologyValidationClient({baseUrl:"/api/ontology",getToken:()=>token,expectedScope:{tenant_id,legal_entity_id,period,currency}}),[token,tenant_id,legal_entity_id,period,currency]);
 const [snapshot,setSnapshot]=useState<{client:typeof client;value:ValidationRead}|null>(null);
 const [error,setError]=useState("");const [busyClient,setBusyClient]=useState<typeof client|null>(null);
 const [review,setReview]=useState<{client:typeof client;id:string;notice:string}|null>(null);const requests=useRef(new Set<AbortController>());
 const proposalId=review?.client===client?review.id:"",notice=review?.client===client?review.notice:"",busy=busyClient===client;
 const workflowId=item.workflow_id,requestId=item.request_id,request=item.validation_request;
 const matchingScope=(["tenant_id","legal_entity_id","period","currency"] as const).every(key=>expectedScope[key]===principal.scope[key]);
 useEffect(()=>{const controller=new AbortController();
  async function read(){try{const id=validationRequestId({workflow_id:workflowId,request_id:requestId});if(!matchingScope||!request||request.request_id!==id)throw Error("The work list does not contain a matching exact validation request and scope.");const value=await client.readValidation(request,{signal:controller.signal});if(!controller.signal.aborted){setSnapshot({client,value});setError("");}}catch(failure){if(!controller.signal.aborted){setSnapshot(null);setError(String(failure));}}}
  void read();return()=>controller.abort();
 },[client,workflowId,requestId,request,matchingScope,revision]);
 useEffect(()=>{const active=requests.current;return()=>{for(const request of active)request.abort();};},[client]);
 const run=snapshot?.client===client&&snapshot.value.workflow_id===workflowId?snapshot.value:null;
 async function download(document:ExternalDocument,filename:string){const controller=new AbortController();requests.current.add(controller);setError("");try{
  const response=await fetch(`/api/ontology/source-documents/${encodeURIComponent(document.document_id)}/content`,{headers:{Authorization:`Bearer ${token}`},cache:"no-store",signal:controller.signal});
  if(!response.ok)throw Error("Retained evidence is unavailable for this identity.");
  const bytes=await response.arrayBuffer();const hash=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",bytes)),value=>value.toString(16).padStart(2,"0")).join("");
  if(bytes.byteLength!==document.byte_length||hash!==document.sha256)throw Error("Evidence integrity check failed; download withheld.");
  controller.signal.throwIfAborted();const url=URL.createObjectURL(new Blob([bytes],{type:"application/octet-stream"}));const link=window.document.createElement("a");link.href=url;link.download=filename;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 }catch(failure){if(!controller.signal.aborted)setError(String(failure));}finally{requests.current.delete(controller);}}
 async function prepareReview(){if(!run||!canProposeValidationReport(run,principal.permissions))return;const controller=new AbortController();requests.current.add(controller);setBusyClient(client);setError("");try{
  const response=await fetch(`/api/ontology/external/validation/runs/${run.request.request_id}/report-proposals`,{method:"POST",headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},body:"{}",signal:controller.signal,cache:"no-store"});
  const detail=await response.json() as ResourceProposalDetail&{detail?:unknown};
  if(!response.ok)throw Error(typeof detail.detail==="string"?detail.detail:"Report review could not be prepared.");
  const report=detail.proposal?.mutations.find(change=>change.object_type==="OntologyValidationReport");
  const definition=report?.attributes.definition;const evidence=object(definition)?definition.report:null;
  if(detail.proposal.access_entity!==principal.scope.legal_entity_id||!object(definition)||!object(evidence)||definition.workflow_id!==run.workflow_id||definition.request_sha256!==run.terminal?.request_sha256||definition.plan_sha256!==run.terminal?.plan_sha256||definition.outcome!==run.terminal?.outcome||evidence.sha256!==run.terminal?.report.sha256||evidence.document_id!==run.terminal?.report.document_id||evidence.byte_length!==run.terminal?.report.byte_length)throw Error("The returned review does not identify this retained report.");
  if(!controller.signal.aborted)setReview({client,id:detail.proposal.proposal_id,notice:detail.decision?`Retained report proposal: ${label(detail.decision)}.`:"Report proposal retained. An independent reviewer must decide it."});
 }catch(failure){if(!controller.signal.aborted)setError(`${String(failure)} Retry prepares the same retained report; it does not approve it.`);}finally{requests.current.delete(controller);if(!controller.signal.aborted)setBusyClient(null);}}
 if(!run)return <section aria-label="Ontology validation inspection">{error?<p role="alert">{error}</p>:<Empty title="Reading retained validation">Checking this request, its exact scope and retained evidence.</Empty>}</section>;
 const summary=validationSummary(run),observation=run.report;
 const result=observation&&observation.outcome!=="REFUSED"?observation.result:null;
 return <article className="g8-validation" aria-label="Ontology profile validation">
  <header><p className="g8-validation-eyebrow">Ontology profile validation</p><div className="g8-validation-heading"><h2>{summary.title}</h2><Badge tone={summary.tone}>{observation?label(observation.outcome):"Awaiting result"}</Badge></div><p>{summary.detail}</p></header>
  {error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
  <dl className="g8-validation-status"><div><dt>Retained state</dt><dd>{retainedState[run.state]}</dd></div><div><dt>Live runtime</dt><dd>{run.runtime_status==="UNOBSERVABLE"?"Not observable":label(run.runtime_status)}</dd></div><div><dt>Coverage selection</dt><dd>{run.plan.selection.mode==="PROFILE_TARGETS"?"Reviewed profile targets":run.plan.selection.mode==="FILTER_TARGETS"?"Filtered target selection":"Explicit shapes and focus nodes"}</dd></div></dl>
  {run.runtime_status==="UNOBSERVABLE"&&<p className="g8-validation-note">Retained evidence is available. Current worker activity cannot be confirmed.</p>}
  <div className="g8-validation-panes"><section aria-label="Validation coverage"><h3>What was checked</h3>{result?<div className="g8-table-scroll"><table><thead><tr><th scope="col">Evaluated coverage</th><th scope="col">Retained count</th></tr></thead><tbody><tr><th scope="row">Shapes evaluated</th><td>{result.evaluated_shape_count.toLocaleString()}</td></tr><tr><th scope="row">Focus nodes evaluated</th><td>{result.evaluated_focus_count.toLocaleString()}</td></tr><tr><th scope="row">Constraint evaluations</th><td>{result.evaluated_constraint_count.toLocaleString()}</td></tr><tr className={result.violation_count?"g8-validation-attention":""}><th scope="row">Validation results requiring review</th><td>{result.violation_count.toLocaleString()}</td></tr></tbody></table></div>:<p>{observation?.outcome==="REFUSED"?`Retained refusal: ${label(observation.refusal_code)}. No evaluated coverage is claimed.`:"Coverage will appear when a complete report is retained."}</p>}
   {result&&<p>Counts describe the selected graphs and targets. They do not measure all company data or certify compliance.</p>}
   <h3>What to investigate next</h3><p>{observation?.outcome==="VIOLATES"?"Open the retained report, then trace the data release and the shape release to understand each result.":observation?.outcome==="NOT_EVALUATED"?"Review the selected targets and shapes before preparing another validation request.":observation?.outcome==="REFUSED"?"Review the refusal and the selected shape release before preparing another request.":observation?"Inspect the exact selection and evidence before requesting independent report review.":"Refresh this work item to read its next retained state."}</p>
  </section><section aria-label="Validation evidence and reviewed meaning"><h3>Evidence and reviewed meaning</h3><PinnedMeaning title="Ontology profile" pin={run.plan.ontology_profile} onInspect={onInspect}/><PinnedMeaning title="Constraint profile" pin={run.plan.constraint_profile} onInspect={onInspect}/>{([['Data release',run.plan.data],['Shape release',run.plan.shapes]] as const).map(([title,selection])=><div key={title}><PinnedMeaning title={title} pin={selection.release} onInspect={onInspect}/><details><summary>{selection.graph_iris.length} selected {selection.graph_iris.length===1?"graph":"graphs"}</summary><ul>{selection.graph_iris.map(iri=><li key={iri}><strong>{graphName(iri)}</strong><small>{iri}</small></li>)}</ul><p>Retained dataset hash: {selection.canonical_dataset.sha256}</p></details></div>)}
   {run.terminal&&<button onClick={()=>void download(run.terminal!.report,"ontology-validation-observation.json")}>Download retained observation</button>}{observation&&observation.outcome!=="REFUSED"&&<button onClick={()=>void download(observation.rdf_report,"ontology-validation-report.nq")}>Download detailed validation evidence</button>}
  </section></div>
  <section aria-label="Validation report review"><h3>Independent report review</h3><p>{run.publication_id?"The execution evidence is published. Canonical report approval is a separate, independent decision.":"A complete, published execution report is required before canonical review can be prepared."}</p>{canProposeValidationReport(run,principal.permissions)&&<button disabled={busy} onClick={()=>void prepareReview()}>{busy?"Preparing report review…":proposalId?"Reopen retained report review":"Prepare report for review"}</button>}{proposalId&&<PromotionReadiness key={proposalId} token={token} proposalId={proposalId}/>}</section>
  <details><summary>Execution and evidence references</summary><dl><dt>Request</dt><dd>{run.workflow_id}</dd><dt>Plan hash</dt><dd>{run.plan_sha256}</dd><dt>Validator manifest hash</dt><dd>{run.plan.validator_manifest_sha256}</dd>{run.terminal&&<><dt>Observation hash</dt><dd>{run.terminal.report.sha256}</dd></>}{run.publication_id&&<><dt>Execution publication</dt><dd>{run.publication_id}</dd></>}</dl><p>The selected company is navigation context. This request uses its retained sign-in scope and has no canonical company binding.</p><p>No financial posting, accounting approval or certification is authorized by this report.</p></details>
 </article>;
}
