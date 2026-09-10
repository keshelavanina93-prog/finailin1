"use client";
import {useEffect,useState} from "react";
import type {CanonicalResource} from "@finai/contracts";
import {assertCompanyRegulation,regulatoryContextLabels,regulatoryStateLabels,type CompanyRegulationPage} from "./company-regulation-state";
import {displayName} from "./display-name";

type Props={token:string;company:CanonicalResource;validAt:string;knownAt:string;onInspect:(node:CanonicalResource,knownAt:string)=>void;onTrace?:(node:CanonicalResource,knownAt:string)=>void};
export default function CompanyRegulation(props:Props){return <Regulation key={JSON.stringify([props.token,props.company.resource_id,props.company.version_id,props.validAt,props.knownAt])} {...props}/>;}
function Regulation(props:Props){
 const [visited,setVisited]=useState(false),[offset,setOffset]=useState(0);
 return <details className="company-operating-resource-depth" onToggle={event=>{if(event.currentTarget.open)setVisited(true);}}><summary>Reviewed regulatory interpretations & effective dates</summary>
  {visited&&<RulePage key={offset} {...props} offset={offset} onPage={setOffset}/>}
 </details>;
}
function RulePage({token,company,validAt,knownAt,onInspect,onTrace,offset,onPage}:Props&{offset:number;onPage:(offset:number)=>void}){
 const [data,setData]=useState<CompanyRegulationPage|null>(null),[error,setError]=useState("");const [revision,setRevision]=useState(0);
 useEffect(()=>{const controller=new AbortController();let disposed=false;const timer=setTimeout(()=>controller.abort(),25000);
  const query=new URLSearchParams({legal_entity_id:company.resource_id,at:validAt,known_at:knownAt,offset:String(offset)});
  void fetch(`/api/ontology/regulation/rules?${query}`,{headers:{Authorization:`Bearer ${token}`},signal:controller.signal,cache:"no-store"}).then(async response=>{
   const value=await response.json();if(!response.ok)throw Error(typeof value.detail==="string"?value.detail:"Retained regulatory interpretations are unavailable.");
   assertCompanyRegulation(value,{company,validAt,knownAt,offset});if(!disposed&&!controller.signal.aborted)setData(value);
  }).catch(failure=>{if(!disposed)setError(controller.signal.aborted?"Regulatory retrieval timed out.":failure instanceof Error?failure.message:"Retained regulatory interpretations are unavailable.");}).finally(()=>clearTimeout(timer));
  return()=>{disposed=true;clearTimeout(timer);controller.abort();};
 },[token,company,validAt,knownAt,offset,revision]);
 return <section aria-label="Company retained regulatory interpretations"><p className="company-operating-note">Reviewed interpretations retained by G8. Stated legal dates come from each interpretation; activity and customer context have not been supplied. Applicability, compliance and a complete register of obligations are not established.</p>
  {error?<div className="company-operating-limitation" role="alert"><p>{error}</p><button onClick={()=>{setData(null);setError("");setRevision(value=>value+1);}}>Retry exact company snapshot</button></div>:!data?<p className="company-operating-note" role="status">Loading retained interpretations…</p>:<>
   {data.rules.length?<div className="company-operating-table"><table><thead><tr><th>Retained interpretation</th><th>Dates & stated status</th><th>Context still required</th><th>Evidence</th></tr></thead><tbody>{data.rules.map(({resource,assessment})=>{const definition=resource.attributes.definition as Record<string,unknown>;const day=(value:unknown)=>typeof value==="string"?value:"Not specified";return <tr key={resource.version_id}><th scope="row">{displayName(resource.display_name)}<details><summary>Recorded provision & obligation</summary><p>{day(definition.provision)}</p><p>{assessment.obligation}</p></details></th><td><span className="company-operating-reference">{regulatoryStateLabels[assessment.legal_state]}</span><small>From {day(definition.effective_from)} · until {day(definition.effective_to)} (exclusive)</small><small>Recorded deadline {day(definition.deadline)}</small></td><td>{regulatoryContextLabels[assessment.applicability]}<small>No effective obligation asserted by this view</small></td><td><span className="company-operating-row-actions"><button onClick={()=>onInspect(resource,knownAt)}>Inspect interpretation</button>{onTrace&&<button onClick={()=>onTrace(resource,knownAt)}>Trace evidence</button>}</span><details><summary>Advanced · exact references</summary><pre>{JSON.stringify({resource_id:resource.resource_id,version_id:resource.version_id,dependencies:data.rules.find(row=>row.resource.version_id===resource.version_id)?.dependencies},null,2)}</pre></details></td></tr>;})}</tbody></table></div>:<p className="company-operating-empty">No company interpretations returned on this registry page. This is not a finding that the company has no legal obligations.</p>}
   <div className="company-operating-pager"><button disabled={offset===0} onClick={()=>onPage(Math.max(0,offset-100))}>Previous registry page</button><span>Bounded registry page · {data.rules.length} company interpretations returned</span><button disabled={data.next_offset===null} onClick={()=>{if(data.next_offset!==null)onPage(data.next_offset);}}>Next registry page</button></div>
   <p className="company-operating-note">Company effective {data.at} · interpretations known {data.known_at}. No accounting effects created.</p>
  </>}
 </section>;
}
