"use client";
import type {CanonicalResource} from "@finai/contracts";
import {useResourceLifecycle} from "./use-resource-lifecycle";

const label=(value:string)=>value.toLowerCase().replaceAll("_"," ");
export default function ResourceAuthority({token,resource,knownAt}:{token:string;resource:CanonicalResource;knownAt?:string}) {
 const result=useResourceLifecycle(token,{resource_id:resource.resource_id,version_id:resource.version_id,known_at:knownAt});
 const history=result.history;
 return <section className="g8-promotion" aria-label="Definition review and retained material state">
  <h3>Definition review & material state</h3>
  <p>Definition review: {label(resource.authority_state)}. Evidence class: {label(resource.evidence_class)}.</p>
  <p>Registry approval records review of this definition. Material authority, how a value is known and its availability are separate observations.</p>
  {result.status==="error"?<p role="alert">{result.error} No material state is inferred from definition approval.</p>:!history?<p role="status">Checking this version&apos;s retained material state…</p>:history.state?<>
   <dl><dt>Material authority</dt><dd>{label(history.state.target_state)}</dd>
    <dt>Business lifecycle</dt><dd>{label(history.state.business_state)}</dd>
    <dt>How it is known</dt><dd>{label(history.state.epistemic_state)}</dd>
    <dt>Availability & quality</dt><dd>{label(history.state.availability_state)}</dd></dl>
   <p>{history.state.reason}</p>
  </>:<p>No reviewed material lifecycle state was recorded for this version by the selected knowledge cutoff. This does not establish its current state.</p>}
  {history&&<small>Retained state as known at {new Date(history.known_at).toLocaleString()} · {history.events.length} reviewed events</small>}
  <p>Historical state inspection does not authorize current use. Reports and actions must check their required authority, availability and exact inputs when they run.</p>
  <button className="g8-link" disabled={result.status==="loading"} onClick={result.refresh}>Refresh retained state</button>
 </section>;
}
