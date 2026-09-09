"use client";

import {useEffect,useId,useRef,useState,type KeyboardEvent,type ReactNode} from "react";
import {Archive,ClockCounterClockwise,Files,Plus,Function as FunctionIcon,FlowArrow,Database} from "@phosphor-icons/react";
import {
 SOURCE_FAMILY_INTAKE_PLANS,
 classifySourceFamily,
 missingDimensionsForAnalyst,
 sourceFamilyIntakeSummary,
 type SourceFamilyClassification,
} from "./source-family-intake-model";
import "./data-workspace.css";

type Section = "families"|"history"|"sources"|"documents"|"analyses"|"builds";
const sections = [
 {id:"families",label:"Source families",icon:Database,description:"See which enterprise source families are accepted, partially wired or still blocked."},
 {id:"builds",label:"Builds",icon:FlowArrow,description:"Follow durable evidence builds through node completion and retained named outputs."},
 {id:"analyses",label:"Saved analyses",icon:FunctionIcon,description:"Run a reviewed evidence analysis with exact definitions, source versions and time cutoffs."},
 {id:"history",label:"Resources & history",icon:ClockCounterClockwise,description:"Find recorded company resources, then inspect their exact version, dependencies and evidence."},
 {id:"sources",label:"Retained sources",icon:Archive,description:"Inspect retained source records and their interpretation, with the original evidence in reach."},
 {id:"documents",label:"Evidence documents",icon:Files,description:"Review company-linked documents and their retained source evidence."},
] as const;

function restoredSection(key:string):Section {
 try {
  const saved=sessionStorage.getItem(key);
  if(saved==="families"||saved==="history"||saved==="sources"||saved==="documents"||saved==="analyses"||saved==="builds")return saved;
 } catch {/* Navigation works when session storage is unavailable. */}
 return "families";
}

function sourceFamilyClassName(state: SourceFamilyClassification) {
 return state === "anchored" ? "wired" : state === "partial" ? "partial" : "target";
}

function sourceFamilyLabel(state: SourceFamilyClassification) {
 return state === "anchored" ? "Anchored" : state === "partial" ? "Partial" : "Target";
}

function SourceFamilyMatrix({companyName}:{companyName:string}) {
 const summary=sourceFamilyIntakeSummary();
 return <section className="source-family-matrix" aria-label="Source family intake matrix">
  <header><div><p className="dataws-eyebrow">MASSIVE MULTI-ENTITY INTAKE</p><h3>Source family matrix</h3><p>Read-only convergence map for 1C, ORPAK/POS, gas networks, cash registers and multi-company evidence.</p></div><span>{companyName||"All authorized contexts"} · {summary.families} families · {summary.anchored} anchored · {summary.partial} partial · {summary.targetOnly} target</span></header>
  <div className="source-family-grid">{SOURCE_FAMILY_INTAKE_PLANS.map(item=>{
   const state=classifySourceFamily(item);
   const missing=missingDimensionsForAnalyst(item.id);
   const destination=item.routes.backendRoutes.length?item.routes.backendRoutes.join(" -> "):"No backend route declared";
   const routes=item.routes.proxyRoutes.length?item.routes.proxyRoutes.join(" -> "):"No frontend proxy route proved yet";
   return <article key={item.id} className={`source-family-card ${sourceFamilyClassName(state)}`}>
    <div><strong>{item.label}</strong><span>{item.systems.join(", ")}</span></div>
    <mark>{sourceFamilyLabel(state)}</mark>
    <dl><dt>Scope</dt><dd>{item.requiredScopeDimensions.join(", ")}</dd><dt>Evidence</dt><dd>{item.requiredEvidence.join(", ")}</dd><dt>Routes</dt><dd>{routes}</dd><dt>Missing</dt><dd>{missing.length?missing.join(", "):"No missing frontend intake dimensions declared"}</dd><dt>Destination</dt><dd>{destination}</dd></dl>
   </article>;
  })}</div>
  <p className="source-family-note">Target means the product architecture requires this dimension, but this checkout does not yet prove a complete frontend/backend/browser-wired journey for it.</p>
 </section>;
}

/** Parent keys this workbench by identity and company context. Only a section name is persisted. */
export default function DataWorkspace({companyName,viewStateKey,history,sources,documents,savedAnalyses,builds,onIntake,observedSourceCount,initialSourceId,sourceSelectionKey=0,initialBuildId}: {
 companyName:string;viewStateKey:string;history:ReactNode;sources:ReactNode;documents:ReactNode;savedAnalyses:ReactNode;builds:ReactNode;
 onIntake:()=>void;observedSourceCount?:number;initialSourceId?:string;sourceSelectionKey?:number;initialBuildId?:string;
}) {
 const incomingSelection=initialSourceId?`${initialSourceId}:${sourceSelectionKey}`:undefined;
 const [navigation,setNavigation]=useState(()=>{
  const section:Section=initialBuildId?"builds":initialSourceId?"sources":restoredSection(viewStateKey);
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
 const panels={families:<SourceFamilyMatrix companyName={companyName}/>,history,sources,documents,analyses:savedAnalyses,builds};
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
