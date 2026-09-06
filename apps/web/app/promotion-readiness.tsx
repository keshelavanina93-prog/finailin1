"use client";
import {useEffect,useRef,useState, type FormEvent} from "react";
import type {PromotionCheck, ResourceProposalDetail} from "@finai/contracts";
import {Badge} from "./g8-ui";

type Props = {token:string;proposalId:string;onDecision?:(detail:ResourceProposalDetail)=>void};
type Checked = PromotionCheck & {change_names:string[]};
export default function PromotionReadiness(props:Props) {
  return <PromotionPanel key={`${props.proposalId}:${props.token}`} {...props}/>;
}
function PromotionPanel({token,proposalId,onDecision}:Props) {
  const [result,setResult]=useState<Checked|null>(null);
  const [error,setError]=useState("");
  const [revision,setRevision]=useState(0);
  const [busy,setBusy]=useState(true);
  const [submitting,setSubmitting]=useState(false);
  const [rationale,setRationale]=useState("");
  const [decision,setDecision]=useState<"APPROVED"|"REJECTED">("APPROVED");
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
  async function recordDecision(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if(submitting || busy || !result || result.status==="DECIDED" || (decision==="APPROVED" && result.status!=="ELIGIBLE"))return;
    setSubmitting(true);setError("");setReceipt("");
    try {
      const response=await fetch(`/api/ontology/proposals/${proposalId}/decision`,{
        method:"POST",headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},
        body:JSON.stringify({decision,rationale})
      });
      const data=await response.json();
      if(!active.current)return;
      if(!response.ok)throw new Error(typeof data.detail === "string" ? data.detail : "The decision could not be recorded");
      if(data.decision!=="APPROVED" && data.decision!=="REJECTED")throw new Error("No retained decision was returned. Refresh the proposal before retrying.");
      setReceipt(data.decision==="APPROVED"
        ? `Approved ${data.proposal.mutations.length} changes together. The review and accepted versions are retained.`
        : "Proposal rejected. The reason is retained; accepted business records were not changed.");
      onDecision?.(data as ResourceProposalDetail);
      setRationale("");
    } catch(error) {if(active.current)setError(error instanceof Error ? error.message : "The decision could not be recorded");}
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
    {result && result.status!=="DECIDED" && <form className="resource-form" onSubmit={recordDecision}>
      <details><summary>{result.change_names.length} changes reviewed together</summary><ul>{result.change_names.map((name,index)=><li key={index}>{name}</li>)}</ul></details>
      <label>Decision<select value={decision} disabled={submitting} onChange={event=>setDecision(event.target.value as "APPROVED"|"REJECTED")}>
        <option value="APPROVED" disabled={result.status!=="ELIGIBLE"}>Approve changes</option>
        <option value="REJECTED">Reject proposal</option>
      </select></label>
      <label>Review rationale<textarea value={rationale} onChange={event=>setRationale(event.target.value)} minLength={10} maxLength={2000} required disabled={submitting}/></label>
      <button disabled={busy || submitting || rationale.trim().length<10 || (decision==="APPROVED" && result.status!=="ELIGIBLE")}>{submitting ? "Recording review..." : decision==="REJECTED" ? "Reject this proposal" : `Approve ${result.change_names.length} changes together`}</button>
      <small>{decision==="REJECTED" ? "Rejection closes this proposal and retains your reason. A correction requires a new proposal." : "All changes are promoted in one transaction. Changed dependencies or failed evaluations block the entire approval."}</small>
    </form>}
    {result?.decision && <p>Recorded decision: {result.decision.toLowerCase()}</p>}
    {result && <small>Checked {new Date(result.checked_at).toLocaleTimeString()} · advisory; this check does not approve</small>}
    <button className="g8-link" disabled={busy || submitting} onClick={()=>{setError("");setRevision(value=>value+1);}}>Recheck eligibility</button>
  </section>;
}
