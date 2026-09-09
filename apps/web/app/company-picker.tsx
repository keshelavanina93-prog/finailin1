"use client";

import {useEffect, useId, useRef, useState} from "react";
import type {CanonicalResource} from "@finai/contracts";
import type {CompanyIndex} from "./company-workspace";
import {companyDirectory,selectableCompanies} from "./company-directory";
import {displayName} from "./display-name";

export default function CompanyPicker({index, selectedId, error, onSelect}: {
  index:CompanyIndex|null; selected?:CanonicalResource; selectedId:string; error:string|null;
  onSelect:(company:CanonicalResource|null)=>void;
}) {
  const pickerId=useId();
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
  const directory=companyDirectory(index),companies=selectableCompanies(index);
  const current=companies.find(company=>company.resource_id===selectedId);
  const groups=directory?[{title:"Companies",hint:"Declared companies and configured company workspaces",rows:companies}]:[];
  const matches=(c:CanonicalResource)=>`${c.display_name} ${String(c.attributes.registration_code??"")}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
  function choose(company:CanonicalResource|null){if(company&&!companies.some(item=>item.resource_id===company.resource_id&&item.version_id===company.version_id&&item.content_hash===company.content_hash))return;onSelect(company);setOpen(false);setQuery("");container.current?.querySelector<HTMLButtonElement>("button")?.focus();}
  return <div className="g8-company-picker" ref={container}>
    <button className="g8-context-chip" aria-label="Choose company context" aria-expanded={open} aria-controls={pickerId} onClick={()=>setOpen(!open)}><span>{current?displayName(current.display_name):selectedId?"Identity requires review":"All authorized contexts"}</span><span aria-hidden>⌄</span></button>
    {open&&<section id={pickerId} className="g8-context-popover" aria-label="Choose company context">
      <label>Find company<input ref={input} value={query} onChange={e=>setQuery(e.target.value)} placeholder="Company name or registration code"/></label>
      <button className="g8-company-option" aria-pressed={!selectedId} onClick={()=>choose(null)}>All authorized contexts<small>Clear the company filter</small></button>
      {error&&<p role="alert">{error}</p>}{!index&&!error&&<p role="status">Loading company contexts…</p>}
      {index&&!directory&&<p role="alert">Company directory unavailable. No legacy identity list is used for selection.</p>}
      {groups.map(group=>{const rows=group.rows.filter(matches);return rows.length>0&&<section key={group.title}><h3>{group.title}</h3><p>{group.hint}</p>{rows.map(c=><button className="g8-company-option" key={c.resource_id} aria-pressed={selectedId===c.resource_id} onClick={()=>choose(c)}>{displayName(c.display_name)}<small>{String(c.attributes.registration_code??"Registration ID not recorded")}</small></button>)}</section>;})}
      {directory&&!groups.some(g=>g.rows.some(matches))&&<p>No matching declared or configured companies.</p>}
    </section>}
  </div>;
}
