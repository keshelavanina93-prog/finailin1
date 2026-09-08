"use client";
import type {JournalReviewReference} from "./journal-review-handoff";
import {useEffect,useLayoutEffect,useState} from "react";
import type {CompanyHomeDescriptor,CanonicalResource} from "@finai/contracts";
import CompanyChanges from "./company-changes";
import CompanyFinancialContext from "./company-financial-context";
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
type Props={onContext?:(context:CompanyNyxContext)=>void;token:string;companyId:string;snapshot?:{validAt:string;knownAt:string};onData:()=>void;onOperations:(state:MapWorkspaceState)=>void;onMapSelection:(selection:MapSelection|null)=>void;onInspect?:(node:CanonicalResource,knownAt:string)=>void;onAccounting?:(handoff:CompanyAccountingHandoff)=>void;showWork?:boolean;onTrace?:(node:CanonicalResource,knownAt:string)=>void;onHistory?:(node:CanonicalResource,knownAt:string)=>void;onProposal?:(id:string)=>void;onJournalReview?:(reference:JournalReviewReference)=>void;onWorkflow?:(id:string)=>void};
export default function CompanyHome(props:Props){return <Home key={`${props.token}:${props.companyId}:${props.snapshot?.validAt??"current"}:${props.snapshot?.knownAt??"current"}`} {...props}/>;}
function Home({onContext,token,companyId,snapshot,onData,onOperations,onMapSelection,onInspect,onAccounting,showWork=false,onTrace,onHistory,onProposal,onJournalReview,onWorkflow}:Props){
 const [sourcesVisited,setSourcesVisited]=useState(false);const validAt=snapshot?.validAt,knownAt=snapshot?.knownAt;
 const [result,setResult]=useState<CompanyHomeDescriptor|null>(null),[error,setError]=useState("");
 const [revision,setRevision]=useState(0),[financial,setFinancial]=useState("profit_loss");
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
  {showWork&&onInspect&&<CompanyOperatingWorkspace compact token={token} companyId={companyId} snapshot={{validAt:result.valid_at,knownAt:result.known_at}} onInspect={onInspect} onTrace={onTrace} onHistory={onHistory} onProposal={onProposal} onJournalReview={onJournalReview} onWorkflow={onWorkflow}/>}
  {onInspect&&<CompanyChanges compact={showWork} token={token} companyId={companyId} validAt={result.valid_at} knownAt={result.known_at} onInspect={onInspect} onTrace={onTrace}/>}
  <section className="home-financials" aria-label="Key financials"><header><div><p className="overline">KEY FINANCIALS</p><h2>Financial condition</h2></div><button className="g8-link" onClick={onData}>Explore source analyses</button></header>
   <div className="home-journal-facts"><HomeSourceAnalyses projectionGroup="journals" token={token} companyId={companyId} onData={onData}/></div>
   <div className="home-financial-tabs" aria-label="Financial view">{result.unavailable_financials.map(item=><button key={item.key} aria-pressed={financial===item.key} onClick={()=>setFinancial(item.key)}>{item.label}</button>)}</div>
   {unavailable&&<p className="home-dependency"><strong>{unavailable.label} unavailable.</strong> {unavailable.reason}</p>}
   <CompanyFinancialContext context={result.financial_context} knownAt={result.known_at} onInspect={onInspect} onAccounting={onAccounting?()=>onAccounting(companyAccountingHandoff(result)):undefined}/>
   <details className="home-source-analysis-depth" onToggle={event=>{if(event.currentTarget.open)setSourcesVisited(true);}}><summary>Source analysis & supporting evidence</summary>{sourcesVisited&&<HomeSourceAnalyses projectionGroup="sources" token={token} companyId={companyId} onData={onData}/>}</details>
  </section>
  <section className="home-operations" aria-label="Company operations"><header><div><p className="overline">OPERATIONS</p><h2>{result.domain_packs.length?result.domain_packs.map(pack=>displayName(pack.display_name)).join(" · "):"Company operating context"}</h2></div><span className="home-status-neutral">Accepted geography</span></header><p>{result.operations.limitation}</p><HomeMap key={`${companyId}:${result.operations.valid_at}:${result.operations.known_at}`} token={token} companyId={companyId} descriptor={result} onOpen={onOperations} onSelect={onMapSelection}/><p className="home-scope-note">Operations as of {stamp(result.operations.valid_at)} · known {stamp(result.operations.known_at)}. Separate from each financial result’s period.</p></section>
 </div>;
}
function HomeMap({token,companyId,descriptor,onOpen,onSelect}:{token:string;companyId:string;descriptor:CompanyHomeDescriptor;onOpen:(state:MapWorkspaceState)=>void;onSelect:(selection:MapSelection|null)=>void}){
 const [state,setState]=useState<MapWorkspaceState>({...initialMapState,lens:descriptor.operations.lens,validAt:descriptor.operations.valid_at,knownAt:descriptor.operations.known_at});
 return <OperationsMap token={token} companyId={companyId} canPropose={false} state={state} onState={setState} onSelect={onSelect} onReview={()=>{}} compact onOpen={()=>onOpen(state)}/>;
}
