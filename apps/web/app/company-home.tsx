"use client";
import type {CompanyWorkflowReference,JournalReviewReference} from "./journal-review-handoff";
import {useEffect,useLayoutEffect,useState} from "react";
import type {CompanyHomeDescriptor,CanonicalResource} from "@finai/contracts";
import CompanyFinancialMetrics from "./company-financial-metrics";
import CompanyChanges from "./company-changes";
import CompanyFinancialContext from "./company-financial-context";
import RetainedCompanyAnalyses from "./retained-company-analyses";
import HomeSourceAnalyses from "./home-source-analyses";
import CompanyOperatingWorkspace from "./company-operating-workspace";
import {companyNyxContext,type CompanyNyxContext} from "./company-nyx-context";
import {assertHomeFinancialContext} from "./company-home-state";
import {companyAccountingHandoff,type CompanyAccountingHandoff} from "./company-accounting-handoff";
import {restorationInstant} from "./definition-restoration-time";
import OperationsMap from "./operations-map";
import {initialMapState,type MapSelection,type MapWorkspaceState} from "./operations-model";
import {displayName} from "./display-name";
import "./company-home.css";

const stamp=(value:string)=>new Date(value).toLocaleString();
type Props={onInspectReference?:(pin:import("@finai/contracts").AnalysisPin,knownAt:string)=>void;onContext?:(context:CompanyNyxContext)=>void;token:string;companyId:string;snapshot?:{validAt:string;knownAt:string};onData:()=>void;onOperations:(state:MapWorkspaceState,selection?:MapSelection|null)=>void;onMapSelection:(selection:MapSelection|null)=>void;onInspect?:(node:CanonicalResource,knownAt:string)=>void;onAccounting?:(handoff:CompanyAccountingHandoff)=>void;showWork?:boolean;onTrace?:(node:CanonicalResource,knownAt:string)=>void;onHistory?:(node:CanonicalResource,knownAt:string)=>void;onProposal?:(id:string)=>void;onJournalReview?:(reference:JournalReviewReference)=>void;onCompanyWorkflow?:(reference:CompanyWorkflowReference)=>void;onWorkflow?:(id:string)=>void};
export default function CompanyHome(props:Props){return <Home key={`${props.token}:${props.companyId}:${props.snapshot?.validAt??"current"}:${props.snapshot?.knownAt??"current"}`} {...props}/>;}
function Home({onInspectReference,onContext,token,companyId,snapshot,onData,onOperations,onMapSelection,onInspect,onAccounting,showWork=false,onTrace,onHistory,onProposal,onJournalReview,onCompanyWorkflow,onWorkflow}:Props){
 const [sourcesVisited,setSourcesVisited]=useState(false);const validAt=snapshot?.validAt,knownAt=snapshot?.knownAt;
 const [result,setResult]=useState<CompanyHomeDescriptor|null>(null),[error,setError]=useState("");
 const [revision,setRevision]=useState(0),[financial,setFinancial]=useState("accepted_movements");
 const [journalSources,setJournalSources]=useState<unknown>(null);
 const [settledRevision,setSettledRevision]=useState<number|null>(null);
 useLayoutEffect(()=>{onContext?.(companyNyxContext(companyId,result?.company??null,result?.valid_at??"",result?.known_at??"",settledRevision!==revision?"updating":error||!result?"unavailable":"ready"));},[onContext,companyId,result,error,settledRevision,revision]);
 useEffect(()=>{if(!companyId)return;const controller=new AbortController();let disposed=false;const timer=setTimeout(()=>controller.abort(),25000);
  async function load(){try{const response=await fetch("/api/ontology/company-home",{method:"POST",headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},body:JSON.stringify({company_id:companyId,...validAt?{valid_at:validAt,known_at:knownAt}:{}}),cache:"no-store",signal:controller.signal});const data=await response.json();if(!response.ok)throw Error(typeof data.detail==="string"?data.detail:"Company Home is unavailable.");const home=data as CompanyHomeDescriptor;
   if(home.contract!=="g8-company-home/1"||home.company.resource_id!==companyId||home.current_use_authorized!==false||home.business_effect_authorized!==false||home.operations.authority!=="GEOGRAPHY_CONTEXT_ONLY"||home.analyses.length!==0)throw Error("Home did not match the selected company and retained references.");
   if(validAt&&(restorationInstant(home.valid_at)!==restorationInstant(validAt)||restorationInstant(home.known_at)!==restorationInstant(knownAt)))throw Error("Home did not preserve the requested company snapshot.");
   assertHomeFinancialContext(home);
   companyAccountingHandoff(home);
   if(!disposed){setResult(home);setError("");setSettledRevision(revision);}
  }catch(failure){if(!disposed){setResult(null);setSettledRevision(revision);setError(controller.signal.aborted?"Company Home timed out. Retry the same company context.":String(failure));}}finally{clearTimeout(timer);}}
  void load();return()=>{disposed=true;clearTimeout(timer);controller.abort();};
 },[token,companyId,revision,validAt,knownAt]);
 if(!companyId)return <section className="company-home-state"><h2>Choose your company</h2><p>Financial results, operating context and review work use its canonical identity.</p></section>;
 if(error)return <section className="company-home-state" role="alert"><h2>Company Home unavailable</h2><p>{error}</p><button onClick={()=>setRevision(value=>value+1)}>Retry company Home</button></section>;
 if(!result)return <p role="status">Resolving company capabilities and retained analyses…</p>;
 const unavailable=result.unavailable_financials.find(item=>item.key===financial);
 return <div className="company-home">
  <section className="home-financials" data-company-accounting-origin tabIndex={-1} aria-label="Key financials"><header><div><p className="overline">KEY FINANCIALS</p><h2>Financial condition</h2></div><button className="g8-link" onClick={onData}>Explore source analyses</button></header>
   <div className="home-financial-tabs" aria-label="Financial view"><button aria-pressed={financial==="accepted_movements"} onClick={()=>setFinancial("accepted_movements")}>Accepted movements</button>{result.unavailable_financials.map(item=><button key={item.key} aria-pressed={financial===item.key} onClick={()=>setFinancial(item.key)}>{item.label}</button>)}</div>
   {financial==="accepted_movements"&&<CompanyFinancialMetrics onInspectReference={onInspectReference} onProposal={onProposal} token={token} companyId={companyId} reviews={journalSources} onData={onData}/>}
   {unavailable&&<p className="home-dependency"><strong>{unavailable.label} unavailable.</strong> {unavailable.reason}</p>}
   <details className="home-accounting-depth"><summary>Accounting context & source readiness</summary><CompanyFinancialContext context={result.financial_context} knownAt={result.known_at} onInspect={onInspect} onAccounting={onAccounting?()=>onAccounting(companyAccountingHandoff(result)):undefined}/></details>
   <details className="home-source-analysis-depth" onToggle={event=>{if(event.currentTarget.open)setSourcesVisited(true);}}><summary>Source analysis & supporting evidence</summary>{sourcesVisited&&<><RetainedCompanyAnalyses token={token} companyId={companyId}/><HomeSourceAnalyses projectionGroup="sources" token={token} companyId={companyId} onData={onData}/></>}</details>
  </section>
  <section className="home-operations" data-company-map-origin tabIndex={-1} aria-label="Company operations"><header><div><p className="overline">OPERATIONS</p><h2>{result.domain_packs.length?result.domain_packs.map(pack=>displayName(pack.display_name)).join(" · "):"Company operating context"}</h2></div><span className="home-status-neutral">Accepted geography</span></header><p>{result.operations.limitation}</p><HomeMap key={`${companyId}:${result.operations.valid_at}:${result.operations.known_at}`} token={token} companyId={companyId} descriptor={result} onOpen={onOperations} onSelect={onMapSelection}/><p className="home-scope-note">Operations as of {stamp(result.operations.valid_at)} · known {stamp(result.operations.known_at)}. Separate from each financial result’s period.</p></section>
  <div className="home-work-depth">{showWork&&onInspect&&<CompanyOperatingWorkspace compact onJournalSources={setJournalSources} token={token} companyId={companyId} snapshot={{validAt:result.valid_at,knownAt:result.known_at}} onInspect={onInspect} onTrace={onTrace} onHistory={onHistory} onProposal={onProposal} onJournalReview={onJournalReview} onCompanyWorkflow={onCompanyWorkflow} onWorkflow={onWorkflow}/>}</div>
  <details className="home-changes-depth"><summary>Changes in retained company evidence</summary>{onInspect&&<CompanyChanges compact={showWork} token={token} companyId={companyId} validAt={result.valid_at} knownAt={result.known_at} onInspect={onInspect} onTrace={onTrace}/>}</details>
 </div>;
}
function HomeMap({token,companyId,descriptor,onOpen,onSelect}:{token:string;companyId:string;descriptor:CompanyHomeDescriptor;onOpen:(state:MapWorkspaceState,selection?:MapSelection|null)=>void;onSelect:(selection:MapSelection|null)=>void}){
 const [selection,setSelection]=useState<MapSelection|null>(null);
 const [state,setState]=useState<MapWorkspaceState>({...initialMapState,lens:descriptor.operations.lens,validAt:descriptor.operations.valid_at,knownAt:descriptor.operations.known_at});
 return <OperationsMap token={token} companyId={companyId} canPropose={false} state={state} onState={setState} selection={selection} onSelect={value=>{setSelection(value);onSelect(value);}} onReview={()=>{}} compact onOpen={()=>onOpen(state,selection)}/>;
}
