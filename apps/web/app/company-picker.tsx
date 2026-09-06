"use client";

import {useEffect, useRef, useState} from "react";
import type {CanonicalResource} from "@finai/contracts";
import type {CompanyIndex} from "./company-workspace";
import {displayName} from "./display-name";

export default function CompanyPicker({index, selected, selectedId, error, onSelect}: {
  index:CompanyIndex|null; selected?:CanonicalResource; selectedId:string; error:string|null;
  onSelect:(company:CanonicalResource|null)=>void;
}) {
  const [open,setOpen]=useState(false);
  const [query,setQuery]=useState("");
  const container=useRef<HTMLDivElement>(null);
  const input=useRef<HTMLInputElement>(null);
  useEffect(()=>{
    if(!open)return;
    input.current?.focus();
    const outside=(event:PointerEvent)=>{if(!container.current?.contains(event.target as Node))setOpen(false);};
    const escape=(event:KeyboardEvent)=>{if(event.key==="Escape"){setOpen(false);container.current?.querySelector<HTMLButtonElement>("button")?.focus();}};
    document.addEventListener("pointerdown",outside);document.addEventListener("keydown",escape);
    return()=>{document.removeEventListener("pointerdown",outside);document.removeEventListener("keydown",escape);};
  },[open]);
  const configured=index?.workspaces.map(w=>w.company)??[];
  const sources=index?.source_companies.filter(c=>!configured.some(w=>w.resource_id===c.resource_id))??[];
  const seen=new Set([...configured,...sources].map(c=>c.resource_id));
  const reported=[...new Map((index?.reported_groups??[]).flatMap(g=>[g.reporter,...g.members.map(m=>m.company)]).filter(c=>!seen.has(c.resource_id)).map(c=>[c.resource_id,c])).values()];
  const groups=[{title:"Configured workspaces",hint:"Company workspace and domain configuration",rows:configured},{title:"Source accounting contexts",hint:"Retained source ownership; workspace configuration may be incomplete",rows:sources},{title:"Companies in dated filings",hint:"Evidence context only; no current ownership or operating scope implied",rows:reported}];
  const matches=(c:CanonicalResource)=>`${c.display_name} ${String(c.attributes.registration_code??"")}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
  function choose(company:CanonicalResource|null){onSelect(company);setOpen(false);setQuery("");container.current?.querySelector<HTMLButtonElement>("button")?.focus();}
  return <div className="g8-company-picker" ref={container}>
    <button className="g8-context-chip" aria-label="Choose company context" aria-expanded={open} aria-controls="company-context-picker" onClick={()=>setOpen(!open)}><span>{selected?displayName(selected.display_name):selectedId?"Company context unavailable":"All authorized contexts"}</span><span aria-hidden>⌄</span></button>
    {open&&<section id="company-context-picker" className="g8-context-popover" aria-label="Choose company context">
      <label>Find company<input ref={input} value={query} onChange={e=>setQuery(e.target.value)} placeholder="Name, source alias or registration ID"/></label>
      <button className="g8-company-option" aria-pressed={!selectedId} onClick={()=>choose(null)}>All authorized contexts<small>Clear the company filter</small></button>
      {error&&<p role="alert">{error}</p>}{!index&&!error&&<p role="status">Loading company contexts…</p>}
      {groups.map(group=>{const rows=group.rows.filter(matches);return rows.length>0&&<section key={group.title}><h3>{group.title}</h3><p>{group.hint}</p>{rows.map(c=><button className="g8-company-option" key={c.resource_id} aria-pressed={selectedId===c.resource_id} onClick={()=>choose(c)}>{displayName(c.display_name)}<small>{String(c.attributes.registration_code??"Registration ID not recorded")}</small></button>)}</section>;})}
      {index&&!groups.some(g=>g.rows.some(matches))&&<p>No matching company contexts.</p>}
    </section>}
  </div>;
}
