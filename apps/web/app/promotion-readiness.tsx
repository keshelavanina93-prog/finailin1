"use client";
import {useEffect,useRef,useState, type FormEvent} from "react";
import type {PromotionCheck} from "@finai/contracts";
import {Badge} from "./g8-ui";

type Props = {token:string;proposalId:string};
type Checked = PromotionCheck & {change_names:string[]};
export default function PromotionReadiness(props:Props) {
  return <PromotionPanel key={`${props.proposalId}:${props.token}`} {...props}/>;
}
function PromotionPanel({token,proposalId}:Props) {
  const [result,setResult]=useState<Checked|null>(null);
  const [error,setError]=useState("");
  const [revision,setRevision]=useState(0);
  const [busy,setBusy]=useState(true);
  const [submitting,setSubmitting]=useState(false);
  const [rationale,setRationale]=useState("");
  const [receipt,setReceipt]=useState("");
  const active=useRef(true);
  useEffect(()=>{active.current=true;return()=>{active.current=false;};},[]);
  useEffect(()=>{
    const controller=new AbortController();let cancelled=false;
    async function load(){
      setBusy(true);setResult(null);
      try {
        const options={headers:{Authorization:`Bearer ${token}`},cache:"no-store" as const,signal:controller.signal};
        const [response,proposalResponse]=await Promise.all([
          fetch(`/api/ontology/proposals/${proposalId}/promotion-check`,options),
          fetch(`/api/ontology/proposals/${proposalId}`,options)
        ]);
        const data=await response.json();
        if(!response.ok)throw new Error(typeof data.detail === "string" ? data.detail : "Promotion check unavailable");
        if(!proposalResponse.ok)throw new Error("The complete change set is unavailable; approval is disabled.");
        const detail=await proposalResponse.json();
        if(!cancelled)setResult({...data,change_names:detail.proposal.mutations.map((item:{display_name:string})=>item.display_name)});
      } catch(error) {if(!cancelled)setError(error instanceof Error ? error.message : "Promotion check unavailable");}
      finally {if(!cancelled)setBusy(false);}
    }
    void load();return()=>{cancelled=true;controller.abort();};
  },[token,proposalId,revision]);
  async function approve(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if(submitting || busy || result?.status!=="ELIGIBLE")return;
    setSubmitting(true);setError("");setReceipt("");
    try {
      const response=await fetch(`/api/ontology/proposals/${proposalId}/decision`,{
        method:"POST",headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},
        body:JSON.stringify({decision:"APPROVED",rationale})
      });
      const data=await response.json();
      if(!active.current)return;
      if(!response.ok)throw new Error(typeof data.detail === "string" ? data.detail : "Approval could not be recorded");
      setReceipt(`Approved ${data.proposal.mutations.length} changes together. The review and accepted versions are retained.`);
      setRationale("");
    } catch(error) {if(active.current)setError(error instanceof Error ? error.message : "Approval could not be recorded");}
    finally {if(active.current){setSubmitting(false);setRevision(value=>value+1);}}
  }
  return <section className="g8-promotion" aria-label="Current promotion eligibility">
    <header><h3>Promotion eligibility</h3><Badge tone={result?.status === "ELIGIBLE" ? "good" : "warning"}>{busy ? "Checking" : result?.status ?? "Unavailable"}</Badge></header>
    {error && <p role="status">{error}</p>}
    {result?.blockers.map(reason=><p className="g8-inline-error" key={reason}>{reason}</p>)}
    {result?.status === "ELIGIBLE" && <p>Current dependencies and policy checks pass for this identity. Approval will validate them again.</p>}
    {result && <section aria-label="Retained evaluation evidence"><h4>Evaluation evidence</h4>
      {result.evaluation ? <><p>Structural checks: {result.evaluation.status === "PASS" ? "Passed" : "Failed"}</p><p>{result.evaluation.scope}</p>
        <ul>{result.evaluation.checks.map(check=><li key={check}>{check}</li>)}</ul>
        <small>Recorded {new Date(result.evaluation.recorded_at).toLocaleString()}</small>
        <details><summary>Evidence trace</summary><p>{result.evaluation.evaluator}</p><p className="full-hash">Proposal: {result.evaluation.proposal_hash}</p><p className="full-hash">Evaluation binding: {result.evaluation.binding_hash}</p></details>
      </> : <p>No evaluation was retained for this proposal. Submit a refreshed proposal before promotion.</p>}
    </section>}
    {receipt && <p role="status">{receipt}</p>}
    {result?.status === "ELIGIBLE" && <form className="resource-form" onSubmit={approve}>
      <details><summary>{result.change_names.length} changes reviewed together</summary><ul>{result.change_names.map((name,index)=><li key={index}>{name}</li>)}</ul></details>
      <label>Review rationale<textarea value={rationale} onChange={event=>setRationale(event.target.value)} minLength={10} maxLength={2000} required disabled={submitting}/></label>
      <button disabled={busy || submitting || rationale.trim().length<10}>{submitting ? "Recording review..." : `Approve ${result.change_names.length} changes together`}</button>
      <small>All changes are promoted in one transaction. Changed dependencies or failed evaluations block the entire approval.</small>
    </form>}
    {result?.decision && <p>Recorded decision: {result.decision.toLowerCase()}</p>}
    {result && <small>Checked {new Date(result.checked_at).toLocaleTimeString()} · advisory; this check does not approve</small>}
    <button className="g8-link" disabled={busy || submitting} onClick={()=>{setError("");setRevision(value=>value+1);}}>Recheck eligibility</button>
  </section>;
}
