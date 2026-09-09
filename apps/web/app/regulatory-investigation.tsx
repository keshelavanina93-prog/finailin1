"use client";

import {useEffect,useState} from "react";
import {ArrowRight,ClockCounterClockwise,FileText,ShieldCheck} from "@phosphor-icons/react";
import {displayName} from "./display-name";
import type {CompanyRegulationPage,OperatorInspection} from "@finai/contracts";
import {assertRegulationHandoffPage,regulationRuleQuery,regulationSnapshotKey,type CompanyRegulationHandoff} from "./company-regulation-handoff";
import {restorationInstant} from "./definition-restoration-time";
import type {Result} from "./regulation-workspace";
import "./regulatory-investigation.css";

export type RegulatoryReference={resource_id:string;version_id:string};
export type RegulatoryNavigation={onInspect?:(resource:RegulatoryReference,knownAt?:string)=>void;onTrace?:(resource:RegulatoryReference,knownAt?:string)=>void;onHistory?:(resource:RegulatoryReference,knownAt?:string)=>void;onWorkflow?:(workflowId:string)=>void};
type Resource=RegulatoryReference&{display_name:string;object_type:string;system_from:string;attributes:Record<string,unknown>};
type Observation={title:string;matsne_id:string;publication:number|null;completeness:string;advertised_publications:number[];text:string;attachments_retained:boolean;current_law_verified:boolean};
type Publication=Resource&{attributes:{document_id:string;act_id:string;observation:Observation}};
type Definition={legal_status:string;source_version_complete:boolean;provision:string;source_version:string;effective_from:string;effective_to:string|null;deadline:string|null;activity:string;obligation:string};
type Rule=Resource&{attributes:{legal_entity_id:string;act_id:string;definition:Definition};overview_assessment?:Result["rules"][number]["assessment"];overview_context?:{at:string;known_at:string}};
type Monitor={workflow_id:string;created_at:string;request:{name:string;document_number:string;publication:number;cadence_hours:number}};
type Check={event_id:string;state:string;created_at:string;checked_at?:string;document?:{document_id:string};reason?:string};
type MonitorDetail=Monitor&{source_health:string;freshness:string;last_success:Check|null;last_new_item:Check|null;events:Check[];runtime:{state:string;next_checks:string[]}};
type Impact={run_id:string;observed_at:string;act:RegulatoryReference&{display_name:string};dependency_impact:{affected:(RegulatoryReference&{object_type:string;display_name:string;depth:number})[]};financial_impact:{state:string;reason:string};limitations:string[]};
type Selection={kind:"rule"|"publication"|"monitor";id:string};
type NavigationState={selected:Selection|null;category:"rules"|"publications"|"monitors";offsets:{rules:number;publications:number}};
type Load<T>={rows:T[];error:string;hasMore:boolean;nextOffset:number|null};
const human=(value:string)=>value.replaceAll("_"," ").toLowerCase();
const stamp=(value:string)=>Number.isFinite(Date.parse(value))?new Date(value).toLocaleString():"Not retained";
function restoreNavigation(key?:string):NavigationState {
 const fallback:NavigationState={selected:null,category:"rules",offsets:{rules:0,publications:0}};
 if(!key)return fallback;
 try {
  const saved=JSON.parse(sessionStorage.getItem(key)??"null");
  if(!saved||!["rules","publications","monitors"].includes(saved.category))return fallback;
  const selected=saved.selected;
  const validSelection=selected&&["rule","publication","monitor"].includes(selected.kind)&&typeof selected.id==="string"&&/^(?:[a-fA-F0-9-]{36}|rgm_[a-f0-9]{64})$/.test(selected.id);
  const page=(value:unknown)=>typeof value==="number"&&Number.isInteger(value)&&value>=0&&value<=100000&&value%100===0?value:0;
  return {category:saved.category,selected:validSelection?selected:null,offsets:{rules:page(saved.offsets?.rules),publications:page(saved.offsets?.publications)}};
 }catch{return fallback;}
}

export default function RegulatoryInvestigation({token,companyId,assessment,onAssessment,viewStateKey,handoff,...navigation}:RegulatoryNavigation&{token:string;companyId:string;assessment:Result|null;onAssessment:()=>void;viewStateKey?:string;handoff?:CompanyRegulationHandoff}) {
 const [snapshot]=useState(handoff);
 const [restored]=useState(()=>restoreNavigation(viewStateKey));
 const [publications,setPublications]=useState<Load<Publication>|null>(null);
 const [ruleResponse,setRuleResponse]=useState<{key:string;value:Load<Rule>}|null>(null);
 const [monitors,setMonitors]=useState<Load<Monitor>|null>(null);
 const [selected,setSelected]=useState<Selection|null>(restored.selected);
 const [revision,setRevision]=useState(0);
 const [monitorDetail,setMonitorDetail]=useState<{id:string;value:MonitorDetail|null;error:string}|null>(null);
 const [source,setSource]=useState<{id:string;observation:Observation;source_url:string}|null>(null);
 const [impact,setImpact]=useState<{id:string;value:Impact}|null>(null);
 const [action,setAction]=useState<{id:string;busy:boolean;error:string}|null>(null);
 const [category,setCategory]=useState<"rules"|"publications"|"monitors">(restored.category);
 const [offsets,setOffsets]=useState(restored.offsets);
 const ruleKey=JSON.stringify([token,companyId,regulationSnapshotKey(snapshot),offsets.rules,revision]);
 const rules=ruleResponse?.key===ruleKey?ruleResponse.value:null;
 useEffect(()=>{if(viewStateKey)try{sessionStorage.setItem(viewStateKey,JSON.stringify({selected,category,offsets}));}catch{/* Optional navigation state; authority stays on the server. */}},[viewStateKey,selected,category,offsets]);
 useEffect(()=>{
  const controller=new AbortController();
  async function load<T>(path:string,field?:string):Promise<Load<T>> {
   const read=async(resourcePath:string)=>{
    const response=await fetch(`/api/ontology/${resourcePath}`,{headers:{Authorization:`Bearer ${token}`},signal:AbortSignal.any([controller.signal,AbortSignal.timeout(20000)]),cache:"no-store"});
    if(!response.ok)throw new Error("This regulatory collection is unavailable. Retry to refresh its evidence.");
    return response.json();
   };
   const companyQuery=snapshot?new URLSearchParams({version_id:snapshot.company.version_id,known_at:snapshot.knownAt}):null;
   const [data,inspection]=await Promise.all([read(path),field==="rules"&&snapshot?read(`operator/resources/${snapshot.company.resource_id}?${companyQuery}`):Promise.resolve(null)]);
   const rawRows=field?data[field]:data;
   if(!Array.isArray(rawRows))throw new Error("Regulatory response did not contain a resource list.");
   if(field==="rules"){
    if(snapshot)assertRegulationHandoffPage(data as CompanyRegulationPage,inspection as OperatorInspection,snapshot,offsets.rules);
    else if(data.company?.resource_id!==companyId||!restorationInstant(data.at)||!restorationInstant(data.known_at)||rawRows.some((item:Result["rules"][number])=>(item.resource.attributes as {legal_entity_id?:string}).legal_entity_id!==companyId))throw Error("Regulatory interpretations did not retain their selected company and returned times.");
   }
   const rows=field==="rules"?rawRows.map((item:Result["rules"][number])=>({...item.resource,overview_assessment:item.assessment,overview_context:{at:data.at,known_at:data.known_at}})):rawRows;
   return {rows,error:"",hasMore:field?data.next_offset!==null:rows.length>=100,nextOffset:field&&typeof data.next_offset==="number"?data.next_offset:null};
  }
  async function loadRules():Promise<Load<Rule>>{return companyId?load<Rule>(`regulation/rules?${regulationRuleQuery(companyId,offsets.rules,snapshot)}`,"rules"):{rows:[],error:"",hasMore:false,nextOffset:null};}
  function publish<T>(request:Promise<Load<T>>,set:(value:Load<T>)=>void){return request.then(value=>{if(!controller.signal.aborted)set(value);}).catch(reason=>{if(!controller.signal.aborted)set({rows:[],error:reason instanceof Error?reason.message:"Collection unavailable",hasMore:false,nextOffset:null});});}
  void Promise.allSettled([
   publish(load<Publication>(`regulation/sources?offset=${offsets.publications}`,"publications"),setPublications),
   publish(loadRules(),value=>setRuleResponse({key:ruleKey,value})),
   publish(load<Monitor>("regulation/monitors"),setMonitors),
  ]);
  return()=>controller.abort();
 },[token,revision,companyId,offsets,snapshot,ruleKey]);
 const companyRules=rules?.rows.filter(row=>row.attributes.legal_entity_id===companyId)??[];
 const active=selected??(category==="rules"&&companyRules[0]?{kind:"rule",id:companyRules[0].resource_id}:category==="publications"&&publications?.rows[0]?{kind:"publication",id:publications.rows[0].resource_id}:category==="monitors"&&monitors?.rows[0]?{kind:"monitor",id:monitors.rows[0].workflow_id}:null);
 const rule=active?.kind==="rule"?companyRules.find(row=>row.resource_id===active.id):undefined;
 const publication=active?.kind==="publication"?publications?.rows.find(row=>row.resource_id===active.id):undefined;
 const monitor=active?.kind==="monitor"?monitors?.rows.find(row=>row.workflow_id===active.id):undefined;
 const monitorId=monitor?.workflow_id;
 useEffect(()=>{
  if(!monitorId)return;
  const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),20000);
  void fetch(`/api/ontology/regulation/monitors/${monitorId}`,{headers:{Authorization:`Bearer ${token}`},signal:controller.signal,cache:"no-store"}).then(async response=>{if(!response.ok)throw new Error("Monitor observations unavailable");return response.json();}).then(value=>{if(!controller.signal.aborted)setMonitorDetail({id:monitorId,value,error:""});}).catch(error=>{if(!cancelled)setMonitorDetail({id:monitorId,value:null,error:controller.signal.aborted?"Monitor observation request timed out":String(error)});});
  let cancelled=false;
  return()=>{cancelled=true;clearTimeout(timer);controller.abort();};
 },[token,monitorId,revision]);
 function choose(kind:Selection["kind"],id:string){setSelected({kind,id});}
 function section(next:typeof category){setCategory(next);setSelected(null);}
 function page(kind:"rules"|"publications",offset:number){if(kind==="rules")setRuleResponse(null);else setPublications(null);setOffsets(previous=>({...previous,[kind]:offset}));setSelected(null);}
 function links(resource:RegulatoryReference,knownAt?:string){return <div className="regi-links">{navigation.onInspect&&<button onClick={()=>navigation.onInspect?.(resource,knownAt)}>Inspect object</button>}{navigation.onTrace&&<button onClick={()=>navigation.onTrace?.(resource,knownAt)}>Trace evidence</button>}{navigation.onHistory&&<button onClick={()=>navigation.onHistory?.(resource,knownAt)}>Version history</button>}</div>;}
 async function sourceAction(documentId:string,kind:"inspect"|"impact") {
  setAction({id:documentId,busy:true,error:""});
  try {
   const response=await fetch(`/api/ontology/regulation/sources/${kind==="inspect"?`inspect?document_id=${encodeURIComponent(documentId)}`:"impact"}`,{method:kind==="impact"?"POST":"GET",headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},body:kind==="impact"?JSON.stringify({document_id:documentId}):undefined,cache:"no-store"});
   const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==="string"?data.detail:"Source investigation unavailable");
   if(kind==="inspect")setSource({id:documentId,observation:data.observation,source_url:data.source_url});else setImpact({id:documentId,value:data});
   setAction({id:documentId,busy:false,error:""});
  } catch(error){setAction({id:documentId,busy:false,error:error instanceof Error?error.message:"Investigation request failed"});}
 }
 const documentId=publication?.attributes.document_id;
 const detail=monitorDetail?.id===monitorId?monitorDetail:null;
 const retainedAssessment=rule&&!snapshot?assessment?.rules.find(item=>item.resource.version_id===rule.version_id):undefined;
 const assessed=retainedAssessment??(rule?.overview_assessment?{assessment:rule.overview_assessment}:undefined);
 return <section className="regi" aria-label="Regulatory investigation">
  <header className="regi-header"><div><p className="regi-eyebrow">REGULATORY INTELLIGENCE</p><h2>Evidence, readiness & potential impact</h2><p>Investigate what the retained evidence establishes, and what still needs review.</p></div><button onClick={()=>setRevision(value=>value+1)}><ClockCounterClockwise size={14}/>Refresh observations</button></header>
  <div className="regi-context"><span><ShieldCheck size={14}/>Company interpretations use the selected legal entity.</span><span>Publication and monitor lists show current retained observations across the authorized workspace; they do not inherit the company rule snapshot.</span></div>
  {snapshot&&<p className="regi-note">Company 360 rules snapshot ; effective {snapshot.validAt} ; known {snapshot.knownAt}. Company version and content are verified before any rule is shown. Applicability and compliance remain unestablished.</p>}
  <nav className="regi-tabs" aria-label="Regulatory observation collections">{(["rules","publications","monitors"] as const).map(kind=><button key={kind} aria-pressed={category===kind} onClick={()=>section(kind)}>{kind==="rules"?"Company readiness":kind==="publications"?"Legal source evidence":"Monitoring health"}</button>)}</nav>
  <div className="regi-split"><aside className="regi-queue" aria-label="Regulatory observations">
   {category==="rules"&&<>{rules?.error?<p role="alert">{rules.error}</p>:!rules?<p role="status">Loading reviewed interpretations…</p>:!companyId?<p>Select a company to inspect its reviewed interpretations.</p>:!companyRules.length?<p>No company interpretations in the loaded page. This is not evidence of no obligations.</p>:companyRules.map(row=><button key={row.version_id} aria-pressed={active?.id===row.resource_id} onClick={()=>choose("rule",row.resource_id)}><strong>{displayName(row.display_name)}</strong><span>{row.overview_assessment?.blocking_reasons?.length?row.overview_assessment.blocking_reasons.map(human).join(" · "):"Review assessment context"}</span><small>{human(row.attributes.definition.legal_status)} interpretation · {human(row.attributes.definition.activity)}</small></button>)}<div className="regi-pager"><button disabled={!rules||offsets.rules===0} onClick={()=>page("rules",Math.max(0,offsets.rules-100))}>Previous</button><span>Authorized page {Math.floor(offsets.rules/100)+1}</span><button disabled={rules?.nextOffset==null} onClick={()=>page("rules",rules!.nextOffset!)}>Next</button></div>{rules?.hasMore&&<p>Company filtering applies within each authorized rule page. Continue to see later matches.</p>}</>}
   {category==="publications"&&<>{publications?.error?<p role="alert">{publications.error}</p>:!publications?<p role="status">Loading retained publications…</p>:publications.rows.length?publications.rows.map(row=><button key={row.version_id} aria-pressed={active?.id===row.resource_id} onClick={()=>choose("publication",row.resource_id)}><strong>{row.attributes.observation.title}</strong><span>{human(row.attributes.observation.completeness)}</span><small>Matsne {row.attributes.observation.matsne_id} · publication {row.attributes.observation.publication??"unknown"}</small></button>):<p>No reviewed publications in this loaded scope.</p>}<div className="regi-pager"><button disabled={!publications||offsets.publications===0} onClick={()=>page("publications",Math.max(0,offsets.publications-100))}>Previous</button><span>Page {Math.floor(offsets.publications/100)+1}</span><button disabled={publications?.nextOffset==null} onClick={()=>page("publications",publications!.nextOffset!)}>Next</button></div></>}
   {category==="monitors"&&<>{monitors?.error?<p role="alert">{monitors.error}</p>:!monitors?<p role="status">Loading source monitors…</p>:monitors.rows.length?monitors.rows.map(row=><button key={row.workflow_id} aria-pressed={active?.id===row.workflow_id} onClick={()=>choose("monitor",row.workflow_id)}><strong>{row.request.name}</strong><span>Matsne {row.request.document_number} · publication {row.request.publication}</span><small>Check cadence {row.request.cadence_hours} hours · select to resolve health</small></button>):<p>No retained monitors in this workspace.</p>}{monitors?.hasMore&&<p>Most recent 100 monitors shown.</p>}</>}
  </aside><div className="regi-canvas">
   {(!active||(active.kind==="rule"&&rules&&!rule)||(active.kind==="publication"&&publications&&!publication)||(active.kind==="monitor"&&monitors&&!monitor))&&<div className="regi-empty"><FileText size={26}/><h3>{active?"Selected observation is not available in this loaded page":"Choose an observation to investigate"}</h3><p>Source evidence, company interpretations and monitor state remain separately inspectable.</p></div>}
   {rule&&<><header><p className="regi-eyebrow">COMPANY INTERPRETATION</p><h3>{displayName(rule.display_name)}</h3><p>{rule.attributes.definition.obligation}</p></header><dl className="regi-facts"><div><dt>Provision</dt><dd>{rule.attributes.definition.provision}</dd></div><div><dt>Declared legal status</dt><dd>{human(rule.attributes.definition.legal_status)}</dd></div><div><dt>Source completeness</dt><dd>{rule.attributes.definition.source_version_complete?"Declared complete in this interpretation":"Applicable source version incomplete"}</dd></div><div><dt>Interpreted effective dates</dt><dd>{rule.attributes.definition.effective_from} — {rule.attributes.definition.effective_to??"No end specified"}</dd></div><div><dt>Interpreted deadline</dt><dd>{rule.attributes.definition.deadline??"Not specified"}</dd></div></dl>
    {assessed?<section className="regi-readiness"><h4>{retainedAssessment?"Retained scenario assessment":snapshot?"Snapshot readiness with incomplete context":"Readiness at returned observation time"}</h4><p>{human(assessed.assessment.legal_state)} · {human(assessed.assessment.applicability)}</p><ul>{assessed.assessment.blocking_reasons?.map(reason=><li key={reason}>{human(reason)}</li>)}</ul><p>{assessed.assessment.effective_obligation?"This scenario meets the retained interpretation's applicability checks. Compliance is not certified.":"An effective obligation is not established by this assessment."}</p>{retainedAssessment?<small>Legal date {assessment?.assessment_context?.at} · known at {assessment?.assessment_context?.known_at}. This is a retained result, not a new current-use decision.</small>:<small>No activity or customer count was supplied. Legal date {rule.overview_context?.at} · known at {rule.overview_context?.known_at}. The server identifies missing context without assuming applicability.</small>}</section>:<section className="regi-readiness"><h4>What remains to establish</h4><p>Activity, customer count, legal date and licence evidence must be evaluated by the shared assessment service. No scenario is assumed here.</p></section>}
    <button className="regi-next" onClick={onAssessment}>Assess an explicit company scenario<ArrowRight size={14}/></button>{links(rule,rule.overview_context?.known_at)}
    <h4>Current retained publications sharing this act identity</h4><p>These publication observations are separate from the historical snapshot of the rule.</p>{publications?.rows.filter(row=>row.attributes.act_id===rule.attributes.act_id).map(row=><button className="regi-resource" key={row.version_id} onClick={()=>{setCategory("publications");choose("publication",row.resource_id);}}>{row.attributes.observation.title}<small>{human(row.attributes.observation.completeness)} · identity association, not proof of complete applicable law</small></button>)}
   </>}
   {publication&&documentId&&<><header><p className="regi-eyebrow">RETAINED LEGAL SOURCE</p><h3>{publication.attributes.observation.title}</h3><p>Matsne {publication.attributes.observation.matsne_id} · publication {publication.attributes.observation.publication??"unknown"}</p></header><section className="regi-readiness"><h4>{human(publication.attributes.observation.completeness)}</h4><p>Retained publication text does not establish current-law completeness or company applicability.</p><p>Attachments retained: {publication.attributes.observation.attachments_retained?"Yes":"No"} · Current law verified: {publication.attributes.observation.current_law_verified?"Yes":"No"}</p></section>{links(publication)}<div className="regi-links"><button disabled={action?.busy} onClick={()=>void sourceAction(documentId,"inspect")}>Read retained publication</button><button disabled={action?.busy} onClick={()=>void sourceAction(documentId,"impact")}>Trace potential dependency impact</button></div>
    {source?.id===documentId&&<section className="regi-original"><h4>Retained source text</h4><a href={source.source_url} target="_blank" rel="noreferrer">Open official publication</a><p className="regi-source-text">{source.observation.text}</p></section>}
    {impact?.id===documentId&&<section className="regi-impact"><h4>Potential dependency impact</h4><p>Snapshot {stamp(impact.value.observed_at)}. Reachability does not establish legal applicability.</p><p>Financial impact {human(impact.value.financial_impact.state)}: {impact.value.financial_impact.reason}</p>{impact.value.dependency_impact.affected.length?impact.value.dependency_impact.affected.map(item=><div className="regi-affected" key={item.version_id}><strong>{displayName(item.display_name)}</strong><small>{item.object_type} · dependency depth {item.depth}</small>{links(item)}</div>):<p>No registered downstream dependencies found. Missing links do not establish no business impact.</p>}<details><summary>Coverage and retained run</summary><ul>{impact.value.limitations.map(value=><li key={value}>{value}</li>)}</ul><code>{impact.value.run_id}</code></details></section>}
    {action?.id===documentId&&action.error&&<p role="alert">{action.error}</p>}{action?.id===documentId&&action.busy&&<p role="status">Resolving retained evidence…</p>}
   </>}
   {monitor&&<><header><p className="regi-eyebrow">SOURCE MONITOR</p><h3>{monitor.request.name}</h3><p>Cadence {monitor.request.cadence_hours} hours · publication {monitor.request.publication}</p></header>{!detail?<p role="status">Resolving source health and runtime availability…</p>:detail.error?<p role="alert">{detail.error}</p>:detail.value&&<><dl className="regi-facts"><div><dt>Latest check state</dt><dd>{human(detail.value.source_health)}</dd></div><div><dt>Check freshness</dt><dd>{human(detail.value.freshness)}</dd></div><div><dt>Runtime</dt><dd>{human(detail.value.runtime.state)}</dd></div><div><dt>Last successful check</dt><dd>{detail.value.last_success?stamp(detail.value.last_success.checked_at??detail.value.last_success.created_at):"No successful check retained"}</dd></div><div><dt>Last new observation</dt><dd>{detail.value.last_new_item?human(detail.value.last_new_item.state):"None retained"}</dd></div></dl><p className="regi-note">An initial capture is not a detected legal change. Check freshness describes the schedule; it does not establish current law.</p><h4>Recent retained checks</h4>{detail.value.events.slice(-20).reverse().map(event=><div className="regi-check" key={event.event_id}><strong>{human(event.state??"Recorded control")}</strong><small>{stamp(event.checked_at??event.created_at)}</small>{event.reason&&<p>{event.reason}</p>}{event.document&&<button onClick={()=>void sourceAction(event.document!.document_id,"inspect")}>Inspect this retained source</button>}</div>)}{action&&detail.value.events.some(event=>event.document?.document_id===action.id)&&<>{action.busy&&<p role="status">Reading retained source…</p>}{action.error&&<p role="alert">{action.error}</p>}</>}{source&&detail.value.events.some(event=>event.document?.document_id===source.id)&&<section className="regi-original"><h4>{source.observation.title}</h4><p>{human(source.observation.completeness)}</p><a href={source.source_url} target="_blank" rel="noreferrer">Open official publication</a><p className="regi-source-text">{source.observation.text}</p></section>}</>}{navigation.onWorkflow&&<button className="regi-next" onClick={()=>navigation.onWorkflow?.(monitor.workflow_id)}>Open retained workflow<ArrowRight size={14}/></button>}</>}
  </div></div>
 </section>;
}
