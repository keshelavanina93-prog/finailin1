"use client";

import {useEffect,useState} from "react";

export type LifecycleState={target_state:string;epistemic_state:string;business_state:string;availability_state:string;reason:string;certification_receipt_id?:string|null;certification_contract?:{resource_id:string;version_id:string}|null};
export type LifecycleHistory={subject:{resource_id:string;version_id:string};purpose:"HISTORICAL_LIFECYCLE";known_at:string;state:LifecycleState|null;events:Array<{recorded_at:string;certification_proof_hash?:string|null}>};
export type CertificationReceipt={receipt_id:string;proof_hash:string;recorded_at:string;current_use_authorized:false;proof:{purpose:"CANONICAL_DEFINITION_CONFORMANCE";status:"PASS";subject:{resource_id:string;version_id:string};contract:{resource_id:string;version_id:string};contract_attributes:{definition:{claim:"CANONICAL_DEFINITION_CONFORMANCE";meaning:string;limitations:string}}}};
type Target={resource_id:string;version_id:string;known_at?:string};
type Response={key:string;history:LifecycleHistory|null;error:string;certification?:CertificationReceipt|null;certificationError?:string};

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
    let certification:CertificationReceipt|null=null;let certificationError="";
    if(history.state?.target_state==="CERTIFIED"){
     try{
      const pin=history.state.certification_contract;const receiptId=history.state.certification_receipt_id;
      if(!pin||!receiptId)throw new Error("The recorded certified state has no exact retained certification binding.");
      const receiptResponse=await fetch(`/api/ontology/certifications/receipts/${encodeURIComponent(receiptId)}`,{headers:{Authorization:`Bearer ${token}`},cache:"no-store",signal:controller.signal});
      if(!receiptResponse.ok)throw new Error("The retained certification proof is unavailable.");
      const receipt:CertificationReceipt=await receiptResponse.json();const proof=receipt.proof;
      if(!receipt.proof_hash||receipt.proof_hash!==history.events.at(-1)?.certification_proof_hash||receipt.receipt_id!==receiptId||proof?.subject?.resource_id!==resourceId||proof.subject.version_id!==versionId||proof.contract?.resource_id!==pin.resource_id||proof.contract.version_id!==pin.version_id||proof.purpose!=="CANONICAL_DEFINITION_CONFORMANCE"||proof.status!=="PASS"||proof.contract_attributes?.definition?.claim!=="CANONICAL_DEFINITION_CONFORMANCE"||!Number.isFinite(Date.parse(receipt.recorded_at))||Date.parse(receipt.recorded_at)>Date.parse(history.known_at)||receipt.current_use_authorized!==false)throw new Error("The certification proof does not match this version, contract and knowledge cutoff.");
      certification=receipt;
     }catch(error){certificationError=error instanceof Error?error.message:"Certification proof unavailable";}
    }
    if(!disposed)setResponse({key,history,error:"",certification,certificationError});
   })
   .catch(error=>{if(!disposed)setResponse({key,history:null,error:controller.signal.aborted?"Retained material state timed out. Retry this version's state check.":error instanceof Error?error.message:"Retained material state unavailable"});})
   .finally(()=>clearTimeout(timer));
  return()=>{disposed=true;clearTimeout(timer);controller.abort();};
 },[token,resourceId,versionId,knownAt,key]);
 const current=enabled&&response?.key===key?response:null;
 return {status:!enabled?"not_requested" as const:!current?"loading" as const:current.error?"error" as const:"ready" as const,history:current?.history??null,certification:current?.certification??null,certificationError:current?.certificationError??"",error:current?.error??"",refresh:()=>setRevision(value=>value+1)};
}
