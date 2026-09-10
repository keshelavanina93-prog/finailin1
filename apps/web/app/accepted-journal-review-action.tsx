"use client";
import {useEffect,useRef,useState} from "react";
import {acceptedJournalTarget} from "./accepted-journal-review";
import {useSourceReview} from "./source-review-navigation";

type Props={token:string;companyId:string;invocationId:string;disabled?:boolean};
export default function AcceptedJournalReviewAction(props:Props){return <Review key={`${props.token}:${props.companyId}:${props.invocationId}`} {...props}/>;}
function Review({token,companyId,invocationId,disabled}:Props){
 const open=useSourceReview(),pending=useRef<AbortController|null>(null),generation=useRef(0);
 const [busy,setBusy]=useState(false),[error,setError]=useState("");
 useEffect(()=>()=>{generation.current++;pending.current?.abort();},[]);
 async function review(){
  pending.current?.abort();const controller=new AbortController();pending.current=controller;const epoch=++generation.current;
  const snapshotAt=new Date().toISOString(),timer=setTimeout(()=>controller.abort(),25000);
  setBusy(true);setError("");
  try{
   const response=await fetch(`/api/ontology/company-journals/reconciliation/projection?${new URLSearchParams({snapshot_at:snapshotAt})}`,{method:"POST",headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},body:JSON.stringify({company_id:companyId,invocation_id:invocationId}),cache:"no-store",signal:controller.signal});
   const value=await response.json();if(!response.ok)throw Error(response.status===404||response.status===503?"Accepted-journal review is unavailable in this runtime. The original source result remains available.":typeof value.detail==="string"?value.detail:"Accepted-journal review is unavailable for this source.");
   const target=acceptedJournalTarget(value,companyId,invocationId,snapshotAt);
   if(epoch===generation.current)open(target);
  }catch(failure){if(epoch===generation.current)setError(controller.signal.aborted?"Accepted-journal review timed out. Retry to request a new snapshot.":failure instanceof Error?failure.message:"Accepted-journal review is unavailable.");}
  finally{clearTimeout(timer);if(epoch===generation.current)setBusy(false);}
 }
 return <div className="posted-journal-review"><button disabled={disabled||busy} onClick={()=>void review()}>{busy?"Matching accepted journal evidence…":"Review accepted journals"}</button><small>Match this retained source to reviewed journal evidence at a fixed snapshot.</small>{error&&<p role="alert">{error}</p>}</div>;
}
