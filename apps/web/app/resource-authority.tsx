"use client";
import {useEffect,useState} from "react";
import type {CanonicalResource} from "@finai/contracts";

type LifecycleState={target_state:string;epistemic_state:string;business_state:string;availability_state:string;reason:string};
type History={known_at:string;state:LifecycleState|null;events:Array<{recorded_at:string}>};
const label=(value:string)=>value.toLowerCase().replaceAll("_"," ");
export default function ResourceAuthority({token,resource}:{token:string;resource:CanonicalResource}) {
  const [result,setResult]=useState<{version:string;authorization:string;history:History}|null>(null);
  const [error,setError]=useState("");
  const [revision,setRevision]=useState(0);
  useEffect(()=>{
    let cancelled=false;const controller=new AbortController();
    async function load(){
      try {
        const response=await fetch(`/api/ontology/lifecycle/versions/${resource.version_id}?resource_id=${resource.resource_id}`,{
          headers:{Authorization:`Bearer ${token}`},cache:"no-store",signal:controller.signal
        });
        if(!response.ok)throw new Error("Material authority could not be checked for this version.");
        const history:History=await response.json();
        if(!cancelled){setResult({version:resource.version_id,authorization:token,history});setError("");}
      }catch(error){if(!cancelled){setResult(null);setError(error instanceof Error?error.message:"Authority unavailable");}}
    }
    void load();return()=>{cancelled=true;controller.abort();};
  },[token,resource.resource_id,resource.version_id,revision]);
  const history=result?.version===resource.version_id&&result.authorization===token?result.history:null;
  return <section className="g8-promotion" aria-label="Material authority and quality">
    <h3>Authority & quality</h3>
    <p>Definition review: {label(resource.authority_state)}. This records governance of the definition; material use has separate requirements.</p>
    {error?<p role="status">{error}</p>:!history?<p role="status">Checking this version&apos;s retained state...</p>:history.state?<>
      <dl><dt>Material authority</dt><dd>{label(history.state.target_state)}</dd>
        <dt>Business lifecycle</dt><dd>{label(history.state.business_state)}</dd>
        <dt>How it is known</dt><dd>{label(history.state.epistemic_state)}</dd>
        <dt>Availability & quality</dt><dd>{label(history.state.availability_state)}</dd></dl>
      <p>{history.state.reason}</p>
      <p>These states are independent. A live or reconciled business label does not grant authority to use the value in a report.</p>
      <p>Reports and actions must validate their required authority and exact input versions when they run.</p>
    </>:<p>No material authority has been established for this version. Definition approval alone does not authorize financial use.</p>}
    {history&&<small>Retained state as known at {new Date(history.known_at).toLocaleString()} · {history.events.length} reviewed events</small>}
    <button className="g8-link" onClick={()=>{setResult(null);setError("");setRevision(value=>value+1);}}>Refresh authority</button>
  </section>;
}
