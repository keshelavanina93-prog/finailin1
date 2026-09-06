"use client";
import {displayName} from "./display-name";
import CompanyPicker from "./company-picker";
import WorkspaceSearchResults from "./workspace-search-results";

import { useCallback, useEffect, useRef, useState, type FormEvent, type CSSProperties } from "react";
import dynamic from "next/dynamic";
import Image from "next/image";
import { House, Buildings, Database, Graph as GraphIcon, GearSix, MagnifyingGlass, ArrowRight, ArrowClockwise, SignOut, ShieldCheck, Tray, UploadSimple, List, X, CaretRight, SidebarSimple, ArrowsOutSimple, ChartLineUp, CalendarBlank, ChartBar, Notebook, MapTrifold, Scales, FlowArrow } from "@phosphor-icons/react";
import type { OperatorInspection, HistorySearchResult, CanonicalResource, IntakeItem, Principal, ReceiptDetail, ResourceProposalDetail } from "@finai/contracts";
import type { EngineeringView } from "./operator-workspace";
import { Badge, Brand, Empty, Panel, Signal } from "./g8-ui";
import { belongsToCompany, emptySnapshot, readable, workItems, type Loadable, type Snapshot, type WorkItem } from "./g8-model";
import ProposalImpact from "./proposal-impact";
import PromotionReadiness from "./promotion-readiness";
import ResourceAuthority from "./resource-authority";
import SourceExplorer from "./source-explorer";
import DataWorkspace from "./data-workspace";
import SourceDocuments from "./source-documents";
import CompanyWorkspace, {type CompanyIndex, type Context as ResolvedCompanyContext} from "./company-workspace";
import NyxInteraction from "./nyx-interaction";
import WorkQueue,{WorkspaceHealth} from "./work-queue";
import OperationsMap from "./operations-map";
import {initialMapState,type MapWorkspaceState,type MapSelection} from "./operations-model";
import ExecutiveOverview from "./executive-overview";
import ObjectSets from "./object-sets";
import AccountingFacts from "./accounting-facts";
import RegulationWorkspace from "./regulation-workspace";
import type {TraceSelection} from "./operator-trace";
import type {HistorySelection} from "./history-model";
const HistoryExplorer = dynamic(()=>import("./history-explorer"));
const ActionWorkbench = dynamic(()=>import("./action-workbench"));
const OperatorHistory = dynamic(()=>import("./operator-history"));
const OperatorTrace = dynamic(()=>import("./operator-trace"));

const Engineering = dynamic(() => import("./operator-workspace"), {loading:() => <p role="status">Opening engineering tools…</p>});
type View = "home" | "companies" | "data" | "ontology" | "system" | "operations" | "regulation" | "actions";
const areas = [{id:"home",label:"Home",hint:"My work",icon:House},{id:"companies",label:"Companies",hint:undefined,icon:Buildings},{id:"data",label:"Data",hint:undefined,icon:Database},{id:"ontology",label:"Ontology",hint:undefined,icon:GraphIcon}] as const;
const navigation = [
 {...areas[0],available:true},{...areas[1],available:true},
 {id:"finance",label:"Finance",hint:undefined,icon:ChartLineUp,available:false},
 {id:"planning",label:"Planning",hint:undefined,icon:Notebook,available:false},
 {id:"reporting",label:"Reporting",hint:undefined,icon:ChartBar,available:false},
 {...areas[2],available:true},{...areas[3],available:true},
 {id:"operations",label:"Operations & Maps",hint:undefined,icon:MapTrifold,available:true},
 {id:"regulation",label:"Regulation",hint:undefined,icon:Scales,available:true},
 {id:"actions",label:"Workflows & Actions",hint:undefined,icon:FlowArrow,available:true},
];
const tone = (state: string) => state === "APPROVED" || state === "ready" ? "good" : state === "REJECTED" || state === "REVOKED" ? "bad" : state === "PENDING" ? "warning" : "neutral";
const date = (value: string) => new Date(value).toLocaleDateString(undefined,{month:"short",day:"numeric"});
async function get<T>(path: string, token: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api/${path}`,{headers:{Authorization:`Bearer ${token}`},cache:"no-store",signal});
  const data = await response.json();
  // A readiness response is an observed degraded state, not a failed data request.
  if (!response.ok && !(path === "readiness" && data.evidence_store)) throw new Error(typeof data.detail === "string" ? data.detail : `Request unavailable (${response.status})`);
  return data as T;
}

export default function G8Workspace() {
  const [session,setSession] = useState<{token:string;principal:Principal} | null>(null);
  const [error,setError] = useState(""); const [busy,setBusy] = useState(false);
  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const token = String(new FormData(event.currentTarget).get("token") ?? "").trim();
    try {const principal = await get<Principal>("workspace/session",token); setSession({token,principal});}
    catch (failure) {setError(failure instanceof Error ? failure.message : "Sign-in unavailable");}
    finally {setBusy(false);}
  }
  if (session) return <SignedIn key={session.principal.actor_id} {...session} onSignOut={() => setSession(null)} />;
  return <main className="g8-login"><section className="g8-login-story"><Brand /><div><p className="overline">ENTERPRISE INTELLIGENCE</p><h1>From source evidence<br />to reviewed enterprise state.</h1><p>One workspace for your companies, retained sources and governed decisions.</p><div className="g8-principles"><span>Exact context<small>Company and version stay bound.</small></span><span>Visible evidence<small>Trace every accepted change.</small></span><span>Controlled action<small>Independent review is preserved.</small></span></div></div><Image className="g8-brand-banner" src="/brand/g8-login-art.png" alt="G8 cognition emblem with connected data ribbons" width={2172} height={724} priority /></section><section className="g8-login-form"><form onSubmit={signIn}><ShieldCheck size={30} /><p className="overline">G8 WORKSPACE ACCESS</p><h2>Sign in to your workspace</h2><p>Your identity determines the company access, evidence and actions available to you.</p><label>Workspace access key<input name="token" type="password" required autoComplete="off" autoFocus /></label><button disabled={busy}>{busy ? "Connecting…" : "Continue securely"}<ArrowRight size={18} /></button>{error && <p role="alert" className="error-banner">{error}</p>}<small>Use your organization-issued access key. It stays in memory for this session.</small></form></section></main>;
}

function SignedIn({token,principal,onSignOut}: {token:string;principal:Principal;onSignOut:()=>void}) {
  const contextKey=`g8-work-context:${principal.actor_id}:${JSON.stringify(principal.scope)}`;
  const [savedContext]=useState<{companyId:string;view:View;trace:TraceSelection|null;history:HistorySelection|null}>(()=>{
    const empty={companyId:"",view:"home" as View,trace:null,history:null};
    try{const saved=JSON.parse(sessionStorage.getItem(contextKey)??"{}");const id=/^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$/;
      const companyId=typeof saved.companyId==="string"&&id.test(saved.companyId)?saved.companyId:"";
      const view=["home","companies","data","ontology","operations","regulation","actions"].includes(saved.view)?saved.view as View:"home";
      const trace=saved.trace&&id.test(saved.trace.resource_id)&&id.test(saved.trace.version_id)&&saved.trace.company_id===companyId?saved.trace:null;
      const history=saved.history&&id.test(saved.history.resource_id)&&id.test(saved.history.version_id)&&saved.history.company_id===companyId?saved.history:null;
      return {companyId,view,trace,history};
    }catch{return empty;}
  });
  const [mapState,setMapState]=useState<MapWorkspaceState>(initialMapState);const [mapSelection,setMapSelection]=useState<MapSelection|null>(null);
  const [resolvedCompany,setResolvedCompany]=useState<ResolvedCompanyContext|null>(null);
  const [companyContextError,setCompanyContextError]=useState("");
  const [companyIndex,setCompanyIndex] = useState<CompanyIndex|null>(null);
  const [exploredCompany,setExploredCompany] = useState<CanonicalResource|null>(null);
  const [companyDirectory,setCompanyDirectory] = useState<Loadable<CanonicalResource[]>>({data:null,error:null});
  const [view,setView] = useState<View>(savedContext.view); const [snapshot,setSnapshot] = useState<Snapshot>(emptySnapshot);
  const [loading,setLoading] = useState(true); const [revision,setRevision] = useState(0); const [updated,setUpdated] = useState("");
  const [companyId,setCompanyId] = useState(savedContext.companyId); const [search,setSearch] = useState(""); const [workFilter,setWorkFilter] = useState("pending");
  const [trace,setTrace]=useState<TraceSelection|null>(savedContext.trace);
  const [history,setHistory]=useState<HistorySelection|null>(savedContext.history);
  useEffect(()=>{try{sessionStorage.setItem(contextKey,JSON.stringify({companyId,view,trace,history}));}catch{/* Navigation can operate without browser storage. */}},[contextKey,companyId,view,trace,history]);
  const [sourceSelectionKey,setSourceSelectionKey] = useState(0);
  const [actionTarget,setActionTarget] = useState<{workflowId:string;companyId:string}|null>(null);
  const [selected,setSelected] = useState<(OperatorInspection) | null>(null); const [work,setWork] = useState<WorkItem | null>(null);
  const [receipt,setReceipt] = useState<ReceiptDetail | null>(null); const [proposal,setProposal] = useState<ResourceProposalDetail | null>(null);
  const [detailError,setDetailError] = useState(""); const [detailBusy,setDetailBusy] = useState(false);
  const [engineering,setEngineering] = useState<{view:EngineeringView;receiptId?:string;proposalId?:string}>({view:"intake"});
  const [menu,setMenu] = useState(false); const [rail,setRail] = useState(false);
  const [savedLayout]=useState(()=>{try {const value=JSON.parse(localStorage.getItem("g8-layout-v1")??"{}");return {nav:value.nav===true,nyx:value.nyx===true,width:typeof value.width==="number"&&Number.isFinite(value.width)?Math.max(300,Math.min(1600,value.width)):340};}catch{return {nav:false,nyx:false,width:340};}});
  const [navFolded,setNavFolded]=useState(savedLayout.nav);const [nyxFolded,setNyxFolded]=useState(savedLayout.nyx);
  const [nyxWidth,setNyxWidth]=useState(savedLayout.width);
  useEffect(()=>{try{localStorage.setItem("g8-layout-v1",JSON.stringify({nav:navFolded,nyx:nyxFolded,width:nyxWidth}));}catch{/* Layout persistence is optional. */}},[navFolded,nyxFolded,nyxWidth]);const [viewport,setViewport]=useState(1440);
  const [nyxTab,setNyxTab]=useState("interact");
  const drag=useRef<{x:number;width:number}|null>(null);
  useEffect(()=>{const resize=()=>setViewport(window.innerWidth);resize();window.addEventListener("resize",resize);return()=>window.removeEventListener("resize",resize);},[]);
  const maxNyxWidth=Math.max(300,viewport-(viewport>1000?(navFolded?64:204)+360:16));
  const panelWidth=Math.min(nyxWidth,maxNyxWidth);
  function toggleNyx(){if(viewport>1000)setNyxFolded(!nyxFolded);else setRail(!rail);}
  function closeNyx(){setNyxFolded(true);setRail(false);}
  const [ontologySection,setOntologySection]=useState("resources");
  const detailRequest = useRef(0); const searchRef = useRef<HTMLInputElement>(null); const workRef = useRef<HTMLDivElement>(null);
  const canOntology = principal.permissions.includes("ontology_read");
  const refresh = useCallback(() => setRevision(value => value+1),[]);
  useEffect(()=>{
    const check=()=>{if(document.visibilityState==="visible")refresh();};
    const interval=window.setInterval(check,60_000);
    document.addEventListener("visibilitychange",check);
    return()=>{window.clearInterval(interval);document.removeEventListener("visibilitychange",check);};
  },[refresh]);
  useEffect(() => {
    const controller = new AbortController(); let cancelled = false;
    async function load() {
      setLoading(true);
      async function read<T>(path:string, key:keyof Snapshot): Promise<Loadable<T>> {
        let result:Loadable<T>;
        try {result={data:await get<T>(path,token,controller.signal),error:null};}
        catch(error){result={data:null,error:error instanceof Error?error.message:"Unavailable"};}
        if(!cancelled)setSnapshot(previous=>({...previous,[key]:result}));
        return result;
      }
      const noAccess = Promise.resolve({data:null,error:"Your identity does not include ontology access."});
      async function loadCompanies(): Promise<Loadable<CanonicalResource[]>> {
        try {const index=await get<CompanyIndex>("ontology/company-context",token,controller.signal);
          const rows=[...new Map([...index.workspaces.map(w=>w.company),...index.source_companies,...(index.reported_groups??[]).flatMap(g=>[g.reporter,...g.members.map(m=>m.company)])].map(c=>[c.resource_id,c])).values()];
          if(!cancelled){setCompanyIndex(index);setCompanyDirectory({data:rows,error:null});}
          return {data:rows,error:null};
        }catch(error){const result={data:null,error:error instanceof Error?error.message:"Company context unavailable"};if(!cancelled)setCompanyDirectory(result);return result;}
      }
      const [summary,evidence,graph,proposals,context,readiness,directory] = await Promise.all([
        read<NonNullable<Snapshot["summary"]["data"]>>("workspace/summary","summary"),read<NonNullable<Snapshot["evidence"]["data"]>>("workspace/intake","evidence"),
        canOntology ? read<NonNullable<Snapshot["graph"]["data"]>>("ontology/graph","graph") : noAccess,
        canOntology ? read<NonNullable<Snapshot["proposals"]["data"]>>("ontology/proposals","proposals") : noAccess,
        canOntology ? read<NonNullable<Snapshot["context"]["data"]>>("ontology/context","context") : noAccess,
        read<NonNullable<Snapshot["readiness"]["data"]>>("readiness","readiness"),canOntology?loadCompanies():noAccess]);
      if (!cancelled) {setCompanyDirectory(directory);setSnapshot({summary,evidence,graph,proposals,context,readiness});setUpdated(new Date().toLocaleTimeString(undefined,{hour:"2-digit",minute:"2-digit"}));setLoading(false);}
    }
    void load(); return () => {cancelled=true;controller.abort();};
  },[token,canOntology,revision]);
  useEffect(() => {
    function shortcut(event:KeyboardEvent) {if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {event.preventDefault();searchRef.current?.focus();} if(event.key === "Escape") {setSearch("");setMenu(false);setRail(false);}}
    document.addEventListener("keydown",shortcut); return () => document.removeEventListener("keydown",shortcut);
  },[]);
  const resources = snapshot.graph.data?.resources ?? [];
  const companies = [...(companyDirectory.data??[]),...(exploredCompany && !(companyDirectory.data??[]).some(c=>c.resource_id===exploredCompany.resource_id)?[exploredCompany]:[])];
  // Canonical company context is resolved separately from legacy credential-bound intake receipts.
  const company = companies.find(item => item.resource_id === companyId);
  const contextCompanyId = snapshot.context.data?.canonical_references.legal_entity_id?.resource_id;
  const currentCompany = company;
  const selectedCompanyId=companyId;
  useEffect(()=>{
    const controller=new AbortController();
    if(!selectedCompanyId)return ()=>controller.abort();
    void get<{context:ResolvedCompanyContext}>(`ontology/company-context?company_id=${selectedCompanyId}`,token,controller.signal).then(result=>{if(!controller.signal.aborted){setResolvedCompany(result.context);setCompanyContextError("");}}).catch(error=>{if(!controller.signal.aborted){setResolvedCompany(null);setCompanyContextError(String(error));}});
    return ()=>controller.abort();
  },[selectedCompanyId,token,revision]);
  const resolvedContext=resolvedCompany?.company.resource_id===selectedCompanyId?resolvedCompany:null;
  const [recentResources,setRecentResources]=useState<{key:string;data:HistorySearchResult|null;error:string}|null>(null);
  const recentKey=JSON.stringify([token,selectedCompanyId,revision]);
  const recent=recentResources?.key===recentKey?recentResources:null;
  useEffect(()=>{
    if(view!=="home"||!selectedCompanyId)return;
    const controller=new AbortController();let disposed=false;
    const timer=setTimeout(()=>controller.abort(),20_000);
    const params=new URLSearchParams({company_id:selectedCompanyId,sort:"recorded_desc",limit:"12"});
    void get<HistorySearchResult>(`ontology/history-search?${params}`,token,controller.signal)
      .then(data=>{if(!disposed&&!controller.signal.aborted)setRecentResources({key:recentKey,data,error:""});})
      .catch(error=>{if(!disposed)setRecentResources({key:recentKey,data:null,error:controller.signal.aborted?"Recent company resources timed out.":error instanceof Error?error.message:"Recent resources unavailable"});})
      .finally(()=>clearTimeout(timer));
    return()=>{disposed=true;clearTimeout(timer);controller.abort();};
  },[view,selectedCompanyId,token,recentKey]);

  const companyDocumentIds=resolvedContext?[...new Set([
    ...resolvedContext.accounting_sources.map(row=>String(row.scope.attributes.document_id)),
    ...resolvedContext.disclosures.map(row=>String(row.observation.attributes.document_id)),
    ...resolvedContext.licence_evidence.flatMap(row=>row.notice?[String(row.notice.attributes.document_id)]:[]),
  ])]:[];
  const companyMismatch = !!selectedCompanyId && selectedCompanyId !== contextCompanyId;
  const scopedEvidence = companyMismatch ? [] : snapshot.evidence.data ?? [];
  const scopedProposals = (snapshot.proposals.data ?? []).filter(item => !currentCompany || item.access_entity === currentCompany.access_entity || item.access_entity === "__PLATFORM__");
  const items = workItems(scopedEvidence,scopedProposals);
  const pending = items.filter(item => item.state === "PENDING");
  const query = search.trim().toLocaleLowerCase();
  const visibleResources = resources.filter(item => !["SchemaDefinition","SemanticContract","LinkType"].includes(item.object_type))
    .filter(item => !selectedCompanyId || belongsToCompany(item,selectedCompanyId));
  const results = query ? [...[...new Map(companies.map(item=>[item.resource_id,item])).values()].filter(item => item.display_name.toLocaleLowerCase().includes(query)).map(item => ({id:item.resource_id,title:item.display_name,kind:readable(item.object_type),resource:item,work:null})),...items.filter(item => item.title.toLocaleLowerCase().includes(query)).map(item => ({id:item.id,title:item.title,kind:readable(item.kind),resource:null,work:item}))].slice(0,12) : [];
  const ready = snapshot.readiness.data;
  const openEngineering = (next:EngineeringView,receiptId?:string,proposalId?:string) => {setEngineering({view:next,receiptId,proposalId});setView("system");setMenu(false);};
  const navigate = (next:View) => {setView(next);setTrace(null);setMenu(false);setSearch("");};
  const clearSelection = () => {setHistory(null);setTrace(null);setMapSelection(null);detailRequest.current++;setSelected(null);setWork(null);setReceipt(null);setProposal(null);setDetailError("");setDetailBusy(false);};
  async function inspect(resource:Pick<CanonicalResource,"resource_id">, pinnedVersion?:string,knownAt?:string) {setNyxTab("context");setMapSelection(null);
    const request = ++detailRequest.current;setWork(null);setReceipt(null);setProposal(null);setSelected(null);setDetailError("");setDetailBusy(true);setRail(true);setNyxFolded(false);setSearch("");
    try {const params=new URLSearchParams({...pinnedVersion?{version_id:pinnedVersion}:{},...knownAt?{known_at:knownAt}:{}});const value=await get<OperatorInspection>(`ontology/operator/resources/${resource.resource_id}?${params}`,token);if(request===detailRequest.current)setSelected(value);}
    catch(error){if(request===detailRequest.current)setDetailError(error instanceof Error ? error.message : "Could not inspect resource");}
    finally {if(request===detailRequest.current)setDetailBusy(false);}
  }
  const inspectWork = useCallback(async (item:WorkItem, showRail=true) => {
    if(item.kind==="evidence")setSourceSelectionKey(value=>value+1);
    setMapSelection(null);const request=++detailRequest.current;setWork(item);setSelected(null);setReceipt(null);setProposal(null);setDetailError("");setDetailBusy(true);if(showRail){setRail(true);setNyxFolded(false);}setSearch("");
    try {if(item.kind === "evidence") {const value=await get<ReceiptDetail>(`workspace/constructions/${item.id}`,token);if(request===detailRequest.current)setReceipt(value);}else {const value=await get<ResourceProposalDetail>(`ontology/proposals/${item.id}`,token);if(request===detailRequest.current)setProposal(value);}}
    catch(error){if(request===detailRequest.current)setDetailError(error instanceof Error ? error.message : "Could not inspect work");}
    finally {if(request===detailRequest.current)setDetailBusy(false);}
  },[token]);
  const inspectSource = useCallback((source:IntakeItem) => {void inspectWork(workItems([source],[])[0],false);},[inspectWork]);
  const selectMap = (selection:MapSelection|null) => {clearSelection();setMapSelection(selection);if(selection){setNyxTab("context");setNyxFolded(false);setRail(true);}};
  const mapProps={token,selection:mapSelection,companyId:currentCompany?.resource_id,canPropose:principal.permissions.includes("ontology_propose"),state:mapState,onState:setMapState,onSelect:selectMap,onReview:(id:string)=>openEngineering("ontology",undefined,id)};
  const workTable = <WorkQueue items={items} filter={workFilter} onFilter={setWorkFilter} onInspect={item=>{void inspectWork(item);setNyxTab("context");}} onHistory={()=>openEngineering("history")} loading={loading} errors={[snapshot.evidence.error?`Evidence queue unavailable: ${snapshot.evidence.error}`:"",snapshot.proposals.error?`Change queue unavailable: ${snapshot.proposals.error}`:""].filter(Boolean)} scope={companyMismatch?"Company exploration; unbound source evidence excluded":"Current authorized scope"}/>;
  return <div className={`g8-app ${menu ? "menu-open" : ""} ${rail ? "rail-open" : ""} ${navFolded ? "nav-folded" : ""} ${nyxFolded ? "nyx-folded" : ""}`} style={{"--nyx-width":`${panelWidth}px`} as CSSProperties}><a className="g8-skip" href="#g8-main">Skip to workspace</a>
    <aside className="g8-sidebar"><div className="g8-nav-brand"><Brand /><button className="g8-icon fold-navigation" aria-label={navFolded?"Expand navigation":"Collapse navigation"} aria-expanded={!navFolded} onClick={()=>setNavFolded(!navFolded)}><SidebarSimple size={18}/></button></div><p className="g8-tagline">Enterprise Intelligence</p><nav aria-label="Business navigation">{navigation.map(({id,label,hint,icon:Icon,available})=><button disabled={!available} title={available?label:`${label}: not connected yet`} aria-label={available?label:`${label} — not connected`} aria-current={view===id ? "page" : undefined} className={view===id ? "active" : ""} onClick={()=>navigate(id as View)} key={id}><Icon size={21} weight="regular"/><span>{label}{hint && <small>{hint}</small>}</span></button>)}</nav><div className="g8-nav-bottom"><button aria-label="System / Engineering" title="System / Engineering" className={`g8-system ${view === "system" ? "active" : ""}`} onClick={()=>navigate("system")}><GearSix size={21}/><span>System<small>Engineering access</small></span><CaretRight size={13}/></button><div className="g8-platform"><ShieldCheck size={20}/><span>G8 Platform<small>{loading ? "Checking services…" : ready?.status === "ready" ? "Services ready" : "Readiness unavailable"}</small></span></div></div></aside>
    <header className="g8-topbar"><button className="g8-icon mobile-menu" aria-label="Toggle navigation" onClick={()=>setMenu(!menu)}><List size={21}/></button><div className="g8-search"><MagnifyingGlass size={19}/><input ref={searchRef} aria-label="Search workspace" maxLength={200} placeholder="Search company resources, identities and work…" value={search} onChange={event=>setSearch(event.target.value)}/><kbd>Ctrl K</kbd>{query && <div className="g8-search-results" role="region" aria-label="Search results"><WorkspaceSearchResults key={companyId} token={token} companyId={companyId} companyName={currentCompany?displayName(currentCompany.display_name):""} query={search} onInspect={(resource,knownAt)=>void inspect(resource,resource.version_id,knownAt)} onClose={()=>setSearch("")}/><small>Companies & loaded work</small>{results.map(result=><button key={result.id} onClick={()=>result.resource ? void inspect(result.resource) : result.work && void inspectWork(result.work)}><span>{displayName(result.title)}<small>{result.kind}</small></span><ArrowRight size={15}/></button>)}{!results.length && <p>No matching companies or loaded work.</p>}</div>}</div>{view==="home"&&<div className="g8-header-period" title="Current authorized evidence scope"><CalendarBlank size={16}/><span>{principal.scope.period}</span><span>{principal.scope.currency}</span></div>}<button className="g8-icon" aria-label="Refresh workspace" onClick={refresh} disabled={loading}><ArrowClockwise size={19}/></button><div className="g8-user"><span>{principal.display_name.split(" ").map(part=>part[0]).slice(0,2).join("")}</span><div>{principal.display_name}<small>Governed workspace</small></div></div><button className="g8-icon" aria-label="Sign out" onClick={onSignOut}><SignOut size={19}/></button><button className="g8-icon nyx-toggle" aria-label="Toggle NYX assistant" aria-expanded={viewport>1000?!nyxFolded:rail} onClick={toggleNyx}><Image src="/brand/nyx-core-transparent.png" alt="" width={25} height={25}/></button></header>
    <main id="g8-main" className="g8-main"><div className="g8-breadcrumb">Workspace< CaretRight size={12}/>{view === "system" ? "System / Engineering" : navigation.find(area=>area.id===view)?.label}<span>{loading ? "Refreshing…" : `Updated ${updated}`}</span></div>
    <CompanyPicker index={companyIndex} selected={currentCompany} selectedId={companyId} error={companyDirectory.error} onSelect={node=>{setExploredCompany(node);setCompanyId(node?.resource_id??"");setCompanyContextError("");setResolvedCompany(null);clearSelection();}}/>
    {companyId&&!currentCompany&&companyDirectory.data&&<p role="alert">The selected company is unavailable in this directory. Choose another context; no substitute company has been selected.</p>}
    {view === "system" ? <><div className="g8-page-heading"><div><p className="overline">ADVANCED INTERNAL ACCESS</p><h1>System / Engineering</h1><p>Evidence intake, construction, registry and governed review tools.</p></div><Badge>Advanced</Badge></div><Engineering key={`${engineering.view}:${engineering.receiptId ?? ""}:${engineering.proposalId ?? ""}`} token={token} principal={principal} initialView={engineering.view} receiptId={engineering.receiptId} proposalId={engineering.proposalId}/></> : <>
      <div className={`g8-page-heading ${view==="home"?"g8-company-hero":""}`}><div><p className="overline">{view === "home" ? `Welcome, ${principal.display_name}.` : "ENTERPRISE WORKSPACE"}</p><h1>{view === "home" ? (currentCompany ? displayName(currentCompany.display_name) : undefined) ?? "Your company workspace" : view === "companies" ? "Companies" : view === "data" ? "Data & evidence" : view === "operations" ? "Operations & Maps" : view === "regulation" ? "Regulation" : view === "actions" ? "Workflows & Actions" : "Ontology"}</h1><p>{view === "home" ? "Financial reality. Operational context. Evidence-led decisions." : view === "companies" ? "Shared company identities. One connected business context." : view === "data" ? "Retained sources, review state and traceable versions." : view === "actions" ? "Investigate work, review changes and verify the resulting state." : "Explore the business resources behind your workspace."}</p></div>{view==="home"?<div className="g8-hero-status"><span><ShieldCheck size={15}/>{ready?.status==="ready"?"Workspace ready":"Checking workspace"}</span><strong>{(currentCompany ? displayName(currentCompany.display_name) : undefined)??"Set your company context"}</strong><p>{currentCompany?readable(currentCompany.evidence_class):"Connect the company behind your work."}</p><button className="g8-link" onClick={()=>navigate("companies")}>Open Companies<ArrowRight size={13}/></button></div>:<Badge tone={currentCompany ? tone(currentCompany.authority_state) : "neutral"}>{currentCompany ? readable(currentCompany.evidence_class) : "Company not selected"}</Badge>}</div>
      {snapshot.graph.data?.bounded && (view==="home"||(view==="ontology"&&ontologySection==="resources")) && <p className="g8-inline-error">Showing up to 1,000 authorized resources. This is a bounded view.</p>}

      {!trace&&<>
      {view === "home" && <><div className="g8-actionbar"><button onClick={()=>{setWorkFilter("pending");workRef.current?.scrollIntoView({behavior:"smooth"});}}><Tray size={23}/><span>Review items<small>{loading ? "Checking…" : `${pending.length} in loaded queues`}</small></span></button><button onClick={()=>{setNyxFolded(false);setRail(true);setNyxTab("interact");}}><ChartLineUp size={23}/><span>Investigate<small>Ask NYX about evidence</small></span></button>{principal.permissions.includes("ingest") && <button onClick={()=>openEngineering("intake")}><UploadSimple size={23}/><span>New data source<small>Retain source evidence</small></span></button>}<button disabled title="Reporting is not connected yet"><ChartLineUp size={23}/><span>Create report<small>Not connected</small></span></button><button disabled title="Planning is not connected yet"><GraphIcon size={23}/><span>New scenario<small>Not connected</small></span></button></div>
      <WorkspaceHealth snapshot={snapshot} loading={loading} onRefresh={refresh} onData={()=>navigate("data")}/>
      <ExecutiveOverview companyId={companyId} canonicalContext={resolvedContext} contextError={companyContextError} recentResult={recent?.data??null} recentError={recent?.error??""} onInspect={(resource,knownAt)=>void inspect(resource,resource.version_id,knownAt)} onTrace={(resource,knownAt)=>setTrace({resource_id:resource.resource_id,version_id:resource.version_id,company_id:companyId,known_at:knownAt})} onHistory={(resource,knownAt)=>setHistory({resource_id:resource.resource_id,version_id:resource.version_id,company_id:companyId,known_at:knownAt})} onRegulation={()=>navigate("regulation")} onAccounting={()=>{navigate("companies");}} operationalPanel={<OperationsMap key={currentCompany?.resource_id??"scope"} {...mapProps} compact onOpen={()=>navigate("operations")}/>} company={(currentCompany ? displayName(currentCompany.display_name) : undefined)??"Select company"} period={principal.scope.period} currency={principal.scope.currency} resources={visibleResources} resourcesAvailable={!loading && !!snapshot.graph.data} onData={()=>navigate("data")} onCompanies={()=>navigate("companies")} onOntology={()=>navigate("ontology")}/>
      <div className="g8-home-bottom"><div ref={workRef}><Panel title="My work" aside={<Badge>{loading?"Checking":`${pending.length} awaiting review`}</Badge>}>{workTable}</Panel></div><Panel title="Recent review activity" aside={<button className="g8-link" onClick={()=>{setWorkFilter("all");workRef.current?.scrollIntoView({behavior:"smooth"});}}>View all</button>}>{[...items].sort((a,b)=>b.date.localeCompare(a.date)).slice(0,5).map(item=><Signal key={`${item.kind}:${item.id}`} title={item.title} detail={`${readable(item.state)} · ${date(item.date)} · ${item.reason}`} tone={item.state==="APPROVED"?"good":item.state==="REJECTED"?"bad":"warning"} onClick={()=>{void inspectWork(item);setNyxTab("context");}}/>)}{!items.length&&<Empty title={loading?"Loading review activity…":"No retained review activity"}>Source receipts and proposal decisions appear here.</Empty>}</Panel></div></>}
      {view === "actions" && <ActionWorkbench key={`${companyId}:${actionTarget?.companyId===companyId?actionTarget.workflowId:"saved"}`} initialWorkflowId={actionTarget?.companyId===companyId?actionTarget.workflowId:undefined} token={token} principal={principal} companyId={companyId} onInspect={id=>void inspect({resource_id:id})}/>}
      {view === "regulation" && <RegulationWorkspace key={companyId} viewStateKey={`${contextKey}:regulation:${companyId}`} token={token} companyId={companyId} onInspect={node=>void inspect(node,node.version_id)} onTrace={node=>setTrace({resource_id:node.resource_id,version_id:node.version_id,company_id:companyId})} onHistory={node=>setHistory({resource_id:node.resource_id,version_id:node.version_id,company_id:companyId})} onWorkflow={workflowId=>{setActionTarget({workflowId,companyId});navigate("actions");}} onProposal={id => openEngineering("ontology", undefined, id)} />}
      {view === "operations" && <OperationsMap key={currentCompany?.resource_id??"scope"} {...mapProps}/>}
      {view === "ontology" && <><nav className="g8-module-tabs" aria-label="Ontology views">{[["resources","Business resources"],["sets","Object sets & definitions"],["accounting","Accounting contracts"]].map(([id,title])=><button key={id} aria-pressed={ontologySection===id} onClick={()=>setOntologySection(id)}>{title}</button>)}</nav>{ontologySection!=="resources"&&<p className="g8-subtle">Shared ontology definitions and queries cover your authorized scope. Company filtering is specified in each query or contract.</p>}</>}
      {view === "ontology" && ontologySection==="accounting" && <AccountingFacts key={`${companyId}:${selected?.resource.version_id??"analysis"}`} token={token} authorityConsumer={typeof selected?.resource.attributes.minimum_authority_state==="string"?selected.resource:undefined} onTrace={reference=>setTrace({...reference,company_id:companyId})} />}
      {view === "ontology" && ontologySection==="sets" && <ObjectSets key={companyId} token={token} viewStateKey={`${contextKey}:object-sets:${companyId}`} onInspect={(node,context)=>void inspect(node,node.version_id,context.known_at)} onHistory={(node,context)=>setHistory({resource_id:node.resource_id,version_id:node.version_id,company_id:companyId,known_at:context.known_at})} onTrace={(node,context)=>setTrace({resource_id:node.resource_id,version_id:node.version_id,company_id:companyId,known_at:context.known_at})} onProposal={id => openEngineering("ontology", undefined, id)} />}
      {companyContextError&&<p role="alert">Company context: {companyContextError}</p>}

      {view === "companies" && <>{companyDirectory.error&&<p role="alert">{companyDirectory.error}</p>}<CompanyWorkspace key={`${token}:${currentCompany?.resource_id??"none"}`} token={token} index={companyIndex} viewStateKey={`${contextKey}:companies:${currentCompany?.resource_id??"none"}`} companyId={currentCompany?.resource_id??""} onSelect={node=>{setExploredCompany(node);setCompanyId(node.resource_id);clearSelection();}} onInspect={node=>void inspect(node,node.version_id)} onHistory={node=>setHistory({resource_id:node.resource_id,version_id:node.version_id,company_id:companyId})} onTrace={node=>setTrace({resource_id:node.resource_id,version_id:node.version_id,company_id:companyId})} onNavigate={destination=>{if(destination==="finance"){navigate("ontology");setOntologySection("accounting");}else navigate(destination==="workflows"?"actions":destination);}}/></>}
      {view === "data" && <DataWorkspace sourceSelectionKey={sourceSelectionKey} key={`${contextKey}:${companyId}`} initialSourceId={work?.kind==="evidence"?work.id:undefined} companyName={currentCompany?displayName(currentCompany.display_name):"All authorized contexts"} viewStateKey={`${contextKey}:data:${companyId}`} history={<HistoryExplorer key={`${contextKey}:${companyId}`} token={token} companyId={companyId} companyName={currentCompany?displayName(currentCompany.display_name):""} contextKey={contextKey} onInspect={(resource,knownAt)=>void inspect(resource,resource.version_id,knownAt)} onHistory={(resource,knownAt)=>{setHistory({resource_id:resource.resource_id,version_id:resource.version_id,company_id:companyId,known_at:knownAt});void inspect(resource,resource.version_id,knownAt);}} onTrace={(resource,knownAt)=>setTrace({resource_id:resource.resource_id,version_id:resource.version_id,company_id:companyId,known_at:knownAt})}/>} documents={<>{selectedCompanyId&&!resolvedContext?<p role="status">{companyContextError?"Company sources unavailable.":"Resolving company sources…"}</p>:<SourceDocuments key={selectedCompanyId||"all"} companyDocumentIds={selectedCompanyId?companyDocumentIds:undefined} token={token} principal={principal} onProposal={id=>openEngineering("ontology",undefined,id)} />}</>} sources={<>{snapshot.evidence.error ? <Empty title="Source inventory unavailable">{snapshot.evidence.error}</Empty> : <SourceExplorer key={currentCompany?.resource_id ?? "scope"} token={token} principal={principal} sources={scopedEvidence} companyId={currentCompany?.resource_id} onInspectResource={reference=>void inspect(reference,reference.version_id)} onTraceResource={reference=>setTrace({...reference,company_id:companyId})} onProposal={id=>openEngineering("ontology",undefined,id)} onSelect={inspectSource} initialReceiptId={work?.kind === "evidence" ? work.id : undefined} onReview={id=>openEngineering("history",id)}/>}</>} onIntake={()=>openEngineering("intake")}/> }
      {view === "ontology" && ontologySection==="resources" && <Panel title="Business resources" aside={<Badge>{visibleResources.length} in view</Badge>}>{snapshot.graph.error ? <Empty title="Ontology unavailable">{snapshot.graph.error}</Empty> : !visibleResources.length ? <Empty title={loading ? "Loading business resources…" : "No accepted resources in this context"}>Accepted companies, accounts, relationships and other business resources will appear here with their authority and evidence.</Empty> : <div className="g8-table-scroll"><table><thead><tr><th>Resource</th><th>Type</th><th>Authority</th><th>Evidence</th><th>Effective</th></tr></thead><tbody>{visibleResources.map(item=><tr key={item.resource_id}><td><button className="g8-link" onClick={()=>void inspect(item)}>{displayName(item.display_name)}</button></td><td>{readable(item.object_type)}</td><td><Badge tone={tone(item.authority_state)}>{item.authority_state}</Badge></td><td>{readable(item.evidence_class)}</td><td>{date(item.valid_from)}</td></tr>)}</tbody></table></div>}<div className="g8-panel-foot">Accepted business context · current effective versions<button className="g8-link" onClick={()=>openEngineering("ontology")}>Open governance tools<ArrowRight size={13}/></button></div></Panel>}
      </>}
      {history&&<OperatorHistory key={`${history.resource_id}:${history.known_at??"current"}`} token={token} selection={history} onClose={()=>setHistory(null)} onSelect={(version,knownAt)=>{setHistory({...history,version_id:version.version_id,known_at:knownAt});void inspect(version,version.version_id,knownAt);}} onTrace={(version,knownAt)=>setTrace({resource_id:version.resource_id,version_id:version.version_id,company_id:companyId,known_at:knownAt})} onInspect={(id,knownAt)=>void inspect({resource_id:id},undefined,knownAt)}/>}
      {trace&&<OperatorTrace key={`${trace.resource_id}:${trace.version_id}:${trace.known_at??"current"}`} token={token} root={trace} onClose={()=>setTrace(null)} onInspect={(node,knownAt)=>void inspect(node,node.version_id,knownAt)}/>}
      <footer className="g8-footer"><span><ShieldCheck size={13}/> Governed evidence · explicit authority</span><span>{snapshot.context.data?.binding ? "Company binding available" : "No confirmed company binding"}</span></footer></>}
    </main>
    <aside className="g8-analyst" aria-label="NYX analyst context"><div className="nyx-resize" role="separator" aria-label="Resize NYX workspace" aria-orientation="vertical" aria-valuemin={300} aria-valuemax={maxNyxWidth} aria-valuenow={Math.round(panelWidth)} tabIndex={0} onDoubleClick={()=>setNyxWidth(panelWidth>450?340:Math.min(maxNyxWidth,Math.round(viewport*.52)))} onKeyDown={event=>{if(["ArrowLeft","ArrowRight","Home","End"].includes(event.key)){event.preventDefault();setNyxWidth(event.key==="Home"?300:event.key==="End"?maxNyxWidth:Math.max(300,Math.min(maxNyxWidth,panelWidth+(event.key==="ArrowLeft"?40:-40))));}}} onPointerDown={event=>{drag.current={x:event.clientX,width:panelWidth};event.currentTarget.setPointerCapture(event.pointerId);}} onPointerMove={event=>{if(drag.current)setNyxWidth(Math.max(300,Math.min(maxNyxWidth,drag.current.width+drag.current.x-event.clientX)));}} onPointerUp={event=>{drag.current=null;event.currentTarget.releasePointerCapture(event.pointerId);}} onPointerCancel={()=>{drag.current=null;}}/><header><Image src="/brand/nyx-core-transparent.png" alt="NYX Core" width={52} height={52}/><div><h2>NYX</h2><small>Context & evidence</small></div><button className="g8-icon nyx-expand" aria-label={panelWidth>450?"Restore NYX width":"Expand NYX workspace"} onClick={()=>setNyxWidth(panelWidth>450?340:Math.min(maxNyxWidth,Math.round(viewport*.52)))}><ArrowsOutSimple size={18}/></button><button className="g8-icon" aria-label="Close NYX context" onClick={closeNyx}><X size={17}/></button></header><div className="nyx-tabs" aria-label="NYX workspace views">{["context","interact","data"].map(id=><button key={id} aria-pressed={nyxTab===id} onClick={()=>setNyxTab(id)}>{id==="interact"?"Ask NYX":id==="data"?"Data workspace":"Context"}</button>)}</div><div className="g8-analyst-body"><div hidden={nyxTab!=="interact"}><NyxInteraction mapSelection={mapSelection} key={currentCompany?.resource_id??"scope"} items={items} work={work} context={`${(currentCompany ? displayName(currentCompany.display_name) : undefined)??"Sign-in scope"} · ${principal.scope.period} · ${principal.scope.currency}`} blockers={receipt?.approval_blockers??[]} availability={loading?"Workspace is refreshing; this answer uses the last loaded snapshot.":[snapshot.evidence.error,snapshot.proposals.error].filter(Boolean).length?"Some work queues are unavailable; this answer is incomplete.":""} onInspect={item=>{void inspectWork(item);setNyxTab("context");}} onData={()=>{setNyxTab("data");setNyxWidth(Math.min(maxNyxWidth,Math.round(viewport*.52)));}} onWork={()=>navigate("home")}/></div>{nyxTab==="data"&&<SourceExplorer key={currentCompany?.resource_id??"rail"} token={token} principal={principal} sources={scopedEvidence} companyId={currentCompany?.resource_id} onInspectResource={reference=>void inspect(reference,reference.version_id)} onTraceResource={reference=>setTrace({...reference,company_id:companyId})} onProposal={id=>openEngineering("ontology",undefined,id)} onSelect={inspectSource} initialReceiptId={work?.kind==="evidence"?work.id:undefined} onReview={id=>openEngineering("history",id)}/>}<div hidden={nyxTab!=="context"}><Badge>Governed context · AI reasoning not connected</Badge><p className="g8-analyst-intro">Your enterprise context, with the evidence always in reach.</p><div className="g8-context-note"><small>WORKING CONTEXT</small><strong>{(currentCompany ? displayName(currentCompany.display_name) : undefined) ?? "No company selected"}</strong><span>{currentCompany ? readable(currentCompany.evidence_class) : "Select an accepted company to explore its resources."}</span></div>{detailBusy && <p role="status">Loading evidence and impact…</p>}{detailError && <p className="g8-inline-error" role="alert">{detailError}</p>}
      {mapSelection&&<div className="g8-inspector"><p className="overline">MAP SNAPSHOT CONTEXT</p><h3>{displayName(mapSelection.resource.display_name)}</h3><Badge>{readable(mapSelection.resource.authority_state)}</Badge><p>{readable(mapSelection.resource.object_type)} · {readable(mapSelection.resource.evidence_class)}</p><dl><dt>Effective snapshot</dt><dd>{new Date(mapSelection.validAt).toLocaleString()}</dd><dt>Known snapshot</dt><dd>{new Date(mapSelection.knownAt).toLocaleString()}</dd></dl><p>Geography is recorded context. Operating condition and impact predictions are not connected.</p><details><summary>Recorded properties & version</summary><dl>{Object.entries(mapSelection.resource.attributes).filter(([key])=>key!=="geometry").map(([key,value])=><div key={key}><dt>{readable(key)}</dt><dd>{typeof value==="object"?JSON.stringify(value):String(value)}</dd></div>)}</dl><small>{mapSelection.resource.version_id}</small></details><button className="g8-panel-action" onClick={()=>navigate("operations")}>Inspect recorded connections<ArrowRight size={15}/></button><button className="g8-link" onClick={clearSelection}>Clear selection</button></div>}
      {selected && <div className="g8-inspector"><p className="overline">RESOURCE CONTEXT</p><h3>{displayName(selected.resource.display_name)}</h3><Badge tone={tone(selected.resource.authority_state)}>{selected.resource.authority_state}</Badge><p>{readable(selected.resource.object_type)} · {readable(selected.resource.evidence_class)}</p><button onClick={()=>setTrace({resource_id:selected.resource.resource_id,version_id:selected.resource.version_id,company_id:companyId,known_at:selected.known_at})}>Show system trace</button><button onClick={()=>setHistory({resource_id:selected.resource.resource_id,version_id:selected.resource.version_id,company_id:companyId,known_at:selected.known_at})}>View history & compare</button><ResourceAuthority key={selected.resource.version_id} token={token} resource={selected.resource} knownAt={selected.known_at}/>{typeof selected.resource.attributes.minimum_authority_state==="string"&&<button onClick={()=>{navigate("ontology");setOntologySection("accounting");}}>Calculate with this authority contract</button>}<dl><dt>Effective from</dt><dd>{date(selected.resource.valid_from)}</dd><dt>Known by G8 at</dt><dd>{new Date(selected.known_at).toLocaleString()}</dd><dt>Versions known then</dt><dd>{selected.versions.length}{selected.versions_truncated?"+ (bounded)":""}</dd><dt>Visible dependents</dt><dd>{selected.dependents.length}{selected.dependents_truncated?"+ (bounded)":""}</dd></dl>{selected.dependents.slice(0,8).map(item=><button className="g8-panel-action" key={`${item.version_id}:${item.relation}`} onClick={()=>void inspect({resource_id:item.resource_id},item.version_id,selected.known_at)}>{displayName(item.display_name)}<ArrowRight size={13}/></button>)}<details><summary>Identity & version</summary><small>{selected.resource.resource_id}<br/>{selected.resource.version_id}</small></details><button className="g8-link" onClick={clearSelection}>Clear selection</button></div>}
      {work && items.find(item=>item.id===work.id&&item.kind===work.kind)?.state!==work.state&&<p className="g8-inline-error">The selected work snapshot differs from the latest queue, or is no longer listed. <button className="g8-link" onClick={()=>void inspectWork(items.find(item=>item.id===work.id&&item.kind===work.kind)??work)}>Reload selected evidence</button></p>}
      {work && <div className="g8-inspector"><p className="overline">WHY THIS NEEDS ATTENTION</p><h3>{work.title}</h3><Badge tone={tone(work.state)}>{work.state}</Badge><p>{work.reason}</p>{receipt && <><h3>Review eligibility</h3>{receipt.approval_blockers.length ? receipt.approval_blockers.map(reason=><p className="g8-inline-error" key={reason}>{reason}</p>) : <p>No approval blockers reported. Independent review remains required.</p>}<h3>Proposed object impact</h3><dl>{Object.entries(receipt.impact).map(([key,value])=><div key={key}><dt>{readable(key)}</dt><dd>{value}</dd></div>)}</dl><button className="g8-panel-action" onClick={()=>openEngineering("history",work.id)}>Open evidence & review<ArrowRight size={15}/></button></>}{proposal && <><PromotionReadiness key={proposal.proposal.proposal_id} token={token} proposalId={proposal.proposal.proposal_id} onDecision={detail=>{setProposal(detail);setWork(current=>current?.id===detail.proposal.proposal_id?{...current,state:detail.decision??current.state}:current);refresh();}}/><ProposalImpact validation={proposal.validation}/><button className="g8-panel-action" onClick={()=>openEngineering("ontology",undefined,work.id)}>Open governed change review<ArrowRight size={15}/></button></>}<button className="g8-link" onClick={clearSelection}>Clear selection</button></div>}
      {!work && !selected && !mapSelection && !detailBusy && <><p>{resolvedContext?`Accounting context: ${resolvedContext.accounting_state.replaceAll("_"," ")} · ${resolvedContext.accounting_sources.length} source scopes · ${resolvedContext.dimensions.length} analytical dimensions`:"Select a company to resolve its canonical context."}</p><h3>What needs attention?</h3><p className="g8-subtle">Open a work item to see its reason, source evidence and available review path.</p><button className="g8-panel-action" onClick={()=>{navigate("home");setWorkFilter("pending");}}>Review current work<ArrowRight size={15}/></button><button className="g8-panel-action" onClick={()=>navigate("data")}>Trace source evidence<ArrowRight size={15}/></button><button className="g8-panel-action" onClick={()=>navigate("companies")}>Explore companies<ArrowRight size={15}/></button></>}
      </div></div><footer><ShieldCheck size={17}/><p>Only governed context is shown here. Natural-language analysis is not connected.</p></footer></aside>
  </div>;
}
