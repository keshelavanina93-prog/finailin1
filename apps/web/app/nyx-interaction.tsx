"use client";
import {useState,type FormEvent} from "react";
import {ArrowUp,ArrowRight} from "@phosphor-icons/react";
import type {MapSelection} from "./operations-model";
import type {WorkItem} from "./g8-model";
import type {OperatorInspection} from "@finai/contracts";
import {displayName} from "./display-name";
import {useResourceLifecycle} from "./use-resource-lifecycle";

const readable=(value:string)=>value.replace(/([a-z])([A-Z])/g,"$1 $2").replaceAll("_"," ").toLowerCase();
const date=(value:string)=>new Date(value).toLocaleString(undefined,{year:"numeric",month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"});

type ResourceReference={resource_id:string;version_id:string;known_at:string;display_name:string};
type ResourceNavigation=(resourceId:string,versionId:string,knownAt:string)=>void;
type Reply={question:string;answer:string;references:WorkItem[];context:string;resourceReference?:ResourceReference};
export default function NyxInteraction({token,items,work,context,blockers,availability,onInspect,onData,onWork,mapSelection,inspection,onResourceTrace,onResourceHistory}:{token?:string;mapSelection?:MapSelection|null;inspection?:OperatorInspection|null;onResourceTrace?:ResourceNavigation;onResourceHistory?:ResourceNavigation;items:WorkItem[];work:WorkItem|null;context:string;blockers:string[];availability:string;onInspect:(item:WorkItem)=>void;onData:()=>void;onWork:()=>void}) {
 const [question,setQuestion]=useState("");const [history,setHistory]=useState<Reply[]>([]);
 const target=mapSelection?{resource_id:mapSelection.resource.resource_id,version_id:mapSelection.resource.version_id,known_at:mapSelection.knownAt}:inspection?{resource_id:inspection.resource.resource_id,version_id:inspection.resource.version_id,known_at:inspection.known_at}:null;
 const lifecycle=useResourceLifecycle(token,target);
 function materialContext(){
  if(lifecycle.status!=="ready")return `Material state ${lifecycle.status==="loading"?"was still being checked":"was unavailable"} when this answer was requested. Definition approval does not establish material authority or availability.`;
  const state=lifecycle.history?.state;
  return state?`Retained material authority: ${readable(state.target_state)}; how it is known: ${readable(state.epistemic_state)}; availability and quality: ${readable(state.availability_state)}; business lifecycle: ${readable(state.business_state)}. Historical state does not authorize current use.`:"No reviewed material state was recorded for this version by the selected knowledge cutoff. Its current material authority and availability are not established by this historical view.";
 }
 function ask(value:string){const q=value.trim();if(!q)return;const pending=items.filter(i=>i.state==="PENDING");let answer="";let references:WorkItem[]=[];let resourceReference:ResourceReference|undefined;let usesQueueContext=true;
 if(/forecast|profit|margin|revenue|cash flow|budget/i.test(q)){answer="Financial analysis is not connected to authoritative metrics in this workspace yet. I can help inspect retained evidence and review blockers, but cannot explain or invent financial performance.";}
 else if(/attention|pending|review items/i.test(q)){references=pending.slice(0,8);answer=`${pending.length} pending items in the loaded authorized queues. Open an item to inspect its evidence and review eligibility.`;}
 else if(mapSelection&&/map|asset|selected|connect|impact|explain/i.test(q)){
  usesQueueContext=false;const r=mapSelection.resource;
  resourceReference={resource_id:r.resource_id,version_id:r.version_id,known_at:mapSelection.knownAt,display_name:displayName(r.display_name)};
  answer=`${resourceReference.display_name} is a recorded ${readable(r.object_type)}. Definition review: ${readable(r.authority_state)}; evidence class: ${readable(r.evidence_class)}. Effective snapshot: ${date(mapSelection.validAt)}; known by G8 at ${date(mapSelection.knownAt)}. ${materialContext()} Open Operations & Maps to inspect explicit connections. Location alone does not establish flow, service disruption or financial impact; telemetry and hydraulic predictions are not connected.`;
 }
 else if(inspection&&/why|block|explain|selected|impact|produced|trace|history|evidence|version/i.test(q)){
  usesQueueContext=false;const r=inspection.resource;
  resourceReference={resource_id:r.resource_id,version_id:r.version_id,known_at:inspection.known_at,display_name:displayName(r.display_name)};
  answer=`${resourceReference.display_name} is a recorded ${readable(r.object_type)}. Definition review: ${readable(r.authority_state)}; evidence class: ${readable(r.evidence_class)}. Known by G8 at ${date(inspection.known_at)}. Effective from ${date(r.valid_from)}${r.valid_to?` until ${date(r.valid_to)} (exclusive)`:"; no end is recorded"}. ${materialContext()} The visible history contains ${inspection.versions.length} version${inspection.versions.length===1?"":"s"}${inspection.versions_truncated?" (bounded)":""} and ${inspection.dependents.length} dependent link${inspection.dependents.length===1?"":"s"}${inspection.dependents_truncated?" (bounded)":""}. Trace shows the recorded evidence chain. These links identify where to investigate; they do not establish a cause, complete business impact or permission for current financial use.`;
 }
 else if(/why|block|explain|selected|impact|produced/i.test(q)){references=work?[work]:[];answer=work?`${work.title}: ${work.reason} ${blockers.length?blockers.join(" "):"Open context for the retained impact and current eligibility. No approval is performed here."}`:"Select a company resource, map object or work item to inspect its recorded context and evidence.";}
 else {const terms=q.toLowerCase().replace(/^(find|search|show)\s+/,"");references=items.filter(i=>`${i.title} ${i.reason}`.toLowerCase().includes(terms)).slice(0,8);answer=references.length?"Matching work and retained sources in your current authorized snapshot:":"No matching item in the loaded context. Try a source filename, ‘pending reviews’ or ‘explain selected’. Financial reasoning and general AI conversation are not connected yet.";}
 setHistory(old=>[...old,{question:q,answer:availability&&usesQueueContext?`${availability} ${answer}`:answer,references,context,resourceReference}].slice(-20));setQuestion("");
 }
 function submit(event:FormEvent){event.preventDefault();ask(question);}
 return <section className="nyx-interaction" aria-label="NYX interactive investigation"><div className="nyx-quick-actions"><button onClick={()=>ask("What needs attention?")}>What needs attention?</button><button onClick={()=>ask("Explain selected")}>Explain selected</button><button onClick={onData}>Explore source data<ArrowRight size={13}/></button><button onClick={onWork}>Open My Work<ArrowRight size={13}/></button></div><p className="g8-subtle">Evidence commands · answers use recorded workspace state, not AI inference.</p><div className="nyx-conversation" role="log" aria-live="polite">{history.map((reply,index)=><article key={index}><p className="nyx-question">{reply.question}</p><small>{reply.context} · snapshot at request</small><p>{reply.answer}</p>{reply.references.map(item=><button className="g8-panel-action" key={item.id} onClick={()=>onInspect(item)}>{item.title}<ArrowRight size={14}/></button>)}{reply.resourceReference&&<div aria-label="Recorded resource investigation">{onResourceTrace&&<button className="g8-panel-action" onClick={()=>{const ref=reply.resourceReference;if(ref)onResourceTrace(ref.resource_id,ref.version_id,ref.known_at);}}>Trace {reply.resourceReference.display_name}<ArrowRight size={14}/></button>}{onResourceHistory&&<button className="g8-panel-action" onClick={()=>{const ref=reply.resourceReference;if(ref)onResourceHistory(ref.resource_id,ref.version_id,ref.known_at);}}>History of {reply.resourceReference.display_name}<ArrowRight size={14}/></button>}<details><summary>Exact retained reference</summary><dl><dt>Resource</dt><dd><small>{reply.resourceReference.resource_id}</small></dd><dt>Version</dt><dd><small>{reply.resourceReference.version_id}</small></dd><dt>Known-at cutoff</dt><dd><small>{reply.resourceReference.known_at}</small></dd></dl></details></div>}</article>)}</div><form onSubmit={submit} className="nyx-composer"><label className="sr-only" htmlFor="nyx-question">Ask NYX about current evidence</label><input id="nyx-question" value={question} onChange={e=>setQuestion(e.target.value)} maxLength={500} placeholder="Find evidence or explain selected…"/><button aria-label="Send to NYX" disabled={!question.trim()}><ArrowUp size={18}/></button></form>{history.length>0&&<button className="g8-link" onClick={()=>setHistory([])}>Clear conversation</button>}</section>;
}
