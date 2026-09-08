"use client";
import {useEffect,useState} from "react";
import type {AnalysisField,AnalysisValue,AnalysisProjection} from "@finai/contracts";
import {assertProjection,formatAnalysisDecimal} from "./semantic-analysis-state";
import {homeAnalysisPins,clearHomeAnalysisPins,subscribeHomeAnalysisPins} from "./company-home-pins";
import {useSourceReview} from "./source-review-navigation";
import {displayedAnalysisView} from "./source-review-route";
const human=(value:string)=>value.replaceAll("_"," ").toLowerCase();
const contextValue=(value:string)=>/^(?:[a-f0-9]{64}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})$/i.test(value)?"Exact reference in source review":value;
const stamp=(value:string)=>new Date(value).toLocaleString();
function cell(value:AnalysisValue,field:AnalysisField){
 if(value.state!=="VALUE")return value.state==="NULL"?"Recorded null":"Not recorded";
 if(field.presentation&&typeof value.value==="string")return formatAnalysisDecimal(value.value,field);
 return value.label??String(value.value);
}

type Props={token:string;companyId:string;onData:()=>void};
export default function HomeSourceAnalyses(props:Props){return <SourceAnalyses key={JSON.stringify([props.token,props.companyId])} {...props}/>;}
function SourceAnalyses({token,companyId,onData}:Props){
 const open=useSourceReview();const [analyses,setAnalyses]=useState<AnalysisProjection[]>([]);
 const [errors,setErrors]=useState<string[]>([]),[busy,setBusy]=useState(true),[revision,setRevision]=useState(0);
 useEffect(()=>{let controller:AbortController|null=null,timer:ReturnType<typeof setTimeout>|undefined,disposed=false,generation=0;
  async function load(){const requestGeneration=++generation;controller?.abort();clearTimeout(timer);
   const requestController=new AbortController();controller=requestController;
   timer=setTimeout(()=>requestController.abort(),25000);
   setBusy(true);setErrors([]);setAnalyses([]);
   try{
   const ids=await homeAnalysisPins(token,companyId);
   if(disposed||requestGeneration!==generation)return;
   const entries=await Promise.all(ids.map(async invocation_id=>{try{
    const request={company_id:companyId,invocation_id};
    const response=await fetch("/api/ontology/analysis/project",{method:"POST",headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},body:JSON.stringify(request),cache:"no-store",signal:requestController.signal});
    const data=await response.json();if(!response.ok)throw Error(response.status===401||response.status===403?"A saved analysis is unavailable to this identity.":"A saved analysis could not be restored. Its reference remains saved.");
    assertProjection(data,request);return {analysis:data as AnalysisProjection,error:null};
   }catch(failure){return {analysis:null,error:requestController.signal.aborted?"Saved analysis retrieval timed out.":String(failure)};}}));
   if(!disposed&&requestGeneration===generation){setAnalyses(entries.flatMap(item=>item.analysis?[item.analysis]:[]));setErrors(entries.flatMap(item=>item.error?[item.error]:[]));}
  }catch{if(!disposed&&requestGeneration===generation)setErrors(["Device analysis references are unavailable. Company condition remains independently available."]);}finally{if(!disposed&&requestGeneration===generation){clearTimeout(timer);setBusy(false);}}}
  const unsubscribe=subscribeHomeAnalysisPins(token,companyId,()=>void load(),()=>{if(!disposed){setErrors(["Device analysis references are unavailable. Company condition remains independently available."]);setBusy(false);}});
  return()=>{disposed=true;unsubscribe();controller?.abort();clearTimeout(timer);};
 },[token,companyId,revision]);
 function retry(){setBusy(true);setErrors([]);setAnalyses([]);setRevision(value=>value+1);}
 return <div className="home-source-analysis-content"><p className="home-scope-note">Each result retains its own financial period, currency and authority. Source movement is not a financial statement.</p>
 {busy?<p role="status">Restoring saved source references…</p>:<>{errors.length>0&&<div role="status" className="home-source-analysis-error">{errors.map((error,index)=><p key={index}>{error}</p>)}<button onClick={retry}>Retry source references</button><button onClick={()=>void clearHomeAnalysisPins(token,companyId).catch(()=>setErrors(["Device references could not be cleared."]))}>Clear device references</button><p>Company condition and work are independent of these saved source references.</p></div>}
   {!analyses.length?<div className="home-pin-prompt"><p>{errors.length?"Saved source analyses are unavailable. Their references remain saved.":<>No analyses pinned for this company. Open a verified source review and choose <strong>Pin to company Home</strong>.</>}</p><button onClick={onData}>Open Data & evidence</button></div>:analyses.map(analysis=>{const d=analysis.descriptor;const fields=d.fields.slice(0,4);return <article className="home-analysis" key={d.invocation_id}><header><h3>{d.title}</h3><button onClick={()=>open({companyId,invocationId:d.invocation_id,view:displayedAnalysisView(analysis,companyId)})}>Investigate source review</button></header><div className="home-result-context"><span>{human(d.authority)}</span>{d.context.map((item,index)=><span key={`${item.label}:${index}`}>{item.label}: {contextValue(item.value)}</span>)}</div><div className="home-result-grid"><table><thead><tr>{fields.map(field=><th key={field.key}>{field.label}{field.unit&&<small>{field.unit}</small>}</th>)}</tr></thead><tbody>{analysis.rows.slice(0,6).map(row=><tr key={row.key}>{fields.map(field=><td key={field.key}>{cell(row.values[field.key],field)}</td>)}</tr>)}</tbody></table></div><footer><span>First {Math.min(6,analysis.rows.length)} of {analysis.total_rows} retained rows · Recorded {stamp(d.recorded_at)}</span><details><summary>Coverage & authority</summary>{d.coverage.map((item,index)=><p key={index}>{item.label}: {item.value}</p>)}<p>{d.unavailable_operations.map(human).join(" · ")}</p></details><details><summary>Advanced</summary><p>Descriptor {analysis.descriptor_sha256}</p><p>Receipt {d.receipt_hash}</p><p>Effective {d.valid_at} · known {d.known_at}</p></details></footer></article>;})}</>}
 </div>;
}
