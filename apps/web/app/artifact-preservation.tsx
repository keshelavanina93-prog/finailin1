"use client";
import {useEffect,useRef,useState} from "react";

type ArtifactReference={kind:"SOURCE_RECEIPT";receipt_id:string}|{kind:"SOURCE_DOCUMENT";document_id:string};
type Artifact={reference:ArtifactReference;artifact_class:string;content_hash:string;exact_scope:Record<string,unknown>;recorded_at:string;authority_scope:string};
type Inspection={artifact:Artifact;execution_authorized:false;legal_compliance_established:false};
type Evaluation={evaluation_id:string;proof_hash:string;recorded_at:string;execution_authorized:false;current_use_authorized:false;proof:{artifact:Artifact;status:string;reasons:string[];effective_disposition:"PRESERVE";requested_action:"PRESERVE";purpose:"DISPOSITION_EVALUATION_ONLY";legal_compliance_established:false}};
type Props={token:string;artifact:ArtifactReference;canRecord:boolean};
const human=(text:string)=>text.toLowerCase().replaceAll("_"," ");
const same=(a:ArtifactReference,b:ArtifactReference)=>a.kind===b.kind&&(a.kind==="SOURCE_RECEIPT"&&b.kind==="SOURCE_RECEIPT"?a.receipt_id===b.receipt_id:a.kind==="SOURCE_DOCUMENT"&&b.kind==="SOURCE_DOCUMENT"&&a.document_id===b.document_id);
export default function ArtifactPreservation(props:Props){return <Preservation key={JSON.stringify([props.token,props.artifact])} {...props}/>;}
function Preservation({token,artifact,canRecord}:Props){
 const [open,setOpen]=useState(false);const [revision,setRevision]=useState(0);const [inspection,setInspection]=useState<Inspection|null>(null);const [error,setError]=useState("");const [loading,setLoading]=useState(false);
 const [evaluation,setEvaluation]=useState<Evaluation|null>(null);const [recording,setRecording]=useState(false);const [recordError,setRecordError]=useState("");
 const requestId=useRef<string|null>(null);const recordRequest=useRef<AbortController|null>(null);
 const reference=JSON.stringify(artifact);
 useEffect(()=>()=>{recordRequest.current?.abort();recordRequest.current=null;},[]);
 useEffect(()=>{
  if(!open)return;const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),20000);let disposed=false;
  async function inspect(){setLoading(true);setError("");setInspection(null);try{
   const response=await fetch("/api/ontology/retention/inspect",{method:"POST",headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},body:JSON.stringify({artifact:JSON.parse(reference)}),signal:controller.signal,cache:"no-store"});
   if(!response.ok)throw new Error("Preservation metadata is unavailable for this source.");const data:Inspection=await response.json();
   if(!same(data.artifact.reference,JSON.parse(reference))||data.execution_authorized!==false||data.legal_compliance_established!==false)throw new Error("Preservation metadata did not match this source.");
   if(!disposed)setInspection(data);
  }catch(failure){if(!disposed)setError(controller.signal.aborted?"The inspection timed out. Retry to check this source.":failure instanceof Error?failure.message:"Inspection unavailable");}
  finally{clearTimeout(timer);if(!disposed)setLoading(false);}}
  void inspect();return()=>{disposed=true;clearTimeout(timer);controller.abort();};
 },[open,token,reference,revision]);
 async function record(){
  if(recording||!inspection||!canRecord)return;const controller=new AbortController();recordRequest.current=controller;const timer=setTimeout(()=>controller.abort(),20000);setRecording(true);setRecordError("");requestId.current??=crypto.randomUUID();
  try{
   const response=await fetch("/api/ontology/retention/evaluations",{method:"POST",headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},body:JSON.stringify({artifact,requested_action:"PRESERVE",request_id:requestId.current}),signal:controller.signal});
   if(!response.ok)throw new Error("The preservation assessment could not be confirmed. Retry uses the same request reference.");const data:Evaluation=await response.json();
   if(data.evaluation_id!==requestId.current||!same(data.proof.artifact.reference,artifact)||data.proof.artifact.content_hash!==inspection.artifact.content_hash||data.proof.purpose!=="DISPOSITION_EVALUATION_ONLY"||data.proof.requested_action!=="PRESERVE"||data.proof.effective_disposition!=="PRESERVE"||data.execution_authorized!==false||data.current_use_authorized!==false||data.proof.legal_compliance_established!==false)throw new Error("The assessment did not match this retained source and preservation request.");
   if(recordRequest.current===controller&&!controller.signal.aborted)setEvaluation(data);
  }catch(failure){if(recordRequest.current===controller)setRecordError(controller.signal.aborted?"The response timed out; the assessment may have been recorded. Retry safely uses the same request reference.":failure instanceof Error?failure.message:"Assessment unavailable");}
  finally{clearTimeout(timer);if(recordRequest.current===controller)setRecording(false);}
 }
 return <details className="source-detail" onToggle={event=>setOpen(event.currentTarget.open)}><summary>Storage & preservation</summary>{open&&<section aria-label="Source preservation">
  <p>Inspect retained source metadata and record a preservation assessment.</p>
  {loading&&<p role="status">Inspecting retained source…</p>}{error&&<p role="alert">{error}</p>}
  {inspection&&<><dl><dt>Storage class</dt><dd>{human(inspection.artifact.artifact_class)}</dd><dt>Retained on</dt><dd>{new Date(inspection.artifact.recorded_at).toLocaleString()}</dd><dt>Authority scope</dt><dd>{human(inspection.artifact.authority_scope)}</dd></dl><p>Retention policy is not selected. A recorded check requests preservation for further review; this inspection does not establish a legal retention period.</p><details><summary>Exact retained metadata</summary><dl><dt>Source reference</dt><dd>{artifact.kind==="SOURCE_RECEIPT"?artifact.receipt_id:artifact.document_id}</dd><dt>Content hash</dt><dd>{inspection.artifact.content_hash}</dd><dt>Server access scope</dt><dd><pre>{JSON.stringify(inspection.artifact.exact_scope,null,2)}</pre></dd></dl></details></>}
  {evaluation&&<div role="status"><h4>Preservation assessment recorded</h4><p>{human(evaluation.proof.status)} · disposition: {human(evaluation.proof.effective_disposition)}</p>{evaluation.proof.reasons.map(reason=><p key={reason}>{human(reason)}</p>)}<small>{new Date(evaluation.recorded_at).toLocaleString()}</small><details><summary>Assessment reference</summary><p>{evaluation.evaluation_id}</p><p>{evaluation.proof_hash}</p></details></div>}
  {recordError&&<p role="alert">{recordError}</p>}
  <p>This is retained assessment evidence. It does not execute storage changes, establish legal compliance or confer financial authority.</p>
  <button type="button" disabled={loading||recording} onClick={()=>setRevision(value=>value+1)}>Refresh metadata</button>{canRecord&&<button type="button" disabled={!inspection||loading||recording||Boolean(evaluation)} onClick={()=>void record()}>{recording?"Recording assessment…":recordError?"Retry preservation check":"Record preservation check"}</button>}
 </section>}</details>;
}
