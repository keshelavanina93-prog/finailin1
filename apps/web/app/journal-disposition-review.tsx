"use client";
import {useEffect,useRef,useState} from "react";
import {assertJournalAttempt,assertJournalDispositions,dispositionLabels,type DispositionPin,type DispositionScope,type JournalAttempt,type JournalDispositions} from "./journal-disposition-state";
import "./journal-disposition-review.css";

export type JournalDispositionContext=DispositionScope&{onInspect:(pin:DispositionPin,knownAt:string)=>void};
type Props={token:string;context:JournalDispositionContext;revision:number;onProposal:(id:string)=>void};
export default function JournalDispositionReview(props:Props){const c=props.context;return <Review key={`${props.token}:${c.companyId}:${c.requestId}:${c.invocationId}:${c.proposalId}`} {...props}/>;}
function Review({token,context,revision,onProposal}:Props){
 const {companyId,requestId,invocationId,proposalId}=context;
 const immutable=useRef<JournalAttempt|null>(null);
 const [result,setResult]=useState<{attempt:JournalAttempt;outcomes:JournalDispositions}|null>(null),[error,setError]=useState("");
 const [refresh,setRefresh]=useState(0),[settled,setSettled]=useState<string|null>(null),[selected,setSelected]=useState(""),[filter,setFilter]=useState("ALL");
 const generation=`${revision}:${refresh}`,pending=settled!==generation;
 useEffect(()=>{let disposed=false;const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),25000);
  async function get(path:string){const response=await fetch(`/api/ontology/company-journals/production/attempts/${requestId}${path}`,{headers:{Authorization:`Bearer ${token}`},cache:"no-store",signal:controller.signal});const data=await response.json();if(!response.ok)throw Error(response.status===401||response.status===403||response.status===404?"This retained journal request is unavailable in the current identity and company scope.":typeof data.detail==="string"?data.detail:"Journal outcome read is unavailable.");return data as unknown;}
  async function load(){try{
   const attempt=await get("");assertJournalAttempt(attempt,{companyId,requestId,invocationId,proposalId},immutable.current??undefined);
   if(disposed)return;immutable.current??=attempt;
   const outcomes=await get(`/dispositions?${new URLSearchParams({company_id:companyId})}`);assertJournalDispositions(outcomes,attempt);
   if(!disposed){setResult({attempt,outcomes});setError("");setSelected(current=>current||outcomes.items.find(item=>item.proposal_id===proposalId)?.coordinate||"");}
  }catch(cause){if(!disposed)setError(controller.signal.aborted?"Journal outcomes timed out. Retry the same immutable request.":cause instanceof Error?cause.message:"Journal outcomes are unavailable.");}
  finally{clearTimeout(timer);if(!disposed)setSettled(generation);}}
  void load();return()=>{disposed=true;clearTimeout(timer);controller.abort();};
 },[token,companyId,requestId,invocationId,proposalId,generation]);
 const outcomes=result?.outcomes,item=outcomes?.items.find(row=>row.coordinate===selected),withheld=pending||Boolean(error);
 const rows=outcomes?.items.filter(row=>filter==="ALL"||row.state===filter)??[];
 const showPin=(pin:DispositionPin)=>{if(outcomes&&!withheld)context.onInspect(pin,outcomes.observed_at);};
 return <section className="journal-dispositions" aria-label="Journal request outcomes">
  <header><div><h3>Source rows · review & publication</h3><p>Each outcome belongs to the original selected source coordinate. No financial total is calculated here.</p></div><button disabled={pending} onClick={()=>setRefresh(value=>value+1)}>Refresh outcomes</button></header>
  {pending&&<p role="status">Reading the immutable attempt and current per-row outcomes… Earlier drill controls are withheld.</p>}
  {error&&<p role="alert">{error} Earlier observations, if shown, are not a current result.</p>}
  {outcomes&&<><p className="journal-disposition-time">Read started <time dateTime={outcomes.observation_started_at}>{new Date(outcomes.observation_started_at).toLocaleString()}</time> · ended <time dateTime={outcomes.observed_at}>{new Date(outcomes.observed_at).toLocaleString()}</time>. Items were read separately; these counts are not an atomic batch snapshot.</p>
   <p>{outcomes.selection_count} selected coordinates · financial totals unavailable</p>
   <label>Show outcomes <select value={filter} onChange={event=>setFilter(event.target.value)}><option value="ALL">All selected coordinates</option>{Object.entries(outcomes.counts).map(([state,count])=><option key={state} value={state}>{dispositionLabels[state as keyof typeof dispositionLabels]} · {count} observed</option>)}</select></label>
   <fieldset disabled={withheld}><legend className="journal-disposition-sr">Exact retained outcome drill</legend><div className="journal-disposition-table"><table><thead><tr><th>Original source coordinate</th><th>Observed outcome</th><th>Review / evidence</th></tr></thead><tbody>{rows.map(row=><tr key={row.coordinate} aria-selected={row.coordinate===selected}><th scope="row"><button aria-pressed={row.coordinate===selected} onClick={()=>setSelected(row.coordinate)}>{row.coordinate}</button></th><td><span data-disposition={row.state}>{dispositionLabels[row.state]}</span></td><td>{row.proposal_id&&row.review?<button onClick={()=>{setSelected(row.coordinate);onProposal(row.proposal_id!);}}>Review exact proposal</button>:<span>{row.state==="EXCLUDED"?"Excluded from original source eligibility":row.state==="BLOCKED"?"Original requirements not satisfied":"No retained review is available"}</span>}</td></tr>)}</tbody></table></div>
    {!rows.length&&<p>No observed items match this outcome filter. The original selection is unchanged.</p>}
    {item&&<section className="journal-disposition-selection" aria-label="Selected source row outcome"><h4>{item.coordinate} · {dispositionLabels[item.state]}</h4>{!rows.includes(item)&&<p>The selected coordinate is outside the current filter; its exact selection is retained.</p>}
     {item.review?.decision==="APPROVED"&&!item.publication&&<p role="status">Review approved, but exact publication is unavailable. This item is not shown as published.</p>}
     {item.review?.rationale&&<p>Review rationale: {item.review.rationale}</p>}
     {item.blockers.length>0&&<ul>{item.blockers.map((blocker,index)=><li key={index}>{blocker.detail??blocker.code.toLowerCase().replaceAll("_"," ")}</li>)}</ul>}
     <div className="journal-disposition-drill">{item.publication&&<><button onClick={()=>showPin(item.publication!.journal)}>Inspect published journal</button>{item.publication.lines.map((line,index)=><button key={line.version_id} onClick={()=>showPin(line)}>Inspect published line {index+1} & source evidence</button>)}</>}<button onClick={()=>showPin(result!.attempt.binding)}>Inspect original source binding</button></div>
     <p>Original coordinate: {item.coordinate}. Source binding and published-line drill open exact retained versions in NYX without leaving this review. Original cell values are not included in this outcome response.</p>
     <details><summary>Advanced · exact selected item</summary><pre>{JSON.stringify(item,null,2)}</pre></details>
    </section>}
   </fieldset>
   {outcomes.source_exclusions.length>0&&<details><summary>Original source exclusions · {outcomes.source_exclusions.length}</summary><p>These exclusions are retained from the original source and may be outside the selected coordinates.</p><ul>{outcomes.source_exclusions.map(row=><li key={row.coordinate}>{row.coordinate}{row.blockers.map((blocker,index)=><p key={index}>{blocker.detail??blocker.code.toLowerCase().replaceAll("_"," ")}</p>)}</li>)}</ul></details>}
   <details><summary>Advanced · immutable request & read observation</summary><pre>{JSON.stringify({request:result!.attempt.request,attempt_receipt_hash:outcomes.attempt_receipt_hash,source_sha256:outcomes.source_sha256,source_receipt_hash:result!.attempt.source_receipt_hash,binding:outcomes.binding,receipt_hash:outcomes.receipt_hash,consistency:outcomes.consistency,observation_started_at:outcomes.observation_started_at,observed_at:outcomes.observed_at,financial_totals:outcomes.financial_totals},null,2)}</pre></details>
  </>}
 </section>;
}
