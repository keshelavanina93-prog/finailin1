"use client";

import {useEffect,useState,type FormEvent} from "react";
import type {CanonicalResource,HistorySearchResult} from "@finai/contracts";
import {displayName} from "./display-name";
import {readable} from "./g8-model";
import {Badge,Empty} from "./g8-ui";
import "./history-explorer.css";

type Search = {object_type:string;q:string;effective_at:string;known_at:string;offset:number};
function initialSearch(key:string):Search {
  const now=new Date().toISOString();
  const empty={object_type:"",q:"",effective_at:now,known_at:now,offset:0};
  try {const value=JSON.parse(sessionStorage.getItem(key)??"null");
    if(value&&typeof value.q==="string"&&value.q.length<=200&&typeof value.effective_at==="string"&&typeof value.known_at==="string"&&Number.isFinite(Date.parse(value.effective_at))&&Number.isFinite(Date.parse(value.known_at)))
      return {...empty,object_type:typeof value.object_type==="string"&&/^[A-Za-z][A-Za-z0-9]{0,99}$/.test(value.object_type)?value.object_type:"",q:value.q,effective_at:value.effective_at,known_at:value.known_at};
  }catch{/* Search is usable when navigation storage is unavailable. */}
  return empty;
}
const localTime=(value:string)=>{const d=new Date(value);return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);};
const stamp=(value:string)=>new Date(value).toLocaleString();

export default function HistoryExplorer({token,companyId,companyName,contextKey,onInspect,onHistory,onTrace}:{
  token:string;companyId:string;companyName:string;contextKey:string;
  onInspect:(resource:CanonicalResource)=>void;onHistory:(resource:CanonicalResource)=>void;onTrace:(resource:CanonicalResource,knownAt:string)=>void;
}) {
  const storageKey=`${contextKey}:history-search:${companyId}`;
  const [search,setSearch]=useState(()=>initialSearch(storageKey));
  const [query,setQuery]=useState(search.q);
  const [effective,setEffective]=useState(localTime(search.effective_at));
  const [known,setKnown]=useState(localTime(search.known_at));
  const [result,setResult]=useState<HistorySearchResult|null>(null);
  const [error,setError]=useState("");const [loading,setLoading]=useState(!!companyId);
  const [revision,setRevision]=useState(0);
  useEffect(()=>{try{sessionStorage.setItem(storageKey,JSON.stringify(search));}catch{/* Optional navigation state only. */}},[storageKey,search]);
  useEffect(()=>{
    if(!companyId)return;
    const controller=new AbortController();
    const timer=setTimeout(()=>controller.abort(),20_000);
    const params=new URLSearchParams({company_id:companyId,...search,offset:String(search.offset),limit:"50"});
    if(!search.object_type)params.delete("object_type");
    void fetch(`/api/ontology/history-search?${params}`,{headers:{Authorization:`Bearer ${token}`},cache:"no-store",signal:controller.signal})
      .then(async response=>{const data=await response.json();if(!response.ok)throw Error(typeof data.detail==="string"?data.detail:"Recorded resources could not be loaded");if(!Array.isArray(data.type_facets)||!Number.isInteger(data.matched_count))throw Error("Resource categories are unavailable. Please retry when the history service is ready.");if(!controller.signal.aborted){setResult(data);setError("");setLoading(false);}})
      .catch(failure=>{if(!controller.signal.aborted){setError(failure instanceof Error?failure.message:"History service unavailable");setResult(null);setLoading(false);}else if(!cancelled){setError("History search timed out. Narrow the search or try again.");setResult(null);setLoading(false);}});
    let cancelled=false;
    return()=>{cancelled=true;clearTimeout(timer);controller.abort();};
  },[token,companyId,search,revision]);
  function submit(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();setResult(null);setError("");setLoading(true);
    setSearch({object_type:search.object_type,q:query.trim(),effective_at:new Date(effective).toISOString(),known_at:new Date(known).toISOString(),offset:0});
  }
  function page(offset:number){setLoading(true);setResult(null);setSearch({...search,offset});}
  return <section className="g8-history-explorer" aria-label="Company history explorer">
    <header><div><p className="overline">RECORDED BUSINESS CONTEXT</p><h2>Resources & history</h2><p>Find what was effective, using what G8 knew at the time.</p></div><Badge>{companyName||"Select a company"}</Badge></header>
    {!companyId?<Empty title="Choose a company">Use Companies above to search its recorded resources.</Empty>:<>
      <form onSubmit={submit} className="g8-history-search"><label>Find a business resource<input value={query} maxLength={200} onChange={e=>setQuery(e.target.value)} placeholder="Account, licence, company or source…"/></label><label>Effective at<input type="datetime-local" required value={effective} onChange={e=>setEffective(e.target.value)}/></label><label>Known by G8 at<input type="datetime-local" required value={known} onChange={e=>setKnown(e.target.value)}/></label><button disabled={loading} type="submit">{loading?"Searching…":"Search history"}</button><button type="button" disabled={loading} onClick={()=>{const now=new Date().toISOString();setEffective(localTime(now));setKnown(localTime(now));setLoading(true);setResult(null);setSearch({object_type:search.object_type,q:query.trim(),effective_at:now,known_at:now,offset:0});}}>Use current time</button></form>
      <p className="g8-subtle">Times use your local timezone. Results retain exact recorded versions; acceptance of a definition does not certify financial values.</p>
      {loading&&<p role="status">Searching authorized company history…</p>}
      {error&&<div role="alert"><p>{error}</p><button onClick={()=>{setError("");setLoading(true);setRevision(r=>r+1);}}>Retry search</button></div>}
      {result&&!loading&&<><nav className="g8-history-facets" aria-label="Resource categories"><button aria-pressed={!search.object_type} onClick={()=>{setLoading(true);setResult(null);setSearch({...search,object_type:"",offset:0});}}>All resource types <span>{result.type_facets.reduce((sum,facet)=>sum+facet.count,0)}</span></button>{result.type_facets.map(facet=><button key={facet.object_type} aria-pressed={search.object_type===facet.object_type} onClick={()=>{setLoading(true);setResult(null);setSearch({...search,object_type:facet.object_type,offset:0});}}>{readable(facet.object_type)} <span>{facet.count}</span></button>)}</nav><div className="g8-history-result-context"><strong>{result.matched_count} matching resources</strong><span>Effective {stamp(result.effective_at)}</span><span>Known {stamp(result.known_at)}</span></div>
        {!result.resources.length?<Empty title="No recorded resources match">Try a different name or time. No current version has been substituted.</Empty>:<div className="g8-table-scroll"><table><caption>Recorded resources for {companyName} · {result.offset+1}–{result.offset+result.resources.length}{result.has_more?" · more available":""}</caption><thead><tr><th scope="col">Business resource</th><th scope="col">Type / evidence</th><th scope="col">Definition state</th><th scope="col">Effective / recorded</th><th scope="col">Investigate</th></tr></thead><tbody>{result.resources.map(resource=><tr key={resource.version_id}><th scope="row"><button className="g8-link" onClick={()=>onInspect(resource)}>{displayName(resource.display_name)}</button></th><td>{readable(resource.object_type)}<small>{readable(resource.evidence_class)}</small></td><td><Badge tone={resource.authority_state==="REVOKED"?"bad":"neutral"}>{readable(resource.authority_state)}</Badge></td><td><time dateTime={resource.valid_from}>{stamp(resource.valid_from)}</time><small>Recorded {stamp(resource.system_from)}</small></td><td><div className="g8-history-row-actions"><button onClick={()=>onHistory(resource)}>Version history</button><button onClick={()=>onTrace(resource,result.known_at)}>Trace evidence</button></div></td></tr>)}</tbody></table></div>}
        <footer><span>Up to 50 resources per page · company relationships checked by the server</span><button disabled={!result.offset} onClick={()=>page(Math.max(0,result.offset-result.limit))}>Previous</button><button disabled={!result.has_more} onClick={()=>page(result.offset+result.limit)}>Next</button></footer>
      </>}
    </>}
  </section>;
}
