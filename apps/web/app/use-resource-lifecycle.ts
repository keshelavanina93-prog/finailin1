"use client";

import {useEffect,useState} from "react";

export type LifecycleState={target_state:string;epistemic_state:string;business_state:string;availability_state:string;reason:string};
export type LifecycleHistory={subject:{resource_id:string;version_id:string};purpose:"HISTORICAL_LIFECYCLE";known_at:string;state:LifecycleState|null;events:Array<{recorded_at:string}>};
type Target={resource_id:string;version_id:string;known_at?:string};
type Response={key:string;history:LifecycleHistory|null;error:string};

/** Read retained state at one version/cutoff. This is never a consumption grant. */
export function useResourceLifecycle(token:string|undefined,target:Target|null){
 const [revision,setRevision]=useState(0);
 const [response,setResponse]=useState<Response|null>(null);
 const resourceId=target?.resource_id;const versionId=target?.version_id;const knownAt=target?.known_at;
 const key=JSON.stringify([token,resourceId,versionId,knownAt,revision]);
 const enabled=Boolean(token&&resourceId&&versionId);
 useEffect(()=>{
  if(!token||!resourceId||!versionId)return;
  const controller=new AbortController();let disposed=false;
  const timer=setTimeout(()=>controller.abort(),20000);
  const params=new URLSearchParams({resource_id:resourceId});if(knownAt)params.set("known_at",knownAt);
  void fetch(`/api/ontology/lifecycle/versions/${encodeURIComponent(versionId)}?${params}`,{headers:{Authorization:`Bearer ${token}`},cache:"no-store",signal:controller.signal})
   .then(async result=>{
    if(!result.ok)throw new Error("Retained material state could not be checked for this version.");
    const history:LifecycleHistory=await result.json();
    if(history.subject?.resource_id!==resourceId||history.subject?.version_id!==versionId||history.purpose!=="HISTORICAL_LIFECYCLE"||!Number.isFinite(Date.parse(history.known_at))||(knownAt&&Date.parse(history.known_at)!==Date.parse(knownAt)))throw new Error("Material state did not match the selected version and knowledge cutoff.");
    if(!disposed&&!controller.signal.aborted)setResponse({key,history,error:""});
   })
   .catch(error=>{if(!disposed)setResponse({key,history:null,error:controller.signal.aborted?"Retained material state timed out. Retry this version's state check.":error instanceof Error?error.message:"Retained material state unavailable"});})
   .finally(()=>clearTimeout(timer));
  return()=>{disposed=true;clearTimeout(timer);controller.abort();};
 },[token,resourceId,versionId,knownAt,key]);
 const current=enabled&&response?.key===key?response:null;
 return {status:!enabled?"not_requested" as const:!current?"loading" as const:current.error?"error" as const:"ready" as const,history:current?.history??null,error:current?.error??"",refresh:()=>setRevision(value=>value+1)};
}
