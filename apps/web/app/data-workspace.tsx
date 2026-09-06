"use client";

import {useEffect,useId,useRef,useState,type KeyboardEvent,type ReactNode} from "react";
import {Archive,ClockCounterClockwise,Files,Plus} from "@phosphor-icons/react";
import "./data-workspace.css";

type Section = "history"|"sources"|"documents";
const sections = [
 {id:"history",label:"Resources & history",icon:ClockCounterClockwise,description:"Find recorded company resources, then inspect their exact version, dependencies and evidence."},
 {id:"sources",label:"Retained sources",icon:Archive,description:"Inspect retained source records and their interpretation, with the original evidence in reach."},
 {id:"documents",label:"Evidence documents",icon:Files,description:"Review company-linked documents and their retained source evidence."},
] as const;

function restoredSection(key:string):Section {
 try {
  const saved=sessionStorage.getItem(key);
  if(saved==="history"||saved==="sources"||saved==="documents")return saved;
 } catch {/* Navigation works when session storage is unavailable. */}
 return "history";
}

/** Parent keys this workbench by identity and company context. Only a section name is persisted. */
export default function DataWorkspace({companyName,viewStateKey,history,sources,documents,onIntake,observedSourceCount,initialSourceId,sourceSelectionKey=0}: {
 companyName:string;viewStateKey:string;history:ReactNode;sources:ReactNode;documents:ReactNode;
 onIntake:()=>void;observedSourceCount?:number;initialSourceId?:string;sourceSelectionKey?:number;
}) {
 const incomingSelection=initialSourceId?`${initialSourceId}:${sourceSelectionKey}`:undefined;
 const [navigation,setNavigation]=useState(()=>{
  const section:Section=initialSourceId?"sources":restoredSection(viewStateKey);
  return {section,visited:new Set<Section>([section]),sourceSelection:incomingSelection};
 });
 // A new source selection can arrive through NYX while this workspace is mounted.
 // Clearing that selection during resource inspection must not reset the active tab.
 if(navigation.sourceSelection!==incomingSelection) {
  setNavigation({...navigation,sourceSelection:incomingSelection,...(initialSourceId?{section:"sources",visited:new Set<Section>([...navigation.visited,"sources"])}:{})});
 }
 const {section,visited}=navigation;
 const tabs=useRef<(HTMLButtonElement|null)[]>([]);
 const id=useId();
 useEffect(()=>{try{sessionStorage.setItem(viewStateKey,section);}catch{/* No private resource or authority state is stored here. */}},[section,viewStateKey]);
 function select(next:Section) {
  setNavigation(previous=>({...previous,section:next,visited:previous.visited.has(next)?previous.visited:new Set([...previous.visited,next])}));
 }
 function keyboard(event:KeyboardEvent<HTMLButtonElement>,index:number) {
  let target:number;
  if(event.key==="ArrowRight")target=(index+1)%sections.length;
  else if(event.key==="ArrowLeft")target=(index+sections.length-1)%sections.length;
  else if(event.key==="Home")target=0;
  else if(event.key==="End")target=sections.length-1;
  else return;
  event.preventDefault();select(sections[target].id);tabs.current[target]?.focus();
 }
 const active=sections.find(item=>item.id===section)!;
 const panels={history,sources,documents};
 const count=typeof observedSourceCount==="number"&&Number.isSafeInteger(observedSourceCount)&&observedSourceCount>=0?observedSourceCount:null;
 return <section className="dataws" aria-label="Data workspace">
  <header className="dataws-header"><div><p className="dataws-eyebrow">DATA WORKSPACE</p><h2>Resources, history & evidence</h2><p>Follow a business resource to the evidence behind it.</p></div><button className="dataws-intake" onClick={onIntake}><Plus size={14} aria-hidden="true"/>Retain a source</button></header>
  <div className="dataws-context"><span><span className="dataws-context-label">Company</span><strong>{companyName||"No company selected"}</strong></span>{count!==null&&<span className="dataws-observed">{count} retained source{count===1?"":"s"} in loaded scope<span className="dataws-count-note">Bounded inventory · not a completeness measure</span></span>}</div>
  <div className="dataws-tabs" role="tablist" aria-label="Data sections">{sections.map((item,index)=>{const Icon=item.icon;return <button key={item.id} ref={node=>{tabs.current[index]=node;}} role="tab" id={`${id}-tab-${item.id}`} aria-controls={`${id}-panel-${item.id}`} aria-selected={section===item.id} tabIndex={section===item.id?0:-1} onClick={()=>select(item.id)} onKeyDown={event=>keyboard(event,index)}><Icon size={15} aria-hidden="true"/>{item.label}</button>;})}</div>
  <div className="dataws-guidance"><span>{active.description}</span><span>Exact-version inspection · source trace</span></div>
  {sections.map(item=><div key={item.id} id={`${id}-panel-${item.id}`} role="tabpanel" aria-labelledby={`${id}-tab-${item.id}`} hidden={section!==item.id} tabIndex={0} className="dataws-panel">{visited.has(item.id)?panels[item.id]:null}</div>)}
  <footer className="dataws-foot"><span>Resource history keeps effective time and knowledge time separate.</span><span>Each section reports its own availability and authority.</span></footer>
 </section>;
}
