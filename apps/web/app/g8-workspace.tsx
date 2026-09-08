"use client";
import {sourceReviewForSession,type SourceReviewContext} from "./source-review-context";
import SourceReviewContextPanel from "./source-review-context-panel";
import SemanticAnalysisWorkspace from "./semantic-analysis-workspace";
import {usePathname} from "next/navigation";
import {SourceReviewNavigation,sourceReviewPath,sourceReviewTarget,sourceReviewUrl,type SourceReviewTarget} from "./source-review-navigation";
import {sourceReviewRouteRefused} from "./source-review-route";
import {parseView} from "./semantic-analysis-state";
import {parseSourceReviewOrigin,type SourceReviewOrigin} from "./source-review-origin";
import {displayName} from "./display-name";
import AccountDimensionPolicyWorkbench from "./account-dimension-policy-workbench";
import CompanyPicker from "./company-picker";
import WorkspaceSearchResults from "./workspace-search-results";

import { useCallback, useEffect, useRef, useState, type FormEvent, type CSSProperties } from "react";
import dynamic from "next/dynamic";
import Image from "next/image";
import { House, Buildings, Database, Graph as GraphIcon, GearSix, MagnifyingGlass, ArrowRight, ArrowClockwise, SignOut, ShieldCheck, Tray, UploadSimple, List, X, CaretRight, SidebarSimple, ArrowsOutSimple, ChartLineUp, ChartBar, Notebook, MapTrifold, Scales, FlowArrow } from "@phosphor-icons/react";
import type { ProposalQueuePage, OperatorInspection, HistorySearchResult, CanonicalResource, IntakeItem, Principal, ReceiptDetail, ResourceProposalDetail } from "@finai/contracts";
import type { EngineeringView } from "./operator-workspace";
import { Badge, Brand, Empty, Panel, Signal } from "./g8-ui";
import { belongsToCompany, emptySnapshot, readable, workItems, type Loadable, type Snapshot, type WorkItem } from "./g8-model";
import ProposalImpact from "./proposal-impact";
import PromotionReadiness from "./promotion-readiness";
import BuildsWorkbench from "./builds-workbench";
import SavedAnalysisWorkbench from "./saved-analysis-workbench";
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
import CompanyHome from "./company-home";
import {companyNyxCaption,companyNyxForSurface,type CompanyNyxContext,type CompanyNyxReadback} from "./company-nyx-context";
import CompanyNyxContextPanel from "./company-nyx-context-panel";
import {accountingEntryForSession,type CompanyAccountingEntry,type CompanyAccountingHandoff} from "./company-accounting-handoff";
import FinanceAnalysis from "./finance-analysis";
import type {FinanceReportReference} from "./finance-report-reference";
import FinanceWorkspace from "./finance-workspace";
import AccountingFacts from "./accounting-facts";
import RegulationWorkspace from "./regulation-workspace";
import {regulationEntryForSession,type CompanyRegulationEntry,type CompanyRegulationHandoff} from "./company-regulation-handoff";
import {restorationInstant} from "./definition-restoration-time";
import type {TraceSelection,TraceContextChange} from "./operator-trace";
import type {HistorySelection} from "./history-model";
const HistoryExplorer = dynamic(()=>import("./history-explorer"));
const ActionWorkbench = dynamic(()=>import("./action-workbench"));
const RuntimeStateWorkbench = dynamic(()=>import("./runtime-state-workbench"));
const OperatorHistory = dynamic(()=>import("./operator-history"));
const OperatorTrace = dynamic(()=>import("./operator-trace"));

const Engineering = dynamic(() => import("./operator-workspace"), {loading:() => <p role="status">Opening engineering tools…</p>});
type View = "finance" | "home" | "companies" | "data" | "ontology" | "system" | "operations" | "regulation" | "actions";
const areas = [{id:"home",label:"Home",hint:"My work",icon:House},{id:"companies",label:"Companies",hint:undefined,icon:Buildings},{id:"data",label:"Data",hint:undefined,icon:Database},{id:"ontology",label:"Ontology",hint:undefined,icon:GraphIcon}] as const;
const navigation = [
 {...areas[0],available:true},{...areas[1],available:true},
 {id:"finance",label:"Finance",hint:undefined,icon:ChartLineUp,available:true},
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
  const pathname=usePathname();
  const [session,setSession] = useState<{token:string;principal:Principal} | null>(null);
  const [error,setError] = useState(""); const [busy,setBusy] = useState(false);
  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const token = String(new FormData(event.currentTarget).get("token") ?? "").trim();
    try {const principal = await get<Principal>("workspace/session",token); setSession({token,principal});}
    catch (failure) {setError(failure instanceof Error ? failure.message : "Sign-in unavailable");}
    finally {setBusy(false);}
  }
  if(sourceReviewRouteRefused(pathname))return <main id="g8-main"><section role="alert" aria-label="Source review reference refused"><Brand/><h1>Source review reference unavailable</h1><p>This link does not identify a valid company, retained result and, where required, an exact journal snapshot. No saved company or result has been substituted.</p><button onClick={()=>{const url=new URL(location.href);url.pathname="/";url.searchParams.delete("analysis_view");window.history.pushState(null,"",url);}}>Return to workspace</button></section></main>;
  if (session) return <SignedIn key={session.principal.actor_id} {...session} onSignOut={() => setSession(null)} />;
  return <main className="g8-login"><section className="g8-login-story"><Brand /><div><p className="overline">ENTERPRISE INTELLIGENCE</p><h1>From source evidence<br />to reviewed enterprise state.</h1><p>One workspace for your companies, retained sources and governed decisions.</p><div className="g8-principles"><span>Exact context<small>Company and version stay bound.</small></span><span>Visible evidence<small>Trace every accepted change.</small></span><span>Controlled action<small>Independent review is preserved.</small></span></div></div><Image className="g8-brand-banner" src="/brand/g8-login-art.png" alt="G8 cognition emblem with connected data ribbons" width={2172} height={724} priority /></section><section className="g8-login-form"><form onSubmit={signIn}><ShieldCheck size={30} /><p className="overline">G8 WORKSPACE ACCESS</p><h2>Sign in to your workspace</h2><p>Your identity determines the company access, evidence and actions available to you.</p><label>Workspace access key<input name="token" type="password" required autoComplete="off" autoFocus /></label><button disabled={busy}>{busy ? "Connecting…" : "Continue securely"}<ArrowRight size={18} /></button>{error && <p role="alert" className="error-banner">{error}</p>}<small>Use your organization-issued access key. It stays in memory for this session.</small></form></section></main>;
}

function SignedIn({token,principal,onSignOut}: {token:string;principal:Principal;onSignOut:()=>void}) {
  const pathname=usePathname();
  const routeTarget=sourceReviewTarget(pathname);
  const [linkedAnalysis]=useState(()=>{try{if(location.pathname!=="/")return null;const raw=new URL(location.href).searchParams.get("analysis_view");return raw?parseView(raw,JSON.parse(raw).request.company_id):null;}catch{return null;}});
  const analysisTarget=routeTarget;
  const sourceReview=Boolean(analysisTarget);
  const [sourceReadback,setSourceReadback]=useState<{sessionKey:string;context:SourceReviewContext}|null>(null);
  const onSourceContext=useCallback((value:SourceReviewContext)=>setSourceReadback({sessionKey:token,context:value}),[token,setSourceReadback]);
  const sourceContext=sourceReviewForSession(sourceReadback,token,analysisTarget);
  const [originSession]=useState(()=>crypto.randomUUID());
  const [reviewOrigin,setReviewOrigin]=useState<SourceReviewOrigin|null>(null);
  const originElements=useRef(new Map<string,{origin:SourceReviewOrigin;focus:HTMLElement|null;scrolls:Array<{element:HTMLElement;top:number;left:number}>}>());
  const pendingOrigin=useRef<SourceReviewOrigin|null>(null);
  const businessSurface=useRef<HTMLDivElement>(null);
  const legacyOpened=useRef(false);
  useEffect(()=>{if(!legacyOpened.current&&linkedAnalysis&&pathname==="/"){legacyOpened.current=true;const url=new URL(location.href);url.pathname=sourceReviewPath({companyId:linkedAnalysis.request.company_id,invocationId:linkedAnalysis.request.invocation_id});window.history.replaceState(null,"",url);}},[pathname,linkedAnalysis]);
  const contextKey=`g8-work-context:${principal.actor_id}:${JSON.stringify(principal.scope)}`;
  const [savedContext]=useState<{companyId:string;view:View;trace:TraceSelection|null;history:HistorySelection|null}>(()=>{
    if(analysisTarget)return {companyId:analysisTarget.companyId,view:"data" as View,trace:null,history:null};
    const empty={companyId:"",view:"home" as View,trace:null,history:null};
    try{const saved=JSON.parse(sessionStorage.getItem(contextKey)??"{}");const id=/^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$/;
      const companyId=typeof saved.companyId==="string"&&id.test(saved.companyId)?saved.companyId:"";
      const view=["home","companies","finance","data","ontology","operations","regulation","actions"].includes(saved.view)?saved.view as View:"home";
      const trace=saved.trace&&id.test(saved.trace.resource_id)&&id.test(saved.trace.version_id)&&saved.trace.company_id===companyId?saved.trace:null;
      const history=saved.history&&id.test(saved.history.resource_id)&&id.test(saved.history.version_id)&&saved.history.company_id===companyId?saved.history:null;
      return {companyId,view,trace,history};
    }catch{return empty;}
  });
  const [buildTarget,setBuildTarget]=useState<{requestId:string;transformation:{resource_id:string;version_id:string};companyId:string;selection:number}|null>(null);
  const [mapState,setMapState]=useState<MapWorkspaceState>(initialMapState);const [rawMapSelection,setMapSelection]=useState<MapSelection|null>(null);
  const [resolvedCompany,setResolvedCompany]=useState<ResolvedCompanyContext|null>(null);
  const [companyContextError,setCompanyContextError]=useState("");
  const [companyIndex,setCompanyIndex] = useState<CompanyIndex|null>(null);
  const [exploredCompany,setExploredCompany] = useState<CanonicalResource|null>(null);
  const [companyDirectory,setCompanyDirectory] = useState<Loadable<CanonicalResource[]>>({data:null,error:null});
  const [companyInitialTab,setCompanyInitialTab]=useState<"accounting"|undefined>(undefined);
  const [companyAccountingEntry,setCompanyAccountingEntry]=useState<CompanyAccountingEntry|null>(null);
  const [companyRegulationEntry,setCompanyRegulationEntry]=useState<CompanyRegulationEntry|null>(null);
  const [view,setView] = useState<View>(savedContext.view); const [snapshot,setSnapshot] = useState<Snapshot>(emptySnapshot);
  const [loading,setLoading] = useState(true); const [revision,setRevision] = useState(0); const [updated,setUpdated] = useState("");
  const [navigationCompanyId,setCompanyId] = useState(savedContext.companyId);const companyId=routeTarget?.companyId??navigationCompanyId; const [search,setSearch] = useState(""); const [workFilter,setWorkFilter] = useState("pending");
  const accountingEntry=accountingEntryForSession(companyAccountingEntry,token,companyId);
  const regulationEntry=regulationEntryForSession(companyRegulationEntry,token,companyId);
  const companySurfaceKey=JSON.stringify([token,sourceReview?"source-review":view,companyId,accountingEntry?.entryId??"saved"]);
  const [companyReadback,setCompanyReadback]=useState<CompanyNyxReadback|null>(null);
  const onCompanyContext=useCallback((value:CompanyNyxContext)=>setCompanyReadback({key:companySurfaceKey,context:value}),[companySurfaceKey]);
  const companyContext=companyNyxForSurface(companyReadback,companySurfaceKey,companyId,!sourceReview&&(view==="home"||view==="companies"));
  const [rawTrace,setTrace]=useState<TraceSelection|null>(savedContext.trace);const trace=rawTrace?.company_id===companyId?rawTrace:null;
  const traceContextKey=trace?JSON.stringify([contextKey,token,companyId,trace.resource_id,trace.version_id,trace.known_at]):null;
  const [traceSelection,setTraceSelection]=useState<{key:string|null;context:TraceContextChange}|null>(null);
  const onTraceSelection=useCallback((context:TraceContextChange)=>setTraceSelection({key:traceContextKey,context}),[traceContextKey]);
  const activeTraceSelection=traceContextKey&&traceSelection?.key===traceContextKey?traceSelection.context:null;
  const traceNode=activeTraceSelection?.selection;
  const traceInspectionKey=traceNode?JSON.stringify([traceContextKey,traceNode.resource_id,traceNode.version_id,traceNode.known_at]):null;
  const [traceReadback,setTraceReadback]=useState<{key:string;inspection:OperatorInspection|null;error:string}|null>(null);
  const traceInspection=traceInspectionKey&&traceReadback?.key===traceInspectionKey?traceReadback:null;
  const traceResourceId=traceNode?.resource_id;const traceVersionId=traceNode?.version_id;const traceKnownAt=traceNode?.known_at;
  useEffect(()=>{
    if(!traceInspectionKey||!traceResourceId||!traceVersionId||!traceKnownAt)return;
    const controller=new AbortController();let disposed=false;const timer=setTimeout(()=>controller.abort(),20000);
    const params=new URLSearchParams({version_id:traceVersionId,known_at:traceKnownAt});
    void get<OperatorInspection>(`ontology/operator/resources/${traceResourceId}?${params}`,token,controller.signal).then(value=>{
      if(value.resource?.resource_id!==traceResourceId||value.resource.version_id!==traceVersionId||!restorationInstant(value.known_at)||restorationInstant(value.known_at)!==restorationInstant(traceKnownAt))throw Error("Trace inspection did not match the selected version and knowledge cutoff.");
      if(!disposed)setTraceReadback({key:traceInspectionKey,inspection:value,error:""});
    }).catch(error=>{if(!disposed)setTraceReadback({key:traceInspectionKey,inspection:null,error:controller.signal.aborted?"Selected trace version timed out.":error instanceof Error?error.message:"Selected trace version unavailable."});}).finally(()=>clearTimeout(timer));
    return()=>{disposed=true;clearTimeout(timer);controller.abort();};
  },[token,traceInspectionKey,traceResourceId,traceVersionId,traceKnownAt]);
  const [rawHistory,setHistory]=useState<HistorySelection|null>(savedContext.history);const history=rawHistory?.company_id===companyId?rawHistory:null;
  useEffect(()=>{try{sessionStorage.setItem(contextKey,JSON.stringify({companyId,view,trace,history}));}catch{/* Navigation can operate without browser storage. */}},[contextKey,companyId,view,trace,history]);
  const [sourceSelectionKey,setSourceSelectionKey] = useState(0);
  const [proposalTarget,setProposalTarget] = useState<{proposalId:string;companyId:string;returnView:View}|null>(null);
  const [actionTarget,setActionTarget] = useState<{workflowId:string;companyId:string}|null>(null);
  const [accountPolicyTarget,setAccountPolicyTarget]=useState<{companyId:string;account:CanonicalResource}|null>(null);
  const [rawSelected,setSelected] = useState<(OperatorInspection) | null>(null); const [rawWork,setWork] = useState<WorkItem | null>(null);
  const [rawReceipt,setReceipt] = useState<ReceiptDetail | null>(null); const [rawProposal,setProposal] = useState<ResourceProposalDetail | null>(null);
  const [rawDetailError,setDetailError] = useState(""); const [rawDetailBusy,setDetailBusy] = useState(false);
  const [detailScope,setDetailScope]=useState(companyId);
  const selected=detailScope===companyId?rawSelected:null,work=detailScope===companyId?rawWork:null,receipt=detailScope===companyId?rawReceipt:null,proposal=detailScope===companyId?rawProposal:null,mapSelection=detailScope===companyId?rawMapSelection:null;
  const detailError=detailScope===companyId?rawDetailError:"",detailBusy=detailScope===companyId&&rawDetailBusy;
  const [engineering,setEngineering] = useState<{view:EngineeringView;receiptId?:string;proposalId?:string}>({view:"intake"});
  const [menu,setMenu] = useState(false); const [rail,setRail] = useState(false);
  const [savedLayout]=useState(()=>{try{const value=JSON.parse(localStorage.getItem("g8-layout-v1")??"{}");return {nav:value.nav===true,nyx:value.nyx===true,width:typeof value.width==="number"&&Number.isFinite(value.width)?Math.max(300,Math.min(1600,value.width)):340};}catch{return {nav:false,nyx:false,width:340};}});
  const [navFolded,setNavFolded]=useState(savedLayout.nav);const [nyxFolded,setNyxFolded]=useState(savedLayout.nyx);
  const [nyxWidth,setNyxWidth]=useState(savedLayout.width);
  useEffect(()=>{try{localStorage.setItem("g8-layout-v1",JSON.stringify({nav:navFolded,nyx:nyxFolded,width:nyxWidth}));}catch{/* Optional layout persistence. */}},[navFolded,nyxFolded,nyxWidth]);const [viewport,setViewport]=useState(1440);
  const [nyxTab,setNyxTab]=useState("interact");const drag=useRef<{x:number;width:number}|null>(null);
  useEffect(()=>{const resize=()=>setViewport(window.innerWidth);resize();window.addEventListener("resize",resize);return()=>window.removeEventListener("resize",resize);},[]);
  const maxNyxWidth=Math.max(300,viewport-(viewport>1000?(navFolded?64:204)+360:16));
  const panelWidth=Math.min(nyxWidth,maxNyxWidth),maxNyxSize=maxNyxWidth,minNyxSize=300,currentNyxSize=panelWidth;
  function resizeNyx(value:number){setNyxWidth(Math.max(minNyxSize,Math.min(maxNyxSize,value)));}
  function toggleNyx(){if(viewport>1000)setNyxFolded(!nyxFolded);else setRail(!rail);}
  function closeNyx(){setNyxFolded(true);setRail(false);}
  useEffect(()=>{if(!rail||viewport>1000)return;const previous=document.activeElement as HTMLElement|null;const pane=document.querySelector<HTMLElement>(".g8-analyst");pane?.querySelector<HTMLElement>("button")?.focus();const key=(event:KeyboardEvent)=>{if(event.key==="Escape"){setRail(false);return;}if(event.key==="Tab"&&pane){const controls=Array.from(pane.querySelectorAll<HTMLElement>('button:not([disabled]),input:not([disabled]),select:not([disabled]),[tabindex="0"]')).filter(el=>el.getClientRects().length);const first=controls[0],last=controls.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}}};window.addEventListener("keydown",key);return()=>{window.removeEventListener("keydown",key);previous?.focus({preventScroll:true});};},[rail,viewport]);
  const [financeTarget,setFinanceTarget]=useState<FinanceReportReference|null>(null);
  function openFinance(reference:FinanceReportReference){setFinanceTarget(reference);navigate("finance");}
  const viewScroll=useRef<Record<string,number>>({});
  useEffect(()=>{if(sourceReview)return;let settled=0;const frame=requestAnimationFrame(()=>{settled=requestAnimationFrame(()=>{
    if(location.pathname!=="/")return;
    const origin=pendingOrigin.current,retained=origin&&originElements.current.get(origin.entryId);
    const matches=origin?.companyId===companyId&&origin.view===view;
    document.getElementById("g8-main")?.scrollTo({top:matches?origin.scroll:viewScroll.current[`${companyId}:${view}`]??0,behavior:"instant"});
    if(matches&&retained){for(const item of retained.scrolls)if(item.element.isConnected)item.element.scrollTo({top:item.top,left:item.left,behavior:"instant"});if(retained.focus?.isConnected&&retained.focus.getClientRects().length)retained.focus.focus({preventScroll:true});pendingOrigin.current=null;}
  });});return()=>{cancelAnimationFrame(frame);cancelAnimationFrame(settled);};},[view,companyId,sourceReview]);
  useEffect(()=>{
    function back(){
      const target=sourceReviewTarget(location.pathname),candidate=parseSourceReviewOrigin(window.history.state?.[target?"g8SourceReviewOrigin":"g8SourceReviewReturn"],originSession,target??undefined);
      const retained=candidate&&originElements.current.get(candidate.entryId);
      const origin=candidate&&retained&&retained.origin.companyId===candidate.companyId&&retained.origin.view===candidate.view?candidate:null;
      setReviewOrigin(target?origin:null);
      if(!target&&location.pathname==="/"&&origin){pendingOrigin.current=origin;setCompanyId(origin.companyId);setView(origin.view);setTrace(null);setHistory(null);setMenu(false);}
    }
    window.addEventListener("popstate",back);return()=>window.removeEventListener("popstate",back);
  },[originSession]);
  const [financeVisited,setFinanceVisited]=useState(savedContext.view==="finance");
  const [ontologySection,setOntologySection]=useState("resources");
  const [queueAnchor,setQueueAnchor]=useState<number|null>(null);
  const queueGeneration=queueAnchor??revision;
  const [queuesRevision,setQueuesRevision]=useState(-1);
  const [graphRevision,setGraphRevision]=useState(-1);
  const [proposalPage,setProposalPage]=useState<{revision:number;page:ProposalQueuePage|null;error:string;loadingMore:boolean}|null>(null);
  const queueControl=useRef<{revision:number;controller:AbortController;busy:boolean}|null>(null);
  const paging=proposalPage?.revision===queueGeneration?proposalPage:null;
  const queuesLoading=queuesRevision!==queueGeneration;
  const graphLoading=graphRevision!==revision;
  const detailRequest = useRef(0); const searchRef = useRef<HTMLInputElement>(null); const workRef = useRef<HTMLDivElement>(null);
  const canOntology = principal.permissions.includes("ontology_read");
  const refresh = useCallback(() => {setQueueAnchor(null);setRevision(value => value+1);},[]);
  useEffect(()=>{
    const check=()=>{if(document.visibilityState==="visible")setRevision(value=>value+1);};
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
      const [summary,context,readiness,directory] = await Promise.all([
        read<NonNullable<Snapshot["summary"]["data"]>>("workspace/summary","summary"),
        canOntology ? read<NonNullable<Snapshot["context"]["data"]>>("ontology/context","context") : noAccess,
        read<NonNullable<Snapshot["readiness"]["data"]>>("readiness","readiness"),canOntology?loadCompanies():noAccess]);
      if (!cancelled) {setCompanyDirectory(directory);setSnapshot(previous=>({...previous,summary,context,readiness}));setUpdated(new Date().toLocaleTimeString(undefined,{hour:"2-digit",minute:"2-digit"}));setLoading(false);}
    }
    void load(); return () => {cancelled=true;controller.abort();};
  },[token,canOntology,revision]);
  useEffect(()=>{
    const controller=new AbortController();let disposed=false;
    const control={revision:queueGeneration,controller,busy:false};queueControl.current=control;
    async function loadQueues(){
      async function proposals(){
        try{
          const page=await get<ProposalQueuePage>("ontology/proposal-queue?limit=25",token,controller.signal);
          if(!disposed){setSnapshot(previous=>({...previous,proposals:{data:page.proposals,error:null}}));setProposalPage({revision:queueGeneration,page,error:"",loadingMore:false});}
        }catch(error){if(!disposed){const message=error instanceof Error?error.message:"Change queue unavailable";setSnapshot(previous=>({...previous,proposals:{data:null,error:message}}));setProposalPage({revision:queueGeneration,page:null,error:message,loadingMore:false});}}
      }
      async function queue<T>(path:string,key:"evidence"|"proposals"):Promise<void>{
        let result:Loadable<T>;
        try{result={data:await get<T>(path,token,controller.signal),error:null};}
        catch(error){result={data:null,error:error instanceof Error?error.message:"Queue unavailable"};}
        if(!disposed)setSnapshot(previous=>({...previous,[key]:result}));
      }
      await Promise.all([
        queue<NonNullable<Snapshot["evidence"]["data"]>>("workspace/intake","evidence"),
        canOntology?proposals():Promise.resolve().then(()=>{if(!disposed)setSnapshot(previous=>({...previous,proposals:{data:null,error:"Your workspace access does not include the change queue."}}));}),
      ]);
      if(!disposed)setQueuesRevision(queueGeneration);
    }
    void loadQueues();return()=>{disposed=true;controller.abort();};
  },[token,canOntology,queueGeneration]);
  async function loadOlderProposals(){
    const page=paging?.page;const control=queueControl.current;
    if(!page?.has_more||!page.next_cursor||!control||control.revision!==queueGeneration||control.busy||control.controller.signal.aborted)return;
    control.busy=true;setQueueAnchor(queueGeneration);setProposalPage({revision:queueGeneration,page,error:"",loadingMore:true});
    const params=new URLSearchParams({limit:String(page.limit),snapshot_at:page.snapshot_at,before_created_at:page.next_cursor.created_at,before_proposal_id:page.next_cursor.proposal_id});
    try{
      const next=await get<ProposalQueuePage>(`ontology/proposal-queue?${params}`,token,control.controller.signal);
      if(!control.controller.signal.aborted){
        setSnapshot(previous=>({...previous,proposals:{data:[...new Map([...(previous.proposals.data??[]),...next.proposals].map(row=>[row.proposal_id,row])).values()],error:null}}));
        setProposalPage({revision:queueGeneration,page:next,error:"",loadingMore:false});
      }
    }catch(error){if(!control.controller.signal.aborted)setProposalPage({revision:queueGeneration,page,error:error instanceof Error?error.message:"Older changes unavailable",loadingMore:false});}
    finally{control.busy=false;}
  }
  useEffect(()=>{
    if(view!=="ontology"||ontologySection!=="resources"||!canOntology||graphRevision===revision)return;
    const controller=new AbortController();let disposed=false;
    void get<NonNullable<Snapshot["graph"]["data"]>>("ontology/graph",token,controller.signal)
      .then(data=>{if(!disposed)setSnapshot(previous=>({...previous,graph:{data,error:null}}));})
      .catch(error=>{if(!disposed)setSnapshot(previous=>({...previous,graph:{data:null,error:error instanceof Error?error.message:"Ontology unavailable"}}));})
      .finally(()=>{if(!disposed)setGraphRevision(revision);});
    return()=>{disposed=true;controller.abort();};
  },[view,ontologySection,canOntology,token,revision,graphRevision]);
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
    ...(resolvedContext.source_company_aliases??[]).map(row=>String(row.attributes.document_id)),
    ...resolvedContext.accounting_sources.map(row=>String(row.scope.attributes.document_id)),
    ...resolvedContext.disclosures.map(row=>String(row.observation.attributes.document_id)),
    ...resolvedContext.licence_evidence.flatMap(row=>row.notice?[String(row.notice.attributes.document_id)]:[]),
  ])]:[];
  const companyMismatch = !!selectedCompanyId && selectedCompanyId !== contextCompanyId;
  const scopedEvidence = companyMismatch
    ? (snapshot.evidence.data??[]).filter(item=>companyDocumentIds.includes(item.receipt_id))
    : snapshot.evidence.data ?? [];
  const scopedProposals = (snapshot.proposals.data ?? []).filter(item => !currentCompany || item.access_entity === currentCompany.access_entity || item.access_entity === "__PLATFORM__");
  const items = workItems(scopedEvidence,scopedProposals);
  const pending = items.filter(item => item.state === "PENDING");
  const query = search.trim().toLocaleLowerCase();
  const visibleResources = resources.filter(item => !["SchemaDefinition","SemanticContract","LinkType"].includes(item.object_type))
    .filter(item => !selectedCompanyId || belongsToCompany(item,selectedCompanyId));
  const results = query ? [...[...new Map(companies.map(item=>[item.resource_id,item])).values()].filter(item => item.display_name.toLocaleLowerCase().includes(query)).map(item => ({id:item.resource_id,title:item.display_name,kind:readable(item.object_type),resource:item,work:null})),...items.filter(item => item.title.toLocaleLowerCase().includes(query)).map(item => ({id:item.id,title:item.title,kind:readable(item.kind),resource:null,work:item}))].slice(0,12) : [];
  const ready = snapshot.readiness.data;
  const openEngineering = (next:EngineeringView,receiptId?:string,proposalId?:string) => {setEngineering({view:next,receiptId,proposalId});navigate("system");};
  const navigate = (next:View) => {setCompanyRegulationEntry(null);setCompanyAccountingEntry(null);setSourceReadback(null);window.dispatchEvent(new Event("g8:capture-source-review"));if(sourceReview){const url=new URL(location.href);url.pathname="/";url.searchParams.delete("analysis_view");window.history.pushState(null,"",url);}viewScroll.current[`${companyId}:${view}`]=document.getElementById("g8-main")?.scrollTop??0;if(next==="finance")setFinanceVisited(true);setCompanyInitialTab(undefined);setView(next);setTrace(null);setMenu(false);setSearch("");};
  const openCompanyRegulation=(handoff:CompanyRegulationHandoff)=>{if(handoff.company.resource_id!==companyId)return;clearSelection();navigate("regulation");setCompanyRegulationEntry({token,entryId:crypto.randomUUID(),handoff});};
  const openHomeAccounting=(handoff:CompanyAccountingHandoff)=>{if(handoff.company.resource_id!==companyId)return;clearSelection();navigate("companies");setCompanyAccountingEntry({token,entryId:crypto.randomUUID(),handoff});};
  const openBusinessProposal = (proposalId:string) => {setProposalTarget({proposalId,companyId,returnView:view});navigate("actions");};
  const clearSelection = () => {setDetailScope(companyId);setHistory(null);setTrace(null);setMapSelection(null);detailRequest.current++;setSelected(null);setWork(null);setReceipt(null);setProposal(null);setDetailError("");setDetailBusy(false);};
  async function inspect(resource:Pick<CanonicalResource,"resource_id">, pinnedVersion?:string,knownAt?:string) {setDetailScope(companyId);setNyxTab("context");setMapSelection(null);
    const request = ++detailRequest.current;setWork(null);setReceipt(null);setProposal(null);setSelected(null);setDetailError("");setDetailBusy(true);setRail(true);setNyxFolded(false);setSearch("");
    try {const params=new URLSearchParams({...pinnedVersion?{version_id:pinnedVersion}:{},...knownAt?{known_at:knownAt}:{}});const value=await get<OperatorInspection>(`ontology/operator/resources/${resource.resource_id}?${params}`,token);if(value.resource.resource_id!==resource.resource_id||(pinnedVersion&&value.resource.version_id!==pinnedVersion)||(knownAt&&restorationInstant(value.known_at)!==restorationInstant(knownAt)))throw Error("Inspection did not match the selected resource, version and knowledge cutoff.");if(request===detailRequest.current)setSelected(value);}
    catch(error){if(request===detailRequest.current)setDetailError(error instanceof Error ? error.message : "Could not inspect resource");}
    finally {if(request===detailRequest.current)setDetailBusy(false);}
  }
  const inspectWork = useCallback(async (item:WorkItem, showRail=true) => {setDetailScope(companyId);
    if(item.kind==="evidence"){setBuildTarget(null);setSourceSelectionKey(value=>value+1);}
    setMapSelection(null);const request=++detailRequest.current;setWork(item);setSelected(null);setReceipt(null);setProposal(null);setDetailError("");setDetailBusy(true);if(showRail){setRail(true);setNyxFolded(false);}setSearch("");
    try {if(item.kind === "evidence") {const value=await get<ReceiptDetail>(`workspace/constructions/${item.id}`,token);if(request===detailRequest.current)setReceipt(value);}else {const value=await get<ResourceProposalDetail>(`ontology/proposals/${item.id}`,token);if(request===detailRequest.current)setProposal(value);}}
    catch(error){if(request===detailRequest.current)setDetailError(error instanceof Error ? error.message : "Could not inspect work");}
    finally {if(request===detailRequest.current)setDetailBusy(false);}
  },[token,companyId,setBuildTarget,setWork,setProposal,setRail,setNyxFolded]);
  const inspectSource = useCallback((source:IntakeItem) => {void inspectWork(workItems([source],[])[0],false);},[inspectWork]);
  const selectMap = (selection:MapSelection|null) => {clearSelection();setMapSelection(selection);if(selection){setNyxTab("context");setNyxFolded(false);setRail(true);}};
  const mapProps={token,selection:mapSelection,companyId:currentCompany?.resource_id,canPropose:principal.permissions.includes("ontology_propose"),state:mapState,onState:setMapState,onSelect:selectMap,onReview:(id:string)=>openEngineering("ontology",undefined,id)};
  function focusWorkQueue(){const panel=workRef.current?.closest("details");if(panel)panel.open=true;requestAnimationFrame(()=>{const queue=workRef.current;if(queue){queue.focus({preventScroll:true});queue.scrollIntoView({behavior:"smooth"});}});}
  const workTable = <>{queueAnchor!==null&&<p className="g8-subtle">Browsing older changes. Refresh workspace to return to the latest queue.</p>}<WorkQueue onLoadMoreProposals={()=>void loadOlderProposals()} proposalsHaveMore={paging?.page?.has_more??false} proposalsLoadingMore={paging?.loadingMore??false} proposalsPageError={paging?.page?paging.error:""} items={items} filter={workFilter} onFilter={setWorkFilter} onInspect={item=>{void inspectWork(item);setNyxTab("context");}} onHistory={()=>openEngineering("history")} loading={queuesLoading} errors={[snapshot.evidence.error?`Evidence queue unavailable: ${snapshot.evidence.error}`:"",snapshot.proposals.error?`Change queue unavailable: ${snapshot.proposals.error}`:""].filter(Boolean)} scope={companyMismatch?"Company exploration; unbound source evidence excluded":"Current authorized scope"}/></>;
  function openSourceReview(target:SourceReviewTarget){
    const destination=sourceReviewUrl(target,new URL(location.href));
    setSourceReadback(null);
    window.dispatchEvent(new Event("g8:capture-source-review"));
    let origin:SourceReviewOrigin|null=null;
    if(!sourceReview&&target.companyId===companyId){
      origin=parseSourceReviewOrigin({version:1,sessionId:originSession,entryId:crypto.randomUUID(),companyId,invocationId:target.invocationId,...(target.journalSnapshot===undefined?{}:{journalSnapshot:target.journalSnapshot}),view,scroll:document.getElementById("g8-main")?.scrollTop??0},originSession,target);
      if(origin){
        const elements=Array.from(businessSurface.current?.querySelectorAll<HTMLElement>("*")??[]).filter(element=>element.scrollTop||element.scrollLeft).slice(0,128);
        originElements.current.set(origin.entryId,{origin,focus:document.activeElement instanceof HTMLElement?document.activeElement:null,scrolls:elements.map(element=>({element,top:element.scrollTop,left:element.scrollLeft}))});
        if(originElements.current.size>20)originElements.current.delete(originElements.current.keys().next().value!);
        window.history.replaceState({...window.history.state,g8SourceReviewReturn:origin},"",location.href);
        viewScroll.current[`${companyId}:${view}`]=origin.scroll;
      }
    }else if(reviewOrigin&&reviewOrigin.companyId===target.companyId){const {journalSnapshot:previousSnapshot,...entry}=reviewOrigin;void previousSnapshot;origin=parseSourceReviewOrigin({...entry,invocationId:target.invocationId,...(target.journalSnapshot===undefined?{}:{journalSnapshot:target.journalSnapshot})},originSession,target);}
    setReviewOrigin(origin);clearSelection();setCompanyId(target.companyId);setMenu(false);setSearch("");window.history.pushState(origin?{g8SourceReviewOrigin:origin}:null,"",destination);
  }
  function returnFromSourceReview(){
    setSourceReadback(null);
    window.dispatchEvent(new Event("g8:capture-source-review"));
    const origin=analysisTarget?parseSourceReviewOrigin(window.history.state?.g8SourceReviewOrigin,originSession,analysisTarget):null;
    const retained=origin&&originElements.current.get(origin.entryId);
    if(!origin||!retained||retained.origin.companyId!==origin.companyId||retained.origin.view!==origin.view){navigate("data");return;}
    pendingOrigin.current=origin;setReviewOrigin(null);setCompanyId(origin.companyId);setView(origin.view);setTrace(null);setHistory(null);setMenu(false);setSearch("");
    const url=new URL(location.href);url.pathname="/";url.searchParams.delete("analysis_view");window.history.pushState({g8SourceReviewReturn:origin},"",url);
  }
  const historyPanel=history&&<OperatorHistory canPropose={principal.permissions.includes("ontology_propose")} onProposal={openBusinessProposal} key={`${history.resource_id}:${history.known_at??"current"}`} token={token} selection={history} onClose={()=>setHistory(null)} onSelect={(version,knownAt)=>{setHistory({...history,version_id:version.version_id,known_at:knownAt});void inspect(version,version.version_id,knownAt);}} onTrace={(version,knownAt)=>setTrace({resource_id:version.resource_id,version_id:version.version_id,company_id:companyId,known_at:knownAt})} onInspect={(id,knownAt)=>void inspect({resource_id:id},undefined,knownAt)}/>;
  const tracePanel=trace&&<OperatorTrace key={traceContextKey} token={token} root={trace} onSelectionChange={onTraceSelection} onClose={()=>setTrace(null)} onInspect={(node,knownAt)=>void inspect(node,node.version_id,knownAt)}/>;
  return <SourceReviewNavigation.Provider value={openSourceReview}><div className={`g8-app ${sourceReview?"source-review-active":""} ${menu ? "menu-open" : ""} ${rail ? "rail-open" : ""} ${navFolded ? "nav-folded" : ""} ${nyxFolded ? "nyx-folded" : ""}`} style={{"--nyx-width":`${panelWidth}px`} as CSSProperties}>{accountPolicyTarget?.companyId===companyId&&<AccountDimensionPolicyWorkbench token={token} companyId={companyId} account={accountPolicyTarget.account} canPropose={principal.permissions.includes("ontology_propose")} onProposal={openBusinessProposal} onClose={()=>setAccountPolicyTarget(null)} onInspectResource={reference=>void inspect(reference,reference.version_id)} onTraceResource={reference=>setTrace({...reference,company_id:companyId})}/>}<a className="g8-skip" href="#g8-main">Skip to workspace</a>
    <aside className="g8-sidebar"><div className="g8-nav-brand"><Brand /><button className="g8-icon fold-navigation" aria-label={navFolded?"Expand navigation":"Collapse navigation"} aria-expanded={!navFolded} onClick={()=>setNavFolded(!navFolded)}><SidebarSimple size={18}/></button></div><p className="g8-tagline">Enterprise Intelligence</p><nav aria-label="Business navigation">{navigation.map(({id,label,hint,icon:Icon,available})=><button disabled={!available} title={available?label:`${label}: not connected yet`} aria-label={available?label:`${label} — not connected`} aria-current={view===id ? "page" : undefined} className={view===id ? "active" : ""} onClick={()=>navigate(id as View)} key={id}><Icon size={21} weight="regular"/><span>{label}{hint && <small>{hint}</small>}</span></button>)}</nav><div className="g8-nav-bottom"><button aria-label="System / Engineering" title="System / Engineering" className={`g8-system ${view === "system" ? "active" : ""}`} onClick={()=>navigate("system")}><GearSix size={21}/><span>System<small>Engineering access</small></span><CaretRight size={13}/></button><div className="g8-platform"><ShieldCheck size={20}/><span>G8 Platform<small>{loading ? "Checking services…" : ready?.status === "ready" ? "Services ready" : "Readiness unavailable"}</small></span></div></div></aside>
    <header className="g8-topbar"><button className="g8-icon mobile-menu" aria-label="Toggle navigation" onClick={()=>setMenu(!menu)}><List size={21}/></button><div className="g8-search"><MagnifyingGlass size={19}/><input ref={searchRef} aria-label="Search workspace" maxLength={200} placeholder="Search company resources, identities and work…" value={search} onChange={event=>setSearch(event.target.value)}/><kbd>Ctrl K</kbd>{query && <div className="g8-search-results" role="region" aria-label="Search results"><WorkspaceSearchResults key={companyId} token={token} companyId={companyId} companyName={currentCompany?displayName(currentCompany.display_name):""} query={search} onInspect={(resource,knownAt)=>void inspect(resource,resource.version_id,knownAt)} onClose={()=>setSearch("")}/><small>Companies & loaded work</small>{results.map(result=><button key={result.id} onClick={()=>result.resource ? void inspect(result.resource) : result.work && void inspectWork(result.work)}><span>{displayName(result.title)}<small>{result.kind}</small></span><ArrowRight size={15}/></button>)}{!results.length && <p>No matching companies or loaded work.</p>}</div>}</div><button className="g8-icon" aria-label="Refresh workspace" onClick={refresh} disabled={loading}><ArrowClockwise size={19}/></button><div className="g8-user"><span>{principal.display_name.split(" ").map(part=>part[0]).slice(0,2).join("")}</span><div>{principal.display_name}<small>Governed workspace</small></div></div><button className="g8-icon" aria-label="Sign out" onClick={onSignOut}><SignOut size={19}/></button><button className="g8-icon nyx-toggle" aria-label="Toggle NYX assistant" aria-expanded={viewport>1000?!nyxFolded:rail} onClick={toggleNyx}><Image src="/brand/nyx-core-transparent.png" alt="" width={25} height={25}/></button></header>
    <main id="g8-main" className="g8-main" data-view={sourceReview?"source-review":view}>{sourceReview&&analysisTarget&&<section className="g8-source-review-route" aria-label="Source review workspace"><div className="g8-source-review-nav"><button className="g8-link" onClick={returnFromSourceReview}>Back to {reviewOrigin?(reviewOrigin.view==="system"?"System / Engineering":navigation.find(area=>area.id===reviewOrigin.view)?.label??"Data & evidence"):"Data & evidence"}</button><span>Source review</span></div><div className="g8-source-review-content" hidden={Boolean(trace||history)}><SemanticAnalysisWorkspace onContext={onSourceContext} key={`${analysisTarget.companyId}:${analysisTarget.invocationId}:${analysisTarget.journalSnapshot??"source"}`} token={token} companyId={analysisTarget.companyId} invocationId={analysisTarget.invocationId} journalSnapshot={analysisTarget.journalSnapshot} onInspect={reference=>void inspect(reference,reference.version_id,reference.known_at)}/></div>{(trace||history)&&<div className="g8-source-review-inspector">{trace?tracePanel:historyPanel}</div>}</section>}<div ref={businessSurface} hidden={sourceReview} style={{display:sourceReview?"none":"contents"}}>{(!sourceReview||reviewOrigin)&&<><div className="g8-breadcrumb">Workspace< CaretRight size={12}/>{view === "system" ? "System / Engineering" : navigation.find(area=>area.id===view)?.label}<span>{loading ? "Refreshing…" : `Updated ${updated}`}</span></div>
    <CompanyPicker index={companyIndex} selected={currentCompany} selectedId={companyId} error={companyDirectory.error} onSelect={node=>{setCompanyInitialTab(undefined);setExploredCompany(node);setCompanyId(node?.resource_id??"");setCompanyContextError("");setResolvedCompany(null);clearSelection();}}/>
    {companyId&&!currentCompany&&companyDirectory.data&&<p role="alert">The selected company is unavailable in this directory. Choose another context; no substitute company has been selected.</p>}
    {view === "system" ? <><div className="g8-page-heading"><div><p className="overline">ADVANCED INTERNAL ACCESS</p><h1>System / Engineering</h1><p>Evidence intake, construction, registry and governed review tools.</p></div><Badge>Advanced</Badge></div><Engineering key={`${engineering.view}:${engineering.receiptId ?? ""}:${engineering.proposalId ?? ""}`} token={token} principal={principal} initialView={engineering.view} receiptId={engineering.receiptId} proposalId={engineering.proposalId}/></> : <>
      <div className={`g8-page-heading ${view==="home"?"g8-company-hero":""}`}><div><p className="overline">{view === "home" ? `Welcome, ${principal.display_name}.` : "ENTERPRISE WORKSPACE"}</p><h1>{view === "home" ? (currentCompany ? displayName(currentCompany.display_name) : undefined) ?? "Your company workspace" : view === "companies" ? "Companies" : view === "finance" ? "Finance" : view === "data" ? "Data & evidence" : view === "operations" ? "Operations & Maps" : view === "regulation" ? "Regulation" : view === "actions" ? "Workflows & Actions" : "Ontology"}</h1><p>{view === "home" ? "Financial reality. Operational context. Evidence-led decisions." : view === "companies" ? "Shared company identities. One connected business context." : view === "data" ? "Retained sources, review state and traceable versions." : view === "actions" ? "Investigate work, review changes and verify the resulting state." : "Explore the business resources behind your workspace."}</p></div>{view==="home"?<div className="g8-hero-status"><span><ShieldCheck size={15}/>{companyContextError?"Company context unavailable":resolvedContext?"Company context resolved":companyId?"Resolving company context":"Choose company"}</span><strong>{(currentCompany ? displayName(currentCompany.display_name) : undefined)??"Set your company context"}</strong><p>{currentCompany?readable(currentCompany.evidence_class):"Connect the company behind your work."}</p><button className="g8-link" onClick={()=>navigate("companies")}>Open Companies<ArrowRight size={13}/></button></div>:<Badge tone={currentCompany ? tone(currentCompany.authority_state) : "neutral"}>{currentCompany ? readable(currentCompany.evidence_class) : "Company not selected"}</Badge>}</div>
      {snapshot.graph.data?.bounded && (view==="ontology"&&ontologySection==="resources") && <p className="g8-inline-error">Showing up to 1,000 authorized resources. This is a bounded view.</p>}

      <div hidden={Boolean(trace)}>{(view==="home"||view==="companies")&&companyId&&<button className="g8-link" onClick={()=>{setOntologySection("sets");navigate("ontology");}}>Analyse account contributors</button>}
      {view === "home" && <><div className="g8-actionbar"><button onClick={()=>{setWorkFilter("pending");focusWorkQueue();}}><Tray size={23}/><span>Review items<small>{queuesLoading ? "Checking…" : `${pending.length} in loaded queues`}</small></span></button><button onClick={()=>{setNyxFolded(false);setRail(true);setNyxTab("interact");}}><ChartLineUp size={23}/><span>Investigate<small>Ask NYX about evidence</small></span></button>{principal.permissions.includes("ingest") && <button onClick={()=>openEngineering("intake")}><UploadSimple size={23}/><span>New data source<small>Retain source evidence</small></span></button>}<button disabled title="Reporting is not connected yet"><ChartLineUp size={23}/><span>Create report<small>Not connected</small></span></button><button disabled title="Planning is not connected yet"><GraphIcon size={23}/><span>New scenario<small>Not connected</small></span></button></div>
      <WorkspaceHealth snapshot={snapshot} loading={loading} onRefresh={refresh} onData={()=>navigate("data")}/>
      <CompanyHome onContext={onCompanyContext} showWork onTrace={(node,knownAt)=>setTrace({resource_id:node.resource_id,version_id:node.version_id,company_id:companyId,known_at:knownAt})} onHistory={(node,knownAt)=>setHistory({resource_id:node.resource_id,version_id:node.version_id,company_id:companyId,known_at:knownAt})} onProposal={openBusinessProposal} onWorkflow={workflowId=>{setProposalTarget(null);setActionTarget({workflowId,companyId});navigate("actions");}} onInspect={(node,knownAt)=>void inspect(node,node.version_id,knownAt)} onAccounting={openHomeAccounting} token={token} companyId={companyId} onData={()=>navigate("data")} onOperations={state=>{setMapState(state);navigate("operations");}} onMapSelection={selectMap}/>
      <details className="home-readiness"><summary>Source readiness and retained resource history</summary><ExecutiveOverview companyId={companyId} canonicalContext={resolvedContext} contextError={companyContextError} recentResult={recent?.data??null} recentError={recent?.error??""} onInspect={(resource,knownAt)=>void inspect(resource,resource.version_id,knownAt)} onTrace={(resource,knownAt)=>setTrace({resource_id:resource.resource_id,version_id:resource.version_id,company_id:companyId,known_at:knownAt})} onHistory={(resource,knownAt)=>setHistory({resource_id:resource.resource_id,version_id:resource.version_id,company_id:companyId,known_at:knownAt})} onRegulation={()=>navigate("regulation")} onAccounting={()=>{navigate("companies");setCompanyInitialTab("accounting");}} company={(currentCompany ? displayName(currentCompany.display_name) : undefined)??"Select company"} period={principal.scope.period} currency={principal.scope.currency} resources={visibleResources} resourcesAvailable={!loading && !!snapshot.graph.data} onData={()=>navigate("data")} onCompanies={()=>navigate("companies")} onOntology={()=>navigate("ontology")}/></details>
      <details className="home-supporting-work"><summary>Source review queues & recent review activity</summary><div className="g8-home-bottom"><div ref={workRef} tabIndex={-1} role="region" aria-label="My work review queue"><Panel title="My work" aside={<Badge>{queuesLoading?"Checking":snapshot.evidence.error||snapshot.proposals.error?"Partial queue":`${pending.length} loaded awaiting review`}</Badge>}>{workTable}</Panel></div><Panel title="Recent review activity" aside={<button className="g8-link" onClick={()=>{setWorkFilter("all");focusWorkQueue();}}>View all</button>}>{[...items].sort((a,b)=>b.date.localeCompare(a.date)).slice(0,5).map(item=><Signal key={`${item.kind}:${item.id}`} title={item.title} detail={`${readable(item.state)} · ${date(item.date)} · ${item.reason}`} tone={item.state==="APPROVED"?"good":item.state==="REJECTED"?"bad":"warning"} onClick={()=>{void inspectWork(item);setNyxTab("context");}}/>)}{!items.length&&<Empty title={queuesLoading?"Loading review activity…":snapshot.evidence.error||snapshot.proposals.error?"Review activity partially unavailable":"No retained review activity"}>Source receipts and proposal decisions appear here.</Empty>}</Panel></div></details></>}
      {view === "actions" && <><ActionWorkbench initialProposalId={proposalTarget?.companyId===companyId?proposalTarget.proposalId:undefined} onProposalDecision={refresh} onReturnFromProposal={()=>{const destination=proposalTarget?.companyId===companyId?proposalTarget.returnView:"home";setProposalTarget(null);navigate(destination);}} key={`${companyId}:${actionTarget?.companyId===companyId?actionTarget.workflowId:"saved"}`} onOpenBuild={(requestId,transformation)=>{setBuildTarget({requestId,transformation,companyId,selection:Date.now()});navigate("data");}} initialWorkflowId={actionTarget?.companyId===companyId?actionTarget.workflowId:undefined} token={token} principal={principal} companyId={companyId} onInspect={id=>void inspect({resource_id:id})}/><RuntimeStateWorkbench token={token} canRead={principal.permissions.includes("ontology_admin")}/></>}
      {view === "regulation" && <RegulationWorkspace key={`${token}:${companyId}:${regulationEntry?.entryId??"saved"}`} handoff={regulationEntry?.handoff} viewStateKey={`${contextKey}:regulation:${companyId}${regulationEntry?`:company360:${regulationEntry.entryId}`:""}`} token={token} companyId={companyId} onInspect={(node,knownAt)=>void inspect(node,node.version_id,knownAt)} onTrace={(node,knownAt)=>setTrace({resource_id:node.resource_id,version_id:node.version_id,known_at:knownAt,company_id:companyId})} onHistory={(node,knownAt)=>setHistory({resource_id:node.resource_id,version_id:node.version_id,known_at:knownAt,company_id:companyId})} onWorkflow={workflowId=>{setProposalTarget(null);setActionTarget({workflowId,companyId});navigate("actions");}} onProposal={openBusinessProposal} />}
      {view === "operations" && <OperationsMap key={currentCompany?.resource_id??"scope"} {...mapProps}/>}
      {view === "ontology" && <><nav className="g8-module-tabs" aria-label="Ontology views">{[["resources","Business resources"],["sets","Account analysis"],["accounting","Accounting contracts"]].map(([id,title])=><button key={id} aria-pressed={ontologySection===id} onClick={()=>setOntologySection(id)}>{title}</button>)}</nav>{ontologySection==="accounting"&&<p className="g8-subtle">Shared ontology definitions and queries cover your authorized scope. Company filtering is specified in each query or contract.</p>}</>}
      <div hidden={view!=="finance"}>{financeVisited&&<FinanceWorkspace onClearReport={()=>setFinanceTarget(null)} initialReport={financeTarget} key={companyId} token={token} companyId={companyId} context={resolvedContext} contextError={companyContextError} onContext={()=>{navigate("companies");setCompanyInitialTab("accounting");}} onInspect={reference=>void inspect(reference,reference.version_id,reference.known_at)} onTrace={reference=>setTrace({...reference,company_id:companyId})}/>}</div>
      {view === "ontology" && ontologySection==="accounting" && <AccountingFacts key={`${companyId}:${selected?.resource.version_id??"analysis"}`} token={token} authorityConsumer={typeof selected?.resource.attributes.minimum_authority_state==="string"?selected.resource:undefined} onTrace={reference=>setTrace({...reference,company_id:companyId})} />}
      {view === "ontology" && ontologySection==="sets" && <FinanceAnalysis key={companyId} companyId={companyId} companyName={currentCompany ? displayName(currentCompany.display_name) : "Selected company"} token={token} viewStateKey={`${contextKey}:object-sets:${companyId}`} onInspect={(node,context)=>void inspect(node,node.version_id,context.known_at)} onHistory={(node,context)=>setHistory({resource_id:node.resource_id,version_id:node.version_id,company_id:companyId,known_at:context.known_at})} onTrace={(node,context)=>setTrace({resource_id:node.resource_id,version_id:node.version_id,company_id:companyId,known_at:context.known_at})} onProposal={openBusinessProposal} />}
      {companyContextError&&<p role="alert">Company context: {companyContextError}</p>}

      {view === "companies" && <>{companyDirectory.error&&<p role="alert">{companyDirectory.error}</p>}<CompanyWorkspace onRegulation={openCompanyRegulation} onContext={onCompanyContext} onWorkflow={workflowId=>{setProposalTarget(null);setActionTarget({workflowId,companyId});navigate("actions");}} onOperations={state=>{setMapState(state);navigate("operations");}} onMapSelection={selectMap} onJournalInspect={(resource,knownAt)=>void inspect(resource,resource.version_id,knownAt)} onJournalTrace={(resource,knownAt)=>setTrace({resource_id:resource.resource_id,version_id:resource.version_id,known_at:knownAt,company_id:companyId})} onInspectResource={reference=>void inspect(reference,reference.version_id)} onTraceResource={reference=>setTrace({...reference,company_id:companyId})} onProposal={openBusinessProposal} canPropose={principal.permissions.includes("ontology_propose")} initialTab={companyInitialTab} initialAccountingHandoff={accountingEntry?.handoff} key={`${token}:${accountingEntry?.handoff.company.resource_id??currentCompany?.resource_id??"none"}:${accountingEntry?.entryId??"saved"}`} token={token} index={companyIndex} viewStateKey={`${contextKey}:companies:${accountingEntry?.handoff.company.resource_id??currentCompany?.resource_id??"none"}${accountingEntry?`:home:${accountingEntry.entryId}`:""}`} companyId={accountingEntry?.handoff.company.resource_id??currentCompany?.resource_id??""} onSelect={node=>{setCompanyInitialTab(undefined);setExploredCompany(node);setCompanyId(node.resource_id);setCompanyContextError("");setResolvedCompany(null);clearSelection();}} onInspect={(node,knownAt)=>void inspect(node,node.version_id,knownAt)} onHistory={(node,knownAt)=>setHistory({resource_id:node.resource_id,version_id:node.version_id,company_id:companyId,known_at:knownAt})} onTrace={(node,knownAt)=>setTrace({resource_id:node.resource_id,version_id:node.version_id,company_id:companyId,known_at:knownAt})} onNavigate={destination=>{if(destination==="finance"){navigate("finance");}else navigate(destination==="workflows"?"actions":destination);}}/></>}

      {view === "data" && <DataWorkspace initialBuildId={buildTarget?.companyId===companyId?buildTarget.requestId:undefined} builds={<BuildsWorkbench onInspectAnalysis={reference=>void inspect(reference,reference.version_id,reference.known_at)} companyId={companyId} onOpenFinance={openFinance} onProposal={openBusinessProposal} canReview={principal.permissions.includes("review")&&principal.permissions.includes("ontology_read")} actorId={principal.actor_id} initialRequestId={buildTarget?.companyId===companyId?buildTarget.requestId:undefined} initialTransformation={buildTarget?.companyId===companyId?buildTarget.transformation:undefined} token={token} companyName={currentCompany?displayName(currentCompany.display_name):""} canControl={principal.permissions.includes("ontology_read")&&principal.permissions.includes("ingest")} onInspect={(resource,knownAt)=>void inspect(resource,resource.version_id,knownAt)} onTrace={(resource,knownAt)=>setTrace({resource_id:resource.resource_id,version_id:resource.version_id,known_at:knownAt,company_id:companyId})}/>} savedAnalyses={<SavedAnalysisWorkbench onInspectAnalysis={reference=>void inspect(reference,reference.version_id,reference.known_at)} companyId={companyId} onOpenFinance={openFinance} onProposal={openBusinessProposal} token={token} companyName={currentCompany?displayName(currentCompany.display_name):""} onInspect={(resource,knownAt)=>void inspect(resource,resource.version_id,knownAt)} onTrace={(resource,knownAt)=>setTrace({resource_id:resource.resource_id,version_id:resource.version_id,known_at:knownAt,company_id:companyId})}/>} sourceSelectionKey={sourceSelectionKey} key={`${contextKey}:${companyId}:${buildTarget?.companyId===companyId?buildTarget.selection:"data"}`} initialSourceId={work?.kind==="evidence"?work.id:undefined} companyName={currentCompany?displayName(currentCompany.display_name):"All authorized contexts"} viewStateKey={`${contextKey}:data:${companyId}`} history={<HistoryExplorer key={`${contextKey}:${companyId}`} token={token} companyId={companyId} companyName={currentCompany?displayName(currentCompany.display_name):""} contextKey={contextKey} onInspect={(resource,knownAt)=>void inspect(resource,resource.version_id,knownAt)} onHistory={(resource,knownAt)=>{setHistory({resource_id:resource.resource_id,version_id:resource.version_id,company_id:companyId,known_at:knownAt});void inspect(resource,resource.version_id,knownAt);}} onTrace={(resource,knownAt)=>setTrace({resource_id:resource.resource_id,version_id:resource.version_id,company_id:companyId,known_at:knownAt})}/>} documents={<>{selectedCompanyId&&!resolvedContext?<p role="status">{companyContextError?"Company sources unavailable.":"Resolving company sources…"}</p>:<SourceDocuments key={selectedCompanyId||"all"} companyDocumentIds={selectedCompanyId?companyDocumentIds:undefined} token={token} principal={principal} onProposal={openBusinessProposal} />}</>} sources={<>{snapshot.evidence.error ? <Empty title="Source inventory unavailable">{snapshot.evidence.error}</Empty> : <SourceExplorer key={currentCompany?.resource_id ?? "scope"} token={token} principal={principal} sources={scopedEvidence} companyId={currentCompany?.resource_id} onInspectResource={reference=>void inspect(reference,reference.version_id)} onTraceResource={reference=>setTrace({...reference,company_id:companyId})} onProposal={openBusinessProposal} onSelect={inspectSource} initialReceiptId={work?.kind === "evidence" ? work.id : undefined} onReview={id=>openEngineering("history",id)}/>}</>} onIntake={()=>openEngineering("intake")}/> }
      {view === "ontology" && ontologySection==="resources" && <Panel title="Business resources" aside={<Badge>{visibleResources.length} in view</Badge>}>{graphLoading&&visibleResources.length>0&&<p role="status">Refreshing business resources; showing the previous snapshot.</p>}{!canOntology?<Empty title="Ontology unavailable">Your workspace access does not include ontology resources.</Empty>:snapshot.graph.error ? <Empty title="Ontology unavailable">{snapshot.graph.error}</Empty> : !visibleResources.length ? <Empty title={graphLoading ? "Loading business resources…" : "No accepted resources in this context"}>Accepted companies, accounts, relationships and other business resources will appear here with their definition review and evidence class.</Empty> : <div className="g8-table-scroll"><table><thead><tr><th>Resource</th><th>Type</th><th>Definition review</th><th>Evidence</th><th>Effective</th></tr></thead><tbody>{visibleResources.map(item=><tr key={item.resource_id}><td><button className="g8-link" onClick={()=>void inspect(item)}>{displayName(item.display_name)}</button></td><td>{readable(item.object_type)}</td><td><Badge tone={tone(item.authority_state)}>{item.authority_state}</Badge></td><td>{readable(item.evidence_class)}</td><td>{date(item.valid_from)}</td></tr>)}</tbody></table></div>}<div className="g8-panel-foot">Accepted business context · current effective versions<button className="g8-link" onClick={()=>openEngineering("ontology")}>Open governance tools<ArrowRight size={13}/></button></div></Panel>}
      {!sourceReview&&historyPanel}
      </div>
      {!sourceReview&&tracePanel}
      <footer className="g8-footer"><span><ShieldCheck size={13}/> Governed evidence · explicit authority</span><span>{snapshot.context.data?.binding ? "Company binding available" : "No confirmed company binding"}</span></footer></>}
    </>}</div></main>
    <>{rail&&viewport<=1000&&<button className="g8-nyx-backdrop" aria-label="Close NYX overlay" onClick={()=>setRail(false)}/>}<aside className="g8-analyst" inert={viewport<=1000&&!rail} role={viewport<=1000?"dialog":undefined} aria-modal={viewport<=1000&&rail?true:undefined} aria-label="NYX analyst context"><div className="nyx-resize" role="separator" aria-label="Resize NYX workspace" aria-orientation="vertical" aria-valuemin={minNyxSize} aria-valuemax={maxNyxSize} aria-valuenow={Math.round(currentNyxSize)} tabIndex={0} onDoubleClick={()=>resizeNyx(currentNyxSize>=maxNyxSize?300:maxNyxSize)} onKeyDown={event=>{if(["ArrowLeft","ArrowRight","Home","End"].includes(event.key)){event.preventDefault();resizeNyx(event.key==="Home"?minNyxSize:event.key==="End"?maxNyxSize:currentNyxSize+(event.key==="ArrowLeft"?40:-40));}}} onPointerDown={event=>{drag.current={x:event.clientX,width:currentNyxSize};event.currentTarget.setPointerCapture(event.pointerId);}} onPointerMove={event=>{if(drag.current)resizeNyx(drag.current.width+drag.current.x-(event.clientX));}} onPointerUp={event=>{drag.current=null;event.currentTarget.releasePointerCapture(event.pointerId);}} onPointerCancel={()=>{drag.current=null;}}/><header><Image src="/brand/nyx-core-transparent.png" alt="NYX Core" width={52} height={52}/><div><h2>NYX</h2><small>Context & evidence</small></div><button className="g8-icon nyx-expand" aria-label={currentNyxSize>=maxNyxSize?"Restore NYX size":"Expand NYX workspace"} onClick={()=>resizeNyx(currentNyxSize>=maxNyxSize?300:maxNyxSize)}><ArrowsOutSimple size={18}/></button><button className="g8-icon" aria-label="Close NYX context" onClick={closeNyx}><X size={17}/></button></header><div className="nyx-tabs" aria-label="NYX workspace views">{["context","interact","data"].map(id=><button key={id} aria-pressed={nyxTab===id} onClick={()=>setNyxTab(id)}>{id==="interact"?"Ask NYX":id==="data"?"Data workspace":"Context"}</button>)}</div><div className="g8-analyst-body">{sourceContext&&<SourceReviewContextPanel value={sourceContext} onTrace={(resource_id,version_id,known_at)=>setTrace({resource_id,version_id,known_at,company_id:companyId})} onHistory={(resource_id,version_id,known_at)=>setHistory({resource_id,version_id,known_at,company_id:companyId})}/>}<div hidden={nyxTab!=="interact"}><NyxInteraction selectionStatus={trace?undefined:{busy:detailBusy,error:detailError}} companyContext={companyContext} sourceContext={trace?null:sourceContext} token={token} traceActive={Boolean(trace)} traceMessage={traceInspection?.error??(activeTraceSelection?.status==="unselected"?"Select a visible trace object; the previous selection is hidden by the trace filters.":activeTraceSelection?.status==="unavailable"?"Trace context is unavailable. Reopen the exact trace to retry.":"The selected trace version is still being resolved.")} inspection={trace?traceInspection?.inspection??null:selected} onResourceTrace={(resource_id,version_id,known_at)=>setTrace({resource_id,version_id,known_at,company_id:companyId})} onResourceHistory={(resource_id,version_id,known_at)=>setHistory({resource_id,version_id,known_at,company_id:companyId})} mapSelection={trace?null:mapSelection} key={`${token}:${companyId}`} items={items} work={work} context={companyContext?companyNyxCaption(companyContext):`${currentCompany?displayName(currentCompany.display_name):"No company selected"} · ${resolvedContext?readable(resolvedContext.accounting_state):"Company accounting context unresolved"}`} blockers={receipt?.approval_blockers??[]} availability={queuesLoading?"Work queues are refreshing; queue answers use the last loaded snapshot.":[snapshot.evidence.error,snapshot.proposals.error].filter(Boolean).length?"Some work queues are unavailable; this answer is incomplete.":""} onInspect={item=>{void inspectWork(item);setNyxTab("context");}} onData={()=>{setNyxTab("data");setNyxWidth(Math.min(maxNyxWidth,Math.round(viewport*.52)));}} onWork={()=>navigate("home")}/></div>{nyxTab==="data"&&<SourceExplorer key={currentCompany?.resource_id??"rail"} token={token} principal={principal} sources={scopedEvidence} companyId={currentCompany?.resource_id} onInspectResource={reference=>void inspect(reference,reference.version_id)} onTraceResource={reference=>setTrace({...reference,company_id:companyId})} onProposal={openBusinessProposal} onSelect={inspectSource} initialReceiptId={work?.kind==="evidence"?work.id:undefined} onReview={id=>openEngineering("history",id)}/>}<div hidden={nyxTab!=="context"}><Badge>Governed context · AI reasoning not connected</Badge><p className="g8-analyst-intro">Your enterprise context, with the evidence always in reach.</p>{companyContext?<CompanyNyxContextPanel value={companyContext} onTrace={(resource_id,version_id,known_at)=>setTrace({resource_id,version_id,known_at,company_id:companyId})} onHistory={(resource_id,version_id,known_at)=>setHistory({resource_id,version_id,known_at,company_id:companyId})}/>:(<div className="g8-context-note"><small>WORKING CONTEXT</small><strong>{(currentCompany ? displayName(currentCompany.display_name) : undefined) ?? "No company selected"}</strong><span>{currentCompany ? readable(currentCompany.evidence_class) : "Select an accepted company to explore its resources."}</span></div>)}{detailBusy && <p role="status">Loading evidence and impact…</p>}{detailError && <p className="g8-inline-error" role="alert">{detailError}</p>}
      {mapSelection&&<div className="g8-inspector"><p className="overline">MAP SNAPSHOT CONTEXT</p><h3>{displayName(mapSelection.resource.display_name)}</h3><Badge>Definition review: {readable(mapSelection.resource.authority_state)}</Badge><p>{readable(mapSelection.resource.object_type)} · {readable(mapSelection.resource.evidence_class)}</p><dl><dt>Effective snapshot</dt><dd>{new Date(mapSelection.validAt).toLocaleString()}</dd><dt>Known snapshot</dt><dd>{new Date(mapSelection.knownAt).toLocaleString()}</dd></dl><ResourceAuthority token={token} resource={mapSelection.resource} knownAt={mapSelection.knownAt}/><p>Geography is recorded context. Operating condition and impact predictions are not connected.</p><details><summary>Recorded properties & version</summary><dl>{Object.entries(mapSelection.resource.attributes).filter(([key])=>key!=="geometry").map(([key,value])=><div key={key}><dt>{readable(key)}</dt><dd>{typeof value==="object"?JSON.stringify(value):String(value)}</dd></div>)}</dl><small>{mapSelection.resource.version_id}</small></details><button className="g8-panel-action" onClick={()=>navigate("operations")}>Inspect recorded connections<ArrowRight size={15}/></button><button className="g8-link" onClick={clearSelection}>Clear selection</button></div>}
      {selected && <div className="g8-inspector"><p className="overline">RESOURCE CONTEXT</p><h3>{displayName(selected.resource.display_name)}</h3><Badge tone={tone(selected.resource.authority_state)}>Definition review: {readable(selected.resource.authority_state)}</Badge><p>{readable(selected.resource.object_type)} · {readable(selected.resource.evidence_class)}</p><button onClick={()=>setTrace({resource_id:selected.resource.resource_id,version_id:selected.resource.version_id,company_id:companyId,known_at:selected.known_at})}>Show system trace</button><button onClick={()=>setHistory({resource_id:selected.resource.resource_id,version_id:selected.resource.version_id,company_id:companyId,known_at:selected.known_at})}>View history & compare</button>{selected.resource.object_type==="LocalAccount"&&companyId&&<button onClick={()=>setAccountPolicyTarget({companyId,account:selected.resource})}>Review analytical requirements</button>}<ResourceAuthority key={selected.resource.version_id} token={token} resource={selected.resource} knownAt={selected.known_at}/>{typeof selected.resource.attributes.minimum_authority_state==="string"&&<button onClick={()=>{navigate("ontology");setOntologySection("accounting");}}>Calculate with this authority contract</button>}<dl><dt>Effective from</dt><dd>{date(selected.resource.valid_from)}</dd><dt>Known by G8 at</dt><dd>{new Date(selected.known_at).toLocaleString()}</dd><dt>Versions known then</dt><dd>{selected.versions.length}{selected.versions_truncated?"+ (bounded)":""}</dd><dt>Visible dependents</dt><dd>{selected.dependents.length}{selected.dependents_truncated?"+ (bounded)":""}</dd></dl>{selected.dependents.slice(0,8).map(item=><button className="g8-panel-action" key={`${item.version_id}:${item.relation}`} onClick={()=>void inspect({resource_id:item.resource_id},item.version_id,selected.known_at)}>{displayName(item.display_name)}<ArrowRight size={13}/></button>)}<details><summary>Identity & version</summary><small>{selected.resource.resource_id}<br/>{selected.resource.version_id}</small></details><button className="g8-link" onClick={clearSelection}>Clear selection</button></div>}
      {work && items.find(item=>item.id===work.id&&item.kind===work.kind)?.state!==work.state&&<p className="g8-inline-error">The selected work snapshot differs from the latest queue, or is no longer listed. <button className="g8-link" onClick={()=>void inspectWork(items.find(item=>item.id===work.id&&item.kind===work.kind)??work)}>Reload selected evidence</button></p>}
      {work && <div className="g8-inspector"><p className="overline">WHY THIS NEEDS ATTENTION</p><h3>{work.title}</h3><Badge tone={tone(work.state)}>{work.state}</Badge><p>{work.reason}</p>{receipt && <><h3>Review eligibility</h3>{receipt.approval_blockers.length ? receipt.approval_blockers.map(reason=><p className="g8-inline-error" key={reason}>{reason}</p>) : <p>No approval blockers reported. Independent review remains required.</p>}<h3>Proposed object impact</h3><dl>{Object.entries(receipt.impact).map(([key,value])=><div key={key}><dt>{readable(key)}</dt><dd>{value}</dd></div>)}</dl><button className="g8-panel-action" onClick={()=>openEngineering("history",work.id)}>Open evidence & review<ArrowRight size={15}/></button></>}{proposal && <><PromotionReadiness key={proposal.proposal.proposal_id} token={token} proposalId={proposal.proposal.proposal_id} onDecision={detail=>{setProposal(detail);setWork(current=>current?.id===detail.proposal.proposal_id?{...current,state:detail.decision??current.state}:current);refresh();}}/><ProposalImpact validation={proposal.validation}/><button className="g8-panel-action" onClick={()=>openBusinessProposal(work.id)}>Open governed change review<ArrowRight size={15}/></button></>}<button className="g8-link" onClick={clearSelection}>Clear selection</button></div>}
      {!work && !selected && !mapSelection && !detailBusy && <>{!companyContext&&<p>{resolvedContext?`Accounting context: ${resolvedContext.accounting_state.replaceAll("_"," ")} · ${resolvedContext.accounting_sources.length} source scopes · ${resolvedContext.dimensions.length} analytical dimensions`:"Select a company to resolve its canonical context."}</p>}<h3>What needs attention?</h3><p className="g8-subtle">Open a work item to see its reason, source evidence and available review path.</p><button className="g8-panel-action" onClick={()=>{navigate("home");setWorkFilter("pending");}}>Review current work<ArrowRight size={15}/></button><button className="g8-panel-action" onClick={()=>navigate("data")}>Trace source evidence<ArrowRight size={15}/></button><button className="g8-panel-action" onClick={()=>navigate("companies")}>Explore companies<ArrowRight size={15}/></button></>}
      </div></div><footer><ShieldCheck size={17}/><p>Only governed context is shown here. Natural-language analysis is not connected.</p></footer></aside></>
  </div></SourceReviewNavigation.Provider>;
}
