"use client";

import {useEffect,useState} from "react";
import type {CanonicalResource} from "@finai/contracts";
import "./retained-build-artifacts.css";

const record=(value:unknown):Record<string,unknown>=>value!==null&&typeof value==="object"&&!Array.isArray(value)?value as Record<string,unknown>:{};
const text=(value:unknown)=>typeof value==="string"?value:"Not recorded";
const human=(value:string)=>value.toLowerCase().replaceAll("_"," ");

export default function RetainedBuildArtifacts({token}:{token:string}) {
 const [open,setOpen]=useState(false);
 return <details className="retained-build-artifacts" onToggle={event=>setOpen(event.currentTarget.open)}><summary>Retained build artifacts</summary>{open&&<ArtifactRecords key={token} token={token}/>}</details>;
}

function ArtifactRecords({token}:{token:string}) {
 const [page,setPage]=useState(()=>({offset:0,cutoff:new Date().toISOString(),revision:0}));
 const [items,setItems]=useState<CanonicalResource[]>([]),[selected,setSelected]=useState("");
 const [loading,setLoading]=useState(true),[error,setError]=useState("");
 useEffect(()=>{let disposed=false;const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),20000);
  async function load(){setLoading(true);setError("");setItems([]);setSelected("");
   try {const query=new URLSearchParams({object_type:"Artifact",offset:String(page.offset),valid_at:page.cutoff,known_at:page.cutoff});
    const response=await fetch(`/api/ontology/resources?${query}`,{headers:{Authorization:`Bearer ${token}`},signal:controller.signal,cache:"no-store"});const data=await response.json();
    if(!response.ok)throw new Error(typeof data.detail==="string"?data.detail:`Retained artifacts unavailable (${response.status}).`);
    if(!Array.isArray(data)||data.length>100||data.some(item=>item.object_type!=="Artifact"||typeof item.resource_id!=="string"||typeof item.version_id!=="string"))throw new Error("Artifact response does not match the requested collection.");
    if(!disposed)setItems(data);
   }catch(failure){if(!disposed)setError(controller.signal.aborted?"Artifact lookup timed out. Retry this page.":failure instanceof Error?failure.message:"Artifact lookup unavailable.");}
   finally{clearTimeout(timer);if(!disposed)setLoading(false);}}
  void load();return()=>{disposed=true;clearTimeout(timer);controller.abort();};
 },[token,page]);
 const active=items.find(item=>item.version_id===selected);
 const definition=record(active?.attributes.definition);
 function move(offset:number){setItems([]);setSelected("");setLoading(true);setPage(previous=>({...previous,offset}));}
 return <section aria-label="Retained build artifact inventory"><p>These canonical records identify retained build bytes in your authorized scope. Retention is not an accepted release, build attestation or deployment grant.</p><div className="artifact-toolbar"><button type="button" disabled={loading} onClick={()=>{setItems([]);setSelected("");setLoading(true);setPage(previous=>({offset:0,cutoff:new Date().toISOString(),revision:previous.revision+1}));}}>Refresh artifacts</button><small>Snapshot {new Date(page.cutoff).toLocaleString()}</small></div>
 {loading&&<p role="status">Loading retained artifacts…</p>}{error&&<p role="alert">{error} <button type="button" onClick={()=>setPage(previous=>({...previous,revision:previous.revision+1}))}>Retry page</button></p>}
 {!loading&&!error&&!items.length&&<p>No retained artifacts were returned on this page.</p>}
 {items.length>0&&<div className="artifact-table"><table><thead><tr><th>Artifact</th><th>Kind</th><th>Retained size</th><th>Authority</th></tr></thead><tbody>{items.map(item=>{const spec=record(item.attributes.definition);return <tr key={item.version_id}><th scope="row"><button type="button" aria-pressed={selected===item.version_id} onClick={()=>setSelected(item.version_id)}>{item.display_name}</button></th><td>{human(text(spec.artifact_kind))}</td><td>{typeof item.attributes.byte_length==="number"?`${item.attributes.byte_length.toLocaleString()} bytes`:"Not recorded"}</td><td>{spec.contract==="retained-build-artifact/1"&&spec.authority==="RETAINED_BYTES_ONLY"?"Retained bytes only":"No supported retention claim"}</td></tr>;})}</tbody></table></div>}
 <div className="artifact-toolbar"><small>{items.length} records on this page; collection uses pages of up to 100.</small>{page.offset>0&&<button type="button" disabled={loading} onClick={()=>move(Math.max(0,page.offset-100))}>Previous page</button>}{items.length===100&&page.offset<100000&&<button type="button" disabled={loading} onClick={()=>move(page.offset+100)}>Next page</button>}</div>
 {active&&<section className="artifact-detail" aria-label="Selected retained artifact"><h4>{active.display_name}</h4><p>Definition review: {human(active.authority_state)} · Recorded {new Date(active.system_from).toLocaleString()}</p><p>{definition.authority==="RETAINED_BYTES_ONLY"?"This record establishes retained byte identity only.":"No supported retained-byte authority is declared."}</p><details><summary>Exact artifact &amp; source references</summary><dl>{Object.entries({"Artifact resource":active.resource_id,"Version":active.version_id,"Canonical content hash":active.content_hash,"Retained byte SHA-256":text(active.attributes.sha256),"Retained document":text(active.attributes.document_id),"Source evidence":text(active.attributes.evidence_id),"Evidence class":active.evidence_class,"Contract":text(definition.contract),"Valid from":active.valid_from,"Known at":page.cutoff}).map(([name,value])=><div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}</dl></details></section>}
 </section>;
}
