"use client";

import { useEffect, useRef, useState } from "react";
import "./runtime-state-workbench.css";

type Pin = { resource_id:string; version_id:string; content_hash:string; display_name:string };
type Observation = {
  request_id:string; run_id:string; proof_hash:string; recorded_at:string;
  assessment:{state:string; checked_at:string; age_seconds:number};
  reported_state:{desired_state:Pin; runtime_agent:Pin; deployment_target:Pin;
    desired_definition:{expected_code_sha256:string; expected_dependency_sha256:string; required_schema_version:number; max_observation_age_seconds:number};
    observation:{observed_at:string; observer_instance_id?:string; observer_started_at?:string; loaded_identity:{code_sha256:string; dependency_sha256:string}; disk_identity:{code_sha256:string; dependency_sha256:string}|null; disk_matches_loaded:boolean; health:Record<string,string>; database_schema_version:number};
    recorded_state:string; release_provenance:string};
};
type Cursor = {recorded_at:string;request_id:string};
type Page = {items:Observation[];next_cursor:Cursor|null};
const date = (value:string) => new Date(value).toLocaleString();
const human = (value:string) => value.toLowerCase().replaceAll("_", " ");

export default function RuntimeStateWorkbench({token,canRead}:{token:string;canRead:boolean}) {
  const [open,setOpen]=useState(false);
  return <details className="runtime-state-workbench" onToggle={event=>setOpen(event.currentTarget.open)}><summary>Runtime state &amp; health</summary><p>Retained observations of running components against reviewed expectations. Local development observations do not establish release acceptance or authorize deployment.</p>{open && (canRead ? <ObservedRuntime key={token} token={token}/> : <p role="status">Runtime observations require ontology administrator access for this identity.</p>)}</details>;
}

function ObservedRuntime({token}:{token:string}) {
  const [items,setItems]=useState<Observation[]>([]),[cursor,setCursor]=useState<Cursor|null>(null);
  const [target,setTarget]=useState(""),[selected,setSelected]=useState("");
  const [detail,setDetail]=useState<Observation|null>(null);
  const [loading,setLoading]=useState(false),[error,setError]=useState("");
  const [reading,setReading]=useState(false),[readError,setReadError]=useState("");
  const listRequest=useRef<AbortController|null>(null),detailRequest=useRef<AbortController|null>(null);
  useEffect(()=>()=>{listRequest.current?.abort();detailRequest.current?.abort();},[]);
  async function read(id:string) {
    detailRequest.current?.abort();const controller=new AbortController();detailRequest.current=controller;
    setSelected(id);setDetail(null);setReadError("");setReading(true);
    const timer=setTimeout(()=>controller.abort(),20000);
    try {const response=await fetch(`/api/ontology/runtime-observations/${encodeURIComponent(id)}`,{headers:{Authorization:`Bearer ${token}`},cache:"no-store",signal:controller.signal});
      const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==="string"?data.detail:`Observation unavailable (${response.status})`);
      if(detailRequest.current===controller)setDetail(data);
    } catch(err){if(detailRequest.current===controller)setReadError(controller.signal.aborted?"Observation request timed out. Retry to check its retained state.":err instanceof Error?err.message:"Observation unavailable");}
    finally{clearTimeout(timer);if(detailRequest.current===controller)setReading(false);}
  }
  async function load(older=false) {
    listRequest.current?.abort();const controller=new AbortController();listRequest.current=controller;setLoading(true);setError("");
    const params=new URLSearchParams({limit:"20"});if(older&&cursor){params.set("before_recorded_at",cursor.recorded_at);params.set("before_request_id",cursor.request_id);}
    const timer=setTimeout(()=>controller.abort(),20000);
    try {const response=await fetch(`/api/ontology/runtime-observations?${params}`,{headers:{Authorization:`Bearer ${token}`},cache:"no-store",signal:controller.signal});const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==="string"?data.detail:`History unavailable (${response.status})`);
      if(listRequest.current!==controller)return;const page=data as Page;
      setItems(previous=>older?[...previous,...page.items.filter(item=>!previous.some(row=>row.request_id===item.request_id))]:page.items);setCursor(page.next_cursor);
      if(!older){setTarget("");setSelected("");setDetail(null);detailRequest.current?.abort();detailRequest.current=null;setReading(false);setReadError("");}
    }catch(err){if(listRequest.current===controller)setError(controller.signal.aborted?"History request timed out. Retry to load observations.":err instanceof Error?err.message:"History unavailable");}
    finally{clearTimeout(timer);if(listRequest.current===controller)setLoading(false);}
  }
  const targets=Array.from(new Map(items.map(item=>[item.reported_state.deployment_target.resource_id,item.reported_state.deployment_target])).values());
  const visible=items.filter(item=>!target||item.reported_state.deployment_target.resource_id===target);
  const state=detail?.reported_state,observed=state?.observation,expected=state?.desired_definition;
  return <><div className="runtime-toolbar"><button type="button" disabled={loading} onClick={()=>void load()}>{loading?"Loading observations…":items.length?"Refresh retained history":"Load retained observations"}</button>{targets.length>0&&<label>Targets in loaded observations<select value={target} onChange={event=>{setTarget(event.target.value);setSelected("");setDetail(null);detailRequest.current?.abort();detailRequest.current=null;setReading(false);setReadError("");}}><option value="">All loaded targets</option>{targets.map(pin=><option key={pin.resource_id} value={pin.resource_id}>{pin.display_name}</option>)}</select></label>}</div>
    {error&&<p role="alert">{error}</p>}
    <div className="runtime-split"><section aria-label="Retained runtime observations"><p>{visible.length} loaded observations{target?" for this target":""}. This is retained history, not a list of all configured targets.</p>{visible.map(item=><button type="button" className="runtime-observation" key={item.request_id} aria-pressed={selected===item.request_id} onClick={()=>void read(item.request_id)}><strong>{item.reported_state.deployment_target.display_name}</strong><time>{date(item.reported_state.observation.observed_at)}</time><span>Recorded outcome: {human(item.reported_state.recorded_state)}</span></button>)}{cursor&&<button type="button" disabled={loading} onClick={()=>void load(true)}>Load older observations</button>}</section>
    <section aria-label="Selected runtime observation" aria-busy={reading}>{reading&&<p role="status">Reading retained observation and checking its age…</p>}{readError&&<p role="alert">{readError} <button type="button" onClick={()=>void read(selected)}>Retry observation</button></p>}{!selected&&<p>Select a retained observation to compare expectations with measured state.</p>}
      {detail&&state&&observed&&expected&&<><header><h3>{state.deployment_target.display_name}</h3><p>{state.desired_state.display_name} · Observer: {state.runtime_agent.display_name}</p></header><p className="runtime-assessment"><strong>{human(detail.assessment.state)}</strong> at readback · checked {date(detail.assessment.checked_at)}</p><p>Observed {date(observed.observed_at)}. Recorded outcome: {human(state.recorded_state)}. Age at readback: {Math.floor(detail.assessment.age_seconds)} seconds; reviewed freshness limit: {expected.max_observation_age_seconds} seconds. This is not a continuously refreshed health reading.</p>
      <table><thead><tr><th>Expectation</th><th>Observed result</th></tr></thead><tbody><tr><th>Loaded code matches reviewed identity</th><td>{observed.loaded_identity.code_sha256===expected.expected_code_sha256?"Matches":"Differs"}</td></tr><tr><th>Loaded dependencies match reviewed identity</th><td>{observed.loaded_identity.dependency_sha256===expected.expected_dependency_sha256?"Matches":"Differs"}</td></tr><tr><th>Database schema at least {expected.required_schema_version}</th><td>Observed version {observed.database_schema_version}</td></tr><tr><th>Files match loaded package</th><td>{observed.disk_identity===null?"Disk identity unavailable":observed.disk_matches_loaded?"Matches":"Differs"}</td></tr>{Object.entries(observed.health).map(([name,value])=><tr key={name}><th>{human(name)}</th><td>{human(value)}</td></tr>)}</tbody></table>
      <button type="button" disabled={reading} onClick={()=>void read(detail.request_id)}>Recheck observation age</button><details><summary>Retained references &amp; provenance</summary><p>Local development; release provenance is unattested. Package identity describes a startup snapshot, not a release attestation.</p><pre>{JSON.stringify({request_id:detail.request_id,run_id:detail.run_id,proof_hash:detail.proof_hash,recorded_at:detail.recorded_at,observer_instance_id:observed.observer_instance_id,observer_started_at:observed.observer_started_at,desired_state:state.desired_state,runtime_agent:state.runtime_agent,deployment_target:state.deployment_target,desired_definition:expected,loaded_identity:observed.loaded_identity,disk_identity:observed.disk_identity,release_provenance:state.release_provenance},null,2)}</pre></details></>}
    </section></div></>;
}
