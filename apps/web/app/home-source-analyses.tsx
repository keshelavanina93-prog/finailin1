"use client";
import {useEffect,useState} from "react";
import type {AnalysisField,AnalysisValue,AnalysisProjection} from "@finai/contracts";
import {assertProjection,formatAnalysisDecimal} from "./semantic-analysis-state";
import {homeAnalysisReferences,clearHomeAnalysisPins,removeHomeAnalysis,subscribeHomeAnalysisPins} from "./company-home-pins";
import {assertHomeRevision,homeAnalysisRequest,homeReferencesForGroup,type HomeAnalysisReference} from "./company-home-revision";
import {useSourceReview} from "./source-review-navigation";
import {displayedAnalysisView} from "./source-review-route";
import {projectionIdentity,projectionEndpoint} from "./analysis-projection-identity";
import {homeAnalysisRowTarget} from "./home-analysis-row";
const human=(value:string)=>value.replaceAll("_"," ").toLowerCase();
const contextValue=(value:string)=>/^(?:[a-f0-9]{64}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})$/i.test(value)?"Exact reference in source review":value;
const stamp=(value:string)=>new Date(value).toLocaleString();
function cell(value:AnalysisValue,field:AnalysisField){
 if(value.state!=="VALUE")return value.state==="NULL"?"Recorded null":"Not recorded";
 if(field.presentation&&typeof value.value==="string")return formatAnalysisDecimal(value.value,field);
 return value.label??String(value.value);
}

type ReferenceError={message:string;reference?:HomeAnalysisReference};
type Props={token:string;companyId:string;onData:()=>void;projectionGroup?:"sources"|"journals"};
export default function HomeSourceAnalyses(props:Props){return <SourceAnalyses key={JSON.stringify([props.token,props.companyId,props.projectionGroup])} {...props}/>;}
function SourceAnalyses({token,companyId,onData,projectionGroup}:Props){
 const open=useSourceReview();const [analyses,setAnalyses]=useState<{projection:AnalysisProjection;reference:HomeAnalysisReference}[]>([]);
 const [errors,setErrors]=useState<ReferenceError[]>([]),[busy,setBusy]=useState(true),[revision,setRevision]=useState(0);
 useEffect(()=>{let controller:AbortController|null=null,timer:ReturnType<typeof setTimeout>|undefined,disposed=false,generation=0;
  async function load(){const requestGeneration=++generation;controller?.abort();clearTimeout(timer);
   const requestController=new AbortController();controller=requestController;
   timer=setTimeout(()=>requestController.abort(),25000);
   setBusy(true);setErrors([]);setAnalyses([]);
   try{
   const references=homeReferencesForGroup(await homeAnalysisReferences(token,companyId),projectionGroup);
   if(disposed||requestGeneration!==generation)return;
   const entries=await Promise.all(references.map(async reference=>{try{
    const request=homeAnalysisRequest(reference,companyId);
    const response=await fetch(projectionEndpoint(reference.journalSnapshot),{method:"POST",headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},body:JSON.stringify(request),cache:"no-store",signal:requestController.signal});
    const data=await response.json();if(!response.ok)throw Error(response.status===401||response.status===403?"A saved analysis is unavailable to this identity.":"A saved analysis could not be restored. Its reference remains saved.");
    assertProjection(data,request);assertHomeRevision(data,reference);return {analysis:{projection:data as AnalysisProjection,reference},error:null};
   }catch(failure){return {analysis:null,error:{reference,message:requestController.signal.aborted?"Saved analysis retrieval timed out.":String(failure)}};}}));
   if(!disposed&&requestGeneration===generation){setAnalyses(entries.flatMap(item=>item.analysis?[item.analysis]:[]));setErrors(entries.flatMap(item=>item.error?[item.error]:[]));}
  }catch{if(!disposed&&requestGeneration===generation)setErrors([{message:"Device analysis references are unavailable. Company condition remains independently available."}]);}finally{if(!disposed&&requestGeneration===generation){clearTimeout(timer);setBusy(false);}}}
  const unsubscribe=subscribeHomeAnalysisPins(token,companyId,()=>void load(),()=>{if(!disposed){setErrors([{message:"Device analysis references are unavailable. Company condition remains independently available."}]);setBusy(false);}});
  return()=>{disposed=true;unsubscribe();controller?.abort();clearTimeout(timer);};
 },[token,companyId,revision,projectionGroup]);
 function retry(){setBusy(true);setErrors([]);setAnalyses([]);setRevision(value=>value+1);}
 function reviewRow(projection:AnalysisProjection,reference:HomeAnalysisReference,rowKey:string){try{const target=homeAnalysisRowTarget(projection,reference,companyId,rowKey);if(target)open(target);else setErrors([{message:"No retained contributor is available for this row."}]);}catch(failure){setErrors([{message:failure instanceof Error?failure.message:"The exact row review is unavailable."}]);}}
 async function remove(reference:HomeAnalysisReference){try{await removeHomeAnalysis(token,companyId,reference);}catch(failure){setErrors(previous=>[...previous,{message:failure instanceof Error?failure.message:"This Home reference could not be removed. Other references are unchanged."}]);}}
 if(projectionGroup==="journals"&&!busy&&!errors.length&&!analyses.length)return null;
 return <div className="home-source-analysis-content">{projectionGroup==="journals"&&analyses.length>0&&<h3>Accepted journal movements</h3>}<p className="home-scope-note">{projectionGroup==="journals"?"Accepted journal movements retain their pinned snapshot, period, currency and source boundaries. Partial coverage does not establish a complete ledger or financial statement.":"Each result retains its own financial period, currency and authority. Source movement is not a financial statement."}</p>
 {busy?<p role="status">Restoring saved source references…</p>:<>{errors.length>0&&<div role="status" className="home-source-analysis-error">{errors.map((error,index)=><div key={index}><p>{error.message}</p>{error.reference&&<><p>{error.reference.journalSnapshot?`Saved journal snapshot · ${stamp(error.reference.journalSnapshot)}`:"Saved source analysis"}{error.reference.kind==="EXACT"&&` · source known ${stamp(error.reference.revision.knownAt)}`}</p><button onClick={()=>void remove(error.reference!)}>Remove this reference from Home</button><details><summary>Advanced · unavailable reference</summary><p>Source result {error.reference.invocationId}</p>{error.reference.kind==="EXACT"&&<><p>Descriptor {error.reference.revision.descriptorSha256}</p><p>Receipt {error.reference.revision.receiptHash}</p><p>Effective {error.reference.revision.validAt} · known {error.reference.revision.knownAt}</p></>}</details></>}</div>)}<button onClick={retry}>Retry source references</button><button onClick={()=>void clearHomeAnalysisPins(token,companyId).catch(()=>setErrors([{message:"Device references could not be cleared."}]))}>Clear all company Home references</button><p>Company condition and work are independent of these saved source references.</p></div>}
   {!analyses.length?<div className="home-pin-prompt"><p>{errors.length?"Saved source analyses are unavailable. Their references remain saved.":<>No analyses pinned for this company. Open a verified source review and choose <strong>Pin to company Home</strong>.</>}</p><button onClick={onData}>Open Data & evidence</button></div>:analyses.map(({projection:analysis,reference})=>{const d=analysis.descriptor;const fields=d.fields;return <article className="home-analysis" key={projectionIdentity(d.invocation_id,reference.journalSnapshot)}><header><h3>{d.title}</h3><button onClick={()=>open({companyId,invocationId:d.invocation_id,...(reference.journalSnapshot===undefined?{}:{journalSnapshot:reference.journalSnapshot}),view:displayedAnalysisView(analysis,companyId,reference.journalSnapshot)})}>Investigate source review</button><button onClick={()=>void remove(reference)}>Remove from Home</button></header><div className="home-result-context"><span>{human(d.authority)}</span><span>{reference.kind==="EXACT"?"Pinned revision verified":"Legacy revision not recorded · showing the currently resolved revision"}</span>{d.context.map((item,index)=><span key={`${item.label}:${index}`}>{item.label}: {contextValue(item.value)}</span>)}</div><div className="home-result-grid"><table><thead><tr>{fields.map(field=><th key={field.key} scope="col" data-numeric={field.kind==="decimal"||field.kind==="integer"}>{field.label}{field.unit&&<small>{field.unit}</small>}</th>)}</tr></thead><tbody>{analysis.rows.slice(0,6).map(row=><tr key={row.key}>{fields.map(field=><td key={field.key} data-numeric={field.kind==="decimal"||field.kind==="integer"}>{field===fields[0]?<>{row.contributor_count>0?<button className="home-row-review" aria-label={`Review evidence for ${row.label}`} onClick={()=>reviewRow(analysis,reference,row.key)}>{cell(row.values[field.key],field)}</button>:<>{cell(row.values[field.key],field)}<small className="home-row-unavailable">No retained contributor</small></>}</>:cell(row.values[field.key],field)}</td>)}</tr>)}</tbody></table></div><footer><span>First {Math.min(6,analysis.rows.length)} of {analysis.total_rows} retained rows · Recorded {stamp(d.recorded_at)}</span><details><summary>Coverage & authority</summary>{d.coverage.map((item,index)=><p key={index}>{item.label}: {item.value}</p>)}<p>{d.unavailable_operations.map(human).join(" · ")}</p></details><details><summary>Advanced</summary><p>Descriptor {analysis.descriptor_sha256}</p><p>Receipt {d.receipt_hash}</p><p>Effective {d.valid_at} · known {d.known_at}</p></details></footer></article>;})}</>}
 </div>;
}
