"use client";
import {useEffect,useState} from "react";
import type {PromotionCheck} from "@finai/contracts";
import {Badge} from "./g8-ui";

export default function PromotionReadiness({token,proposalId}: {token:string;proposalId:string}) {
  const [result,setResult]=useState<PromotionCheck | null>(null);
  const [error,setError]=useState(""); const [revision,setRevision]=useState(0);
  const [busy,setBusy]=useState(true);
  useEffect(()=>{
    const controller=new AbortController();let cancelled=false;
    async function load(){setBusy(true);setError("");setResult(null);
      try{const response=await fetch(`/api/ontology/proposals/${proposalId}/promotion-check`,{headers:{Authorization:`Bearer ${token}`},cache:"no-store",signal:controller.signal});
        const data=await response.json();if(!response.ok)throw new Error(typeof data.detail === "string" ? data.detail : "Promotion check unavailable");
        if(!cancelled)setResult(data);
      }catch(error){if(!cancelled)setError(error instanceof Error ? error.message : "Promotion check unavailable");}
      finally{if(!cancelled)setBusy(false);}
    }
    void load();return()=>{cancelled=true;controller.abort();};
  },[token,proposalId,revision]);
  return <section className="g8-promotion" aria-label="Current promotion eligibility"><header><h3>Promotion eligibility</h3><Badge tone={result?.status === "ELIGIBLE" ? "good" : "warning"}>{busy ? "Checking" : result?.status ?? "Unavailable"}</Badge></header>
    {error && <p role="status">{error}</p>}{result?.blockers.map(reason=><p className="g8-inline-error" key={reason}>{reason}</p>)}
    {result?.status === "ELIGIBLE" && <p>Current dependencies and policy checks pass for this identity. Approval will validate them again.</p>}
    {result && <section aria-label="Retained evaluation evidence"><h4>Evaluation evidence</h4>
      {result.evaluation ? <><p>Structural checks: {result.evaluation.status === "PASS" ? "Passed" : "Failed"}</p><p>{result.evaluation.scope}</p>
        <ul>{result.evaluation.checks.map(check => <li key={check}>{check}</li>)}</ul>
        <small>Recorded {new Date(result.evaluation.recorded_at).toLocaleString()}</small>
        <details><summary>Evidence trace</summary><p>{result.evaluation.evaluator}</p><p className="full-hash">Proposal: {result.evaluation.proposal_hash}</p><p className="full-hash">Evaluation binding: {result.evaluation.binding_hash}</p></details>
      </> : <p>No evaluation was retained for this proposal. Submit a refreshed proposal before promotion.</p>}
    </section>}
    {result && <small>Checked {new Date(result.checked_at).toLocaleTimeString()} · advisory; this check does not approve</small>}
    <button className="g8-link" disabled={busy} onClick={()=>setRevision(value=>value+1)}>Recheck eligibility</button></section>;
}
