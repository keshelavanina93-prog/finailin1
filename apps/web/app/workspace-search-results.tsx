"use client";

import {useEffect,useRef,useState,type KeyboardEvent} from "react";
import type {CanonicalResource,HistorySearchResult} from "@finai/contracts";
import {displayName} from "./display-name";
import "./workspace-search-results.css";

type Search={key:string;cutoff:string;offset:number;revision:number};
type Loaded={key:string;result:HistorySearchResult|null;error:string};
const label=(value:string)=>value.replace(/([a-z])([A-Z])/g,"$1 $2").replaceAll("_"," ").toLowerCase();

export default function WorkspaceSearchResults({token,companyId,companyName,query,onInspect,onClose}:{
 token:string;companyId:string;companyName:string;query:string;
 onInspect:(resource:CanonicalResource,knownAt:string)=>void;onClose:()=>void;
}) {
 const text=query.trim();
 const valid=Boolean(companyId&&text&&text.length<=200);
 const scopeKey=JSON.stringify([token,companyId,text]);
 const [search,setSearch]=useState<Search|null>(null);
 const [loaded,setLoaded]=useState<Loaded|null>(null);
 const panel=useRef<HTMLElement>(null);
 const focusRequest=useRef("");
 const request=search?.key===scopeKey&&valid?search:null;
 const requestKey=request?JSON.stringify(request):"";
 const current=requestKey&&loaded?.key===requestKey?loaded:null;
 const result=current?.result;
 const busy=valid&&!current;
 useEffect(()=>{
  if(!valid)return;
  const timer=setTimeout(()=>setSearch({key:scopeKey,cutoff:new Date().toISOString(),offset:0,revision:0}),300);
  return()=>clearTimeout(timer);
 },[scopeKey,valid]);
 useEffect(()=>{
  if(!request)return;
  const controller=new AbortController();let disposed=false;
  const timer=setTimeout(()=>controller.abort(),20000);
  const params=new URLSearchParams({company_id:companyId,q:text,limit:"12",offset:String(request.offset),effective_at:request.cutoff,known_at:request.cutoff});
  void fetch(`/api/ontology/history-search?${params}`,{headers:{Authorization:`Bearer ${token}`},signal:controller.signal,cache:"no-store"})
   .then(async response=>{
    const data=await response.json();
    if(!response.ok)throw new Error(typeof data.detail==="string"?data.detail:"Company resource search unavailable");
    if(!Array.isArray(data.resources)||data.resources.length>12||!Number.isInteger(data.matched_count)||data.matched_count<0||data.offset!==request.offset||data.limit!==12||Date.parse(data.effective_at)!==Date.parse(request.cutoff)||Date.parse(data.known_at)!==Date.parse(request.cutoff))throw new Error("Search response did not retain the requested page and time context. Retry the search.");
    if(!disposed&&!controller.signal.aborted)setLoaded({key:requestKey,result:data,error:""});
   })
   .catch(error=>{if(!disposed)setLoaded({key:requestKey,result:null,error:controller.signal.aborted?"Company search timed out. Retry or narrow the query.":error instanceof Error?error.message:"Company resource search unavailable"});})
   .finally(()=>clearTimeout(timer));
  return()=>{disposed=true;clearTimeout(timer);controller.abort();};
 },[request,requestKey,token,companyId,text]);
 useEffect(()=>{
  if(current&&current.key===focusRequest.current){
   focusRequest.current="";
   (panel.current?.querySelector<HTMLButtonElement>("button[data-resource-result]")??panel.current)?.focus();
  }
 },[current]);
 function page(offset:number){if(request){const next={...request,offset};focusRequest.current=JSON.stringify(next);setSearch(next);}}
 function keyboard(event:KeyboardEvent<HTMLElement>){
  if(event.key==="Escape"){event.preventDefault();onClose();return;}
  if(event.key!=="ArrowDown"&&event.key!=="ArrowUp")return;
  const buttons=Array.from(panel.current?.querySelectorAll<HTMLButtonElement>("button[data-resource-result]")??[]);
  if(!buttons.length)return;
  const index=buttons.indexOf(document.activeElement as HTMLButtonElement);
  const next=event.key==="ArrowDown"?(index+1)%buttons.length:(index<=0?buttons.length-1:index-1);
  event.preventDefault();buttons[next].focus();
 }
 return <section ref={panel} tabIndex={-1} className="wssearch-results" aria-label="Company resource search" onKeyDown={keyboard}>
  <header><div><strong>Company resources</strong><span>{companyName||"Choose a company"}</span></div><button type="button" className="wssearch-close" onClick={onClose} aria-label="Close company search">Close</button></header>
  {!companyId?<p className="wssearch-message">Select a company to search its recorded resources. No broader scope is substituted.</p>:!text?<p className="wssearch-message">Enter a resource name or identifier.</p>:text.length>200?<p className="wssearch-message" role="alert">Search supports up to 200 characters. Shorten the query to continue.</p>:<>
   {busy&&<p className="wssearch-message" role="status">Searching company resources…</p>}
   {current?.error&&<div className="wssearch-error" role="alert"><p>{current.error}</p><button type="button" onClick={()=>{if(request)setSearch({...request,revision:request.revision+1});}}>Retry search</button></div>}
   {result&&<><p className="wssearch-count" role="status">{result.matched_count} matching resource{result.matched_count===1?"":"s"} in this company at the search cutoff</p>
    {result.resources.length?<ul className="wssearch-list">{result.resources.map(resource=><li key={resource.version_id}><button type="button" data-resource-result onClick={()=>{onInspect(resource,result.known_at);onClose();}}><span className="wssearch-name">{displayName(resource.display_name)}</span><span className="wssearch-meta"><span>{label(resource.object_type)}</span><span>{label(resource.authority_state)} · {label(resource.evidence_class)}</span></span></button></li>)}</ul>:<p className="wssearch-message">No recorded company resources match this query at the selected cutoff.</p>}
    <footer><span>{result.resources.length?`${result.offset+1}–${result.offset+result.resources.length} of ${result.matched_count}`:"0 results"}</span><button type="button" disabled={result.offset===0} onClick={()=>page(Math.max(0,result.offset-result.limit))}>Previous</button><button type="button" disabled={!result.has_more} onClick={()=>page(result.offset+result.limit)}>Next</button></footer>
    <details className="wssearch-time"><summary>Search time context</summary><p>Effective and known at <time dateTime={result.known_at}>{new Date(result.known_at).toLocaleString()}</time>. Pages preserve this cutoff. Opening a result retains its exact version.</p></details>
   </>}
  </>}
 </section>;
}
