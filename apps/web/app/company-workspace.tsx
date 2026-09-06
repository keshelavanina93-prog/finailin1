"use client";

import {useEffect, useId, useState} from "react";
import type {CanonicalResource} from "@finai/contracts";
import {ArrowRight, Buildings, ClockCounterClockwise, Database, MagnifyingGlass, ShieldCheck} from "@phosphor-icons/react";
import {Badge} from "./g8-ui";
import {displayName} from "./display-name";
import "./company-workspace.css";
import CompanyStructureGraph from "./company-structure-graph";

type Node = CanonicalResource;
export type CompanyIndex = {source_companies:Node[];workspaces:{configuration:Node;company:Node;enterprise:Node;domain_pack:Node}[];reported_groups?:{reporter:Node;reporting_year:number;members:{company:Node;binding:Node;reported_percent:string|null;former_indicator:string}[]}[]};
export type Context = {company:Node;accounting_state:string;
 relationships:{kind:string;record:Node;source:Node;target:Node}[];
 structural_resources:Node[]; dimensions:Node[];
 ledgers:{ledger:Node;calendar_id:Node|null;chart_id:Node|null;currency_id:Node|null;books:Node[];periods:Node[];ready:boolean}[];
 disclosures:{binding:Node;reporter:Node;party:Node;observation:Node}[];
 accounting_sources:{scope:Node;bindings:Node[];binding_eligibility?:Record<string,{state:string;reason:string;checked_at:string|null;eligible_for_accounting:boolean}>}[];
 licence_evidence:{binding:Node;notice:Node|null;licence:Node|null}[];
};
export type CompanyDestination = "data"|"ontology"|"operations"|"regulation"|"workflows"|"finance";
type Tab = "overview"|"structure"|"accounting"|"evidence";
type Pins = Record<string,{resource_id:string;version_id:string}>;
const readable = (value:string) => value.replaceAll("_"," ").toLowerCase();
const date = (value:string) => Number.isFinite(Date.parse(value))?new Date(value).toLocaleDateString(undefined,{day:"numeric",month:"short",year:"numeric"}):"Not retained";
type ViewState={tab:Tab;search:string;companyId:string;ledgerId:string;bookId:string;periodId:string};
function restoreView(key:string|undefined,companyId:string):ViewState {
 const fallback:ViewState={tab:"overview",search:"",companyId,ledgerId:"",bookId:"",periodId:""};
 if(!key||typeof window==="undefined")return fallback;
 try {
  const saved=JSON.parse(sessionStorage.getItem(key)??"null") as Partial<ViewState>|null;
  if(!saved||saved.companyId!==companyId)return fallback;
  return {...fallback,tab:(["overview","structure","accounting","evidence"] as unknown[]).includes(saved.tab)?saved.tab!:"overview",search:typeof saved.search==="string"?saved.search.slice(0,200):"",...Object.fromEntries(["ledgerId","bookId","periodId"].map(field=>[field,typeof saved[field as keyof ViewState]==="string"&&/^[\w-]{0,100}$/.test(saved[field as keyof ViewState]!)?saved[field as keyof ViewState]:""]))};
 } catch {return fallback;}
}

export default function CompanyWorkspace({token,index,companyId,onSelect,onInspect,onNavigate,onHistory,onTrace,viewStateKey,initialTab}:{token:string;index:CompanyIndex|null;companyId:string;onSelect:(node:Node)=>void;onInspect:(node:Node)=>void;onNavigate?:(destination:CompanyDestination)=>void;onHistory?:(node:Node)=>void;onTrace?:(node:Node)=>void;viewStateKey?:string;initialTab?:Tab}) {
 const [loaded,setLoaded]=useState<{key:string;context:Context|null;error:string}|null>(null);
 const [refresh,setRefresh]=useState(0);
 const [restored]=useState(()=>restoreView(viewStateKey,companyId));
 const [tab,setTab]=useState<Tab>(initialTab??restored.tab);
 const [search,setSearch]=useState(restored.search);
 const [choice,setChoice]=useState({companyId,ledgerId:restored.ledgerId,bookId:restored.bookId,periodId:restored.periodId});
 const [directoryPage,setDirectoryPage]=useState(0);
 const [validated,setValidated]=useState<{key:string;pins:Pins|null;error:string}|null>(null);
 const id=useId();
 const contextKey=JSON.stringify([token,companyId,refresh]);
 const context=loaded?.key===contextKey?loaded.context:null;
 const error=loaded?.key===contextKey?loaded.error:"";
 const busy=Boolean(companyId)&&loaded?.key!==contextKey;
 const selected=choice.companyId===companyId?choice:{companyId,ledgerId:"",bookId:"",periodId:""};
 const {ledgerId,bookId,periodId}=selected;
 const selectionKey=JSON.stringify([contextKey,ledgerId,bookId,periodId]);
 const selection=validated?.key===selectionKey?validated:null;
 const validating=Boolean(context&&ledgerId&&bookId&&periodId)&&!selection;
 useEffect(()=>{if(viewStateKey)try{sessionStorage.setItem(viewStateKey,JSON.stringify({companyId,tab,search,ledgerId,bookId,periodId}));}catch{/* Storage restrictions do not block company work. */}},[viewStateKey,companyId,tab,search,ledgerId,bookId,periodId]);
 useEffect(()=>{
  if(!companyId)return;
  const controller=new AbortController();
  void fetch(`/api/ontology/company-context?company_id=${encodeURIComponent(companyId)}`,{headers:{Authorization:`Bearer ${token}`},signal:controller.signal,cache:"no-store"})
   .then(async response=>{const data=await response.json();if(!response.ok)throw Error(typeof data.detail==="string"?data.detail:"Company context unavailable");if(!controller.signal.aborted)setLoaded({key:contextKey,context:data.context,error:""});})
   .catch(failure=>{if(!controller.signal.aborted)setLoaded({key:contextKey,context:null,error:failure instanceof Error?failure.message:"Company context unavailable"});});
  return ()=>controller.abort();
 },[token,companyId,contextKey]);
 useEffect(()=>{
  if(!context||!companyId||!ledgerId||!bookId||!periodId)return;
  const controller=new AbortController();
  const params=new URLSearchParams({company_id:companyId,ledger_id:ledgerId,book_id:bookId,period_id:periodId});
  void fetch(`/api/ontology/company-context?${params}`,{headers:{Authorization:`Bearer ${token}`},signal:controller.signal,cache:"no-store"})
   .then(async response=>{const data=await response.json();if(!response.ok)throw Error(typeof data.detail==="string"?data.detail:"Accounting context rejected");if(!controller.signal.aborted)setValidated({key:selectionKey,pins:data.accounting_selection,error:""});})
   .catch(failure=>{if(!controller.signal.aborted)setValidated({key:selectionKey,pins:null,error:failure instanceof Error?failure.message:"Accounting context unavailable"});});
  return ()=>controller.abort();
 },[token,companyId,ledgerId,bookId,periodId,selectionKey,context]);

 const directory=new Map<string,{node:Node;workspace:boolean;source:boolean;years:Set<number>}>();
 function add(node:Node,kind:"workspace"|"source"|"reported",year?:number){const entry=directory.get(node.resource_id)??{node,workspace:false,source:false,years:new Set<number>()};if(kind==="workspace")entry.workspace=true;if(kind==="source")entry.source=true;if(year!==undefined)entry.years.add(year);directory.set(node.resource_id,entry);}
 index?.workspaces.forEach(item=>add(item.company,"workspace"));
 index?.source_companies.forEach(node=>add(node,"source"));
 index?.reported_groups?.forEach(group=>{add(group.reporter,"reported",group.reporting_year);group.members.forEach(member=>add(member.company,"reported",group.reporting_year));});
 if(context&&!directory.has(companyId))add(context.company,"source");
 const companies=[...directory.values()].filter(({node})=>`${node.display_name} ${String(node.attributes.registration_code??"")}`.toLowerCase().includes(search.toLowerCase())).sort((a,b)=>Number(b.workspace)-Number(a.workspace)||displayName(a.node.display_name).localeCompare(displayName(b.node.display_name)));
 const company=context?.company??directory.get(companyId)?.node;
 const configurations=index?.workspaces.filter(item=>item.company.resource_id===companyId)??[];
 const ledger=context?.ledgers.find(item=>item.ledger.resource_id===ledgerId);
 const missingLedger=context?!context.ledgers.length:false;
 const incompleteLedgers=context?.ledgers.filter(item=>!item.ready)??[];
 const unresolvedSources=context?.accounting_sources.filter(source=>!source.bindings.some(binding=>source.binding_eligibility?.[binding.version_id]?.eligible_for_accounting===true))??[];
 const attention=context?[
  ...(missingLedger?[{title:"Establish the company accounting context",reason:"No accepted ledger is configured. A company name cannot establish books, periods or monetary meaning.",label:"Review accounting context",tab:"accounting" as Tab}]:[]),
  ...(incompleteLedgers.length?[{title:"Complete the linked ledger context",reason:`${incompleteLedgers.length} ledger context${incompleteLedgers.length===1?"":"s"} require review of chart, calendar, currency, books or periods.`,label:"Inspect ledger dependencies",tab:"accounting" as Tab}]:[]),
  ...(unresolvedSources.length?[{title:"Review current accounting use of company sources",reason:`${unresolvedSources.length} source scope${unresolvedSources.length===1?"":"s"} have no currently eligible accounting binding reported by the server. Reviewed declarations and current use are separate.`,label:"Review source bindings",tab:"accounting" as Tab}]:[]),
  ...(!context.accounting_sources.length?[{title:"Connect evidence to this company",reason:"No source accounting scope is linked to this company. Retained files alone do not establish company accounting coverage.",label:"Inspect source coverage",tab:"evidence" as Tab}]:[]),
 ]:[];
 const recent=context?[...new Map([context.company,...context.relationships.map(row=>row.record),...context.accounting_sources.flatMap(row=>[row.scope,...row.bindings]),...context.licence_evidence.map(row=>row.binding)].map(node=>[node.version_id,node])).values()].sort((a,b)=>Date.parse(b.system_from)-Date.parse(a.system_from)).slice(0,5):[];
 function pick(node:Node){setTab("overview");onSelect(node);}
 function inspect(node:Node){onInspect(node);}
 function actions(node:Node){return <span className="c360-inline-actions"><button onClick={()=>inspect(node)}>Inspect</button>{onTrace&&<button onClick={()=>onTrace(node)}>Trace</button>}{onHistory&&<button onClick={()=>onHistory(node)}>History</button>}</span>;}
 function route(destination:CompanyDestination,label:string){return onNavigate?<button className="c360-route" onClick={()=>onNavigate(destination)}>{label}<ArrowRight size={14}/></button>:null;}
 function sourceRows(){return context?.accounting_sources.length?<div className="c360-table-wrap"><table><thead><tr><th>Source scope</th><th>Observed dates</th><th>Declared use</th><th>Evidence</th></tr></thead><tbody>{context.accounting_sources.map(source=><tr key={source.scope.resource_id}><th scope="row"><button className="c360-text-button" onClick={()=>inspect(source.scope)}>{displayName(source.scope.display_name)}</button><small>{String(source.scope.attributes.worksheet??"")}</small></th><td>{String(source.scope.attributes.observed_from)}<br/>{String(source.scope.attributes.observed_through)}</td><td>{source.bindings.length?source.bindings.map(binding=><div key={binding.resource_id}><button className="c360-text-button" onClick={()=>inspect(binding)}>{readable(String(binding.attributes.source_use))}</button>{Boolean(binding.attributes.contract_version)&&<small>Interpretation version {String(binding.attributes.contract_version)}</small>}<small className={source.binding_eligibility?.[binding.version_id]?.eligible_for_accounting?"":"c360-attention-text"}>{readable(source.binding_eligibility?.[binding.version_id]?.state??"ELIGIBILITY_NOT_CHECKED")}</small>{source.binding_eligibility?.[binding.version_id]?.reason&&<small>{source.binding_eligibility[binding.version_id].reason}</small>}{source.binding_eligibility?.[binding.version_id]?.checked_at&&<small>Checked {new Date(source.binding_eligibility[binding.version_id].checked_at!).toLocaleString()}</small>}</div>):<span className="c360-attention-text">Use unresolved</span>}</td><td>{actions(source.scope)}</td></tr>)}</tbody></table></div>:<div className="c360-empty"><Database size={24}/><h4>No company-bound accounting sources</h4><p>Bind retained evidence to the accepted company before declaring its accounting use.</p>{route("data","Open Data")}</div>;}

 return <div className="c360-workbench">
  <aside className="c360-directory" aria-label="Company directory"><header><Buildings size={20}/><div><strong>Companies</strong><small>{index?`${directory.size} retained contexts`:"Directory loading"}</small></div></header>
   <label className="c360-search"><MagnifyingGlass size={15}/><input value={search} onChange={event=>{setSearch(event.target.value);setDirectoryPage(0);}} placeholder="Find a company" aria-label="Find company by name or registration code"/></label>
   <nav aria-label="Choose company">{companies.slice(directoryPage*50,(directoryPage+1)*50).map(entry=><button key={entry.node.resource_id} className={companyId===entry.node.resource_id?"selected":""} aria-pressed={companyId===entry.node.resource_id} onClick={()=>pick(entry.node)}><span className="c360-company-mark">{displayName(entry.node.display_name).slice(0,1)}</span><span><strong>{displayName(entry.node.display_name)}</strong><small>{entry.workspace?"Configured workspace":entry.source?"Source company context":`Reported in ${[...entry.years].sort().join(", ")}`}</small></span>{companyId===entry.node.resource_id&&<ArrowRight size={13}/>}</button>)}</nav>
   {companies.length>50&&<div className="c360-pager"><button disabled={directoryPage===0} onClick={()=>setDirectoryPage(value=>value-1)}>Previous</button><span>{directoryPage*50+1}–{Math.min((directoryPage+1)*50,companies.length)} / {companies.length}</span><button disabled={(directoryPage+1)*50>=companies.length} onClick={()=>setDirectoryPage(value=>value+1)}>Next</button></div>}
   {index&&!companies.length&&<p className="c360-directory-note">No company matches this search.</p>}
   <footer>Company identity first.<br/>Reported relationships retain their filing date.</footer>
  </aside>
  <div className="c360-canvas">
   {!companyId?<div className="c360-empty c360-welcome"><Buildings size={34}/><p className="c360-eyebrow">COMPANY WORKSPACE</p><h2>Select the company behind your work</h2><p>Its accounting coverage, operating relationships and evidence will resolve from shared accepted resources.</p></div>:<>
    <header className="c360-hero"><div><p className="c360-eyebrow">COMPANY 360</p><h2>{company?displayName(company.display_name):"Resolving company"}</h2><p>{configurations.length?configurations.map(item=>displayName(item.domain_pack.display_name)).join(" · "):"Shared legal-entity context"}</p>{Boolean(company?.attributes.registration_code)&&<span className="c360-registration">Registration {String(company?.attributes.registration_code)}</span>}</div><div className="c360-hero-actions"><Badge>{context?"Accepted company context":busy?"Resolving context":"Context unavailable"}</Badge><button disabled={busy} onClick={()=>setRefresh(value=>value+1)} aria-label="Refresh company context"><ClockCounterClockwise size={15}/>Refresh</button>{context&&onHistory&&<button onClick={()=>onHistory(context.company)}>Company history</button>}</div></header>
    <nav className="c360-tabs" aria-label="Company workspace sections">{(["overview","structure","accounting","evidence"] as Tab[]).map(value=><button key={value} aria-pressed={tab===value} onClick={()=>setTab(value)}>{value.charAt(0).toUpperCase()+value.slice(1)}</button>)}</nav>
    {busy&&<div className="c360-loading" role="status">Resolving accepted company relationships, source coverage and accounting context…</div>}
    {error&&<div className="c360-error" role="alert"><h3>Company context could not be resolved</h3><p>{error}</p></div>}
    {context&&<div className="c360-content">
     {tab==="overview"&&<>
      <div className="c360-overview-grid"><section className="c360-section"><header><div><p className="c360-eyebrow">PRIORITIES</p><h3>What needs attention</h3></div><span className="c360-small">From the current context</span></header>
       {attention.length?<ol className="c360-attention">{attention.map(item=><li key={item.title}><span className="c360-attention-dot"/><div><h4>{item.title}</h4><p>{item.reason}</p><button className="c360-text-button" onClick={()=>setTab(item.tab)}>{item.label}<ArrowRight size={13}/></button></div></li>)}</ol>:<div className="c360-empty"><ShieldCheck size={24}/><h4>No missing configuration identified by this view</h4><p>Source coverage and financial authority still require their own execution checks.</p></div>}
       <footer className="c360-section-foot">Configuration coverage is not financial performance or certification.</footer>
      </section><section className="c360-section"><header><div><p className="c360-eyebrow">WORKING CONTEXT</p><h3>Connected company coverage</h3></div></header><dl className="c360-coverage"><div><dt>Accounting</dt><dd>{context.ledgers.length?`${context.ledgers.length} linked ledger${context.ledgers.length===1?"":"s"}`:"Ledger not configured"}</dd></div><div><dt>Source evidence</dt><dd>{context.accounting_sources.length?`${context.accounting_sources.length} accounting scopes`:"No accounting source scope"}</dd></div><div><dt>Company structure</dt><dd>{context.relationships.length?`${context.relationships.length} effective relationships`:"No effective relationships"}</dd></div><div><dt>Analytical dimensions</dt><dd>{context.dimensions.length?`${context.dimensions.length} linked resources`:"No dimension model bound"}</dd></div><div><dt>Licence evidence</dt><dd>{context.licence_evidence.length?`${context.licence_evidence.length} retained bindings`:"No licence evidence linked"}</dd></div></dl><div className="c360-destinations">{route("data","Data & sources")}{route("ontology","Ontology")}{route("operations","Operations & maps")}{route("regulation","Regulation")}{route("workflows","Workflows & actions")}</div></section></div>
      <section className="c360-section"><header><div><p className="c360-eyebrow">WHAT CHANGED</p><h3>Latest retained versions</h3></div><span className="c360-small">Company, relationship and source records</span></header><div className="c360-table-wrap"><table><thead><tr><th>Resource</th><th>Recorded</th><th>Effective from</th><th>Evidence</th></tr></thead><tbody>{recent.map(node=><tr key={node.version_id}><th scope="row"><button className="c360-text-button" onClick={()=>inspect(node)}>{displayName(node.display_name)}</button><small>{node.object_type.replace(/([a-z])([A-Z])/g,"$1 $2")}</small></th><td>{date(node.system_from)}</td><td>{date(node.valid_from)}</td><td>{actions(node)}</td></tr>)}</tbody></table></div></section>
     </>}
     {tab==="structure"&&<>
      {configurations.length>0&&<section className="c360-section"><header><h3>Configured workspace</h3></header>{configurations.map(item=><div className="c360-structure-row" key={item.configuration.resource_id}><Buildings size={19}/><div><strong>{displayName(item.enterprise.display_name)} → {displayName(item.company.display_name)}</strong><p>{displayName(item.domain_pack.display_name)} · attached industry semantics</p></div>{actions(item.configuration)}</div>)}<footer className="c360-section-foot">Workspace grouping is separate from corporate ownership.</footer></section>}
      <CompanyStructureGraph context={context} onInspect={inspect} onSelect={pick} onTrace={onTrace}/>
      {context.structural_resources.length>0&&<section className="c360-section"><header><h3>Linked operating and structural resources</h3></header>{context.structural_resources.map(node=><div className="c360-resource-row" key={node.resource_id}><div><strong>{displayName(node.display_name)}</strong><small>{node.object_type.replace(/([a-z])([A-Z])/g,"$1 $2")}</small></div>{actions(node)}</div>)}</section>}
     </>}
     {tab==="accounting"&&<>
      <section className="c360-section"><header><div><p className="c360-eyebrow">ACCOUNTING BOUNDARIES</p><h3>Ledger, book and period</h3></div><Badge tone={context.ledgers.length?"neutral":"warning"}>{readable(context.accounting_state)}</Badge></header>
       {!context.ledgers.length?<div className="c360-empty"><h4>No accepted ledger is configured</h4><p>Accounting values, books and functional currency cannot be inferred from this company name.</p>{route("ontology","Review company accounting resources")}</div>:<div className="c360-accounting-select"><label htmlFor={`${id}-ledger`}>Company ledger<select id={`${id}-ledger`} value={ledgerId} onChange={event=>setChoice({companyId,ledgerId:event.target.value,bookId:"",periodId:""})}><option value="">Select ledger</option>{context.ledgers.map(item=><option key={item.ledger.resource_id} value={item.ledger.resource_id}>{displayName(item.ledger.display_name)}</option>)}</select></label>
        {ledger&&<><label htmlFor={`${id}-book`}>Accounting book<select id={`${id}-book`} value={bookId} onChange={event=>setChoice({...selected,bookId:event.target.value})}><option value="">Select book</option>{ledger.books.map(book=><option key={book.resource_id} value={book.resource_id}>{displayName(book.display_name)}</option>)}</select></label><label htmlFor={`${id}-period`}>Fiscal period<select id={`${id}-period`} value={periodId} onChange={event=>setChoice({...selected,periodId:event.target.value})}><option value="">Select period</option>{ledger.periods.map(period=><option key={period.resource_id} value={period.resource_id}>{displayName(period.display_name)}</option>)}</select></label></>}
       </div>}
       {ledger&&<div className="c360-ledger-context"><dl className="c360-coverage"><div><dt>Chart of accounts</dt><dd>{ledger.chart_id?displayName(ledger.chart_id.display_name):"Unresolved"}</dd></div><div><dt>Fiscal calendar</dt><dd>{ledger.calendar_id?displayName(ledger.calendar_id.display_name):"Unresolved"}</dd></div><div><dt>Currency context</dt><dd>{ledger.currency_id?displayName(ledger.currency_id.display_name):"Unresolved"}</dd></div></dl>{actions(ledger.ledger)}</div>}
       {validating&&<p className="c360-message" role="status">Validating the selected company, ledger, book and period…</p>}{selection?.error&&<p className="c360-error" role="alert">{selection.error}</p>}
       {selection?.pins&&<div className="c360-message"><p><ShieldCheck size={15}/> Selected accounting context validated by the server.</p><details><summary>Exact canonical version references</summary><dl>{Object.entries(selection.pins).map(([field,pin])=><div key={field}><dt>{readable(field)}</dt><dd><code>{pin.resource_id} · {pin.version_id}</code></dd></div>)}</dl></details></div>}
      </section><section className="c360-section"><header><h3>Company-bound source accounting</h3>{route("data","Open source review")}</header>{sourceRows()}<footer className="c360-section-foot">A declared accounting input is rechecked at execution. Financial certification is not implied.</footer></section>
      <section className="c360-section"><header><h3>Analytical dimensions</h3></header>{context.dimensions.length?context.dimensions.map(node=><div className="c360-resource-row" key={node.resource_id}><div><strong>{displayName(node.display_name)}</strong>{Boolean(node.attributes.source_header)&&<small>Source label: {String(node.attributes.source_header)}</small>}</div>{actions(node)}</div>):<p className="c360-message">No source analytical dimension model is bound to this company.</p>}</section>
     </>}
     {tab==="evidence"&&<>
      <section className="c360-section"><header><div><p className="c360-eyebrow">SOURCE COVERAGE</p><h3>Accounting evidence</h3></div>{route("data","Inspect retained sources")}</header>{sourceRows()}</section>
      <section className="c360-section"><header><h3>Licence evidence</h3>{route("regulation","Open Regulation")}</header>{context.licence_evidence.length?context.licence_evidence.map(item=><div className="c360-resource-row" key={item.binding.resource_id}><div><strong>{item.licence?displayName(item.licence.display_name):"Licence dependency requires review"}</strong><small>Retained issuance evidence · current licence authority is separate</small></div>{actions(item.binding)}</div>):<p className="c360-message">No licence notice is bound to this company. This view does not determine whether a licence is required.</p>}</section>
      <section className="c360-section"><header><div><p className="c360-eyebrow">DATED SOURCE STATEMENTS</p><h3>Reported company relationships</h3></div></header><p className="c360-message">Filing relationships retain their reporting year. They do not establish current ownership, licence status or consolidation scope.</p>
       {context.disclosures.length?context.disclosures.map(disclosure=>{const observation=disclosure.observation.attributes.observation as {reported_role?:string;reported_percent?:string|null;former_indicator?:string};return <details className="c360-filing" key={disclosure.binding.resource_id}><summary>{String(disclosure.binding.attributes.reporting_year)} · {displayName(disclosure.reporter.display_name)} → {displayName(disclosure.party.display_name)}</summary><p>Reported role: {observation.reported_role?readable(observation.reported_role):"Not stated"} · {observation.reported_percent==null?"Participation not stated":`Reported ${observation.reported_percent}%`}{observation.former_indicator?` · former-party marker: ${observation.former_indicator}`:""}</p><div className="c360-inline-actions"><button onClick={()=>pick(disclosure.party)}>Open related company</button>{actions(disclosure.binding)}</div></details>;}):<p className="c360-message">No reviewed corporate disclosure bindings.</p>}
       {index?.reported_groups?.filter(group=>group.reporter.resource_id===companyId).map(group=><details className="c360-filing" key={`${group.reporter.resource_id}:${group.reporting_year}`}><summary>{group.reporting_year} filing · {group.members.length} reported company relationships</summary><ul>{group.members.map(member=><li key={member.binding.resource_id}><button className="c360-text-button" onClick={()=>pick(member.company)}>{displayName(member.company.display_name)}</button> · {member.reported_percent===null?"participation not stated":`reported ${member.reported_percent}%`}{member.former_indicator?" · former-party marker":""} {actions(member.binding)}</li>)}</ul></details>)}
      </section>
     </>}
     <footer className="c360-canvas-foot"><span><ShieldCheck size={14}/> Shared company context · effective resources and retained evidence</span><details><summary>Company identity & version</summary><code>{context.company.resource_id}<br/>{context.company.version_id}</code><button onClick={()=>inspect(context.company)}>Inspect company resource</button></details></footer>
    </div>}
   </>}
  </div>
 </div>;
}
