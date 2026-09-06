"use client";

import {useEffect,useState} from "react";
import type {CanonicalDetail,CanonicalResource} from "@finai/contracts";
import {displayName} from "./display-name";
import {readable} from "./g8-model";
import {Badge} from "./g8-ui";
import {compareVersions,type HistorySelection,type HistoryValue} from "./history-model";
import "./operator-history.css";

const timestamp=(v:string)=>new Date(v).toLocaleString();
const identity=/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
export function Value({entry,onInspect}:{entry:HistoryValue;onInspect:(id:string)=>void}) {
  if(!entry.present)return <span className="g8-subtle">Not returned</span>;
  if(entry.value===null)return <span className="g8-subtle">Not set</span>;
  if(typeof entry.value==="string"&&identity.test(entry.value))return <button className="g8-link" onClick={()=>onInspect(entry.value as string)}>Inspect linked object</button>;
  if(Array.isArray(entry.value))return <ul>{entry.value.map((v,i)=><li key={i}><Value entry={{present:true,value:v}} onInspect={onInspect}/></li>)}</ul>;
  if(typeof entry.value==="object")return <dl>{Object.entries(entry.value as Record<string,unknown>).map(([k,v])=><div key={k}><dt>{readable(k)}</dt><dd><Value entry={{present:true,value:v}} onInspect={onInspect}/></dd></div>)}</dl>;
  return <span>{typeof entry.value==="boolean"?(entry.value?"Yes":"No"):String(entry.value)||"Empty text"}</span>;
}

export default function OperatorHistory({token,selection,onSelect,onTrace,onInspect,onClose}:{
  token:string;selection:HistorySelection;onSelect:(version:CanonicalResource)=>void;
  onTrace:(version:CanonicalResource)=>void;onInspect:(id:string)=>void;onClose:()=>void;
}) {
  const [detail,setDetail]=useState<CanonicalDetail|null>(null);
  const [error,setError]=useState("");const [revision,setRevision]=useState(0);
  const [baseline,setBaseline]=useState("");const [changesOnly,setChangesOnly]=useState(false);
  useEffect(()=>{const controller=new AbortController();
    void fetch(`/api/ontology/resources/${selection.resource_id}`,{headers:{Authorization:`Bearer ${token}`},cache:"no-store",signal:controller.signal})
      .then(async response=>{const result=await response.json();if(!response.ok)throw Error(typeof result.detail==="string"?result.detail:"History unavailable");if(!controller.signal.aborted){setDetail(result);setError("");}})
      .catch(e=>{if(!controller.signal.aborted){setDetail(null);setError(e instanceof Error?e.message:"History unavailable");}});
    return()=>controller.abort();
  },[token,selection.resource_id,revision]);
  const versions=[...(detail?.versions??[])].sort((a,b)=>b.system_from.localeCompare(a.system_from)||b.version_id.localeCompare(a.version_id));
  const selected=versions.find(v=>v.version_id===selection.version_id);
  const selectedIndex=versions.findIndex(v=>v.version_id===selection.version_id);
  const before=versions.find(v=>v.version_id===baseline)??versions[selectedIndex+1]??selected;
  const rows=before&&selected?compareVersions(before,selected):[];
  const changed=rows.filter(r=>r.changed).length;
  return <section className="g8-history" aria-label="Object history">
    <header><div><p className="overline">HISTORY & EVIDENCE</p><h2>{detail?displayName(detail.resource.display_name):"Object history"}</h2><p>Compare recorded versions. Opening history does not change accepted business state.</p></div><div className="g8-history-actions"><button onClick={()=>setRevision(r=>r+1)}>Refresh history</button><button onClick={onClose}>Close history</button></div></header>
    {error&&<p role="alert">{error}</p>}{!detail&&!error&&<p role="status">Loading authorized history…</p>}
    {detail&&!selected&&<p role="alert">The selected version is unavailable. Select an available recorded version to continue.</p>}
    {detail&&<div className="g8-history-body"><nav aria-label="Recorded versions">{versions.map((v,i)=><button key={v.version_id} aria-pressed={v.version_id===selection.version_id} onClick={()=>{setBaseline("");onSelect(v);}}><strong>{timestamp(v.system_from)}</strong><span>{v.version_id===detail.resource.version_id?"Current accepted version":"Historical version"} · {versions.length-i}</span><Badge tone={v.authority_state==="REVOKED"?"bad":"neutral"}>{readable(v.authority_state)}</Badge><small>Effective {timestamp(v.valid_from)}</small></button>)}</nav>
      {selected&&before&&<div className="g8-history-comparison"><div className="g8-history-context"><Badge>{selected.version_id===detail.resource.version_id?"Current accepted version":"Historical version"}</Badge><span>Recorded {timestamp(selected.system_from)}</span><span>Effective {timestamp(selected.valid_from)}{selected.valid_to?` until ${timestamp(selected.valid_to)}`:" · no end recorded"}</span></div>
        <div className="g8-history-toolbar"><label>Compare with<select value={before.version_id} onChange={e=>setBaseline(e.target.value)}>{versions.map((v,i)=><option key={v.version_id} value={v.version_id}>Version {versions.length-i} · {timestamp(v.system_from)}</option>)}</select></label><label className="g8-history-check"><input type="checkbox" checked={changesOnly} onChange={e=>setChangesOnly(e.target.checked)}/>Changed fields only</label><button onClick={()=>onTrace(selected)}>Trace selected version</button>{before.version_id!==selected.version_id&&<button onClick={()=>onTrace(before)}>Trace comparison version</button>}</div>
        <p role="status">{versions.length===1?"One recorded version; no earlier version is available.":`${changed} changed fields in the returned evidence.`} Missing fields can reflect access policy; they do not establish deletion.</p>
        <div className="g8-table-scroll"><table><caption>Recorded business fields · {displayName(selected.display_name)}</caption><thead><tr><th scope="col">Field</th><th scope="col">Comparison version</th><th scope="col">Selected version</th><th scope="col">Change</th></tr></thead><tbody>{rows.filter(r=>!changesOnly||r.changed).map(r=><tr key={JSON.stringify(r.path)} className={r.changed?"g8-history-changed":""}><th scope="row">{r.path.map(readable).join(" › ")}</th><td><Value entry={r.before} onInspect={onInspect}/></td><td><Value entry={r.after} onInspect={onInspect}/></td><td>{r.changed?"Changed":"Unchanged"}</td></tr>)}</tbody></table>{changesOnly&&!changed&&<p>No changed fields between these versions.</p>}</div>
        <details><summary>Exact version references</summary><dl><dt>Selected version</dt><dd>{selected.version_id}</dd><dt>Comparison version</dt><dd>{before.version_id}</dd><dt>Selected content fingerprint</dt><dd>{selected.content_hash}</dd></dl></details>
      </div>}
    </div>}
  </section>;
}
