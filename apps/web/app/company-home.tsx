"use client";
import {useEffect,useState} from "react";
import type {AnalysisField,AnalysisValue,CompanyHomeDescriptor} from "@finai/contracts";
import {restorationInstant} from "./definition-restoration-time";
import {assertProjection,formatAnalysisDecimal} from "./semantic-analysis-state";
import {homeAnalysisPins,clearHomeAnalysisPins} from "./company-home-pins";
import {useSourceReview} from "./source-review-navigation";
import OperationsMap from "./operations-map";
import {initialMapState,type MapSelection,type MapWorkspaceState} from "./operations-model";
import {displayName} from "./display-name";
import "./company-home.css";

const human=(value:string)=>value.replaceAll("_"," ").toLowerCase();
const contextValue=(value:string)=>/^(?:[a-f0-9]{64}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})$/i.test(value)?"Exact reference in source review":value;
const stamp=(value:string)=>new Date(value).toLocaleString();
function cell(value:AnalysisValue,field:AnalysisField){
 if(value.state!=="VALUE")return value.state==="NULL"?"Recorded null":"Not recorded";
 if(field.presentation&&typeof value.value==="string")return formatAnalysisDecimal(value.value,field);
 return value.label??String(value.value);
}
type Props={token:string;companyId:string;snapshot?:{validAt:string;knownAt:string};onData:()=>void;onOperations:(state:MapWorkspaceState)=>void;onMapSelection:(selection:MapSelection|null)=>void};
export default function CompanyHome(props:Props){return <Home key={`${props.token}:${props.companyId}:${props.snapshot?.validAt??"current"}:${props.snapshot?.knownAt??"current"}`} {...props}/>;}
function Home({token,companyId,snapshot,onData,onOperations,onMapSelection}:Props){
 const open=useSourceReview();const validAt=snapshot?.validAt,knownAt=snapshot?.knownAt;
 const [result,setResult]=useState<CompanyHomeDescriptor|null>(null),[error,setError]=useState("");
 const [revision,setRevision]=useState(0),[financial,setFinancial]=useState("profit_loss");
 useEffect(()=>{if(!companyId)return;const controller=new AbortController();let disposed=false;const timer=setTimeout(()=>controller.abort(),25000);
  async function load(){try{const invocation_ids=await homeAnalysisPins(token,companyId);const response=await fetch("/api/ontology/company-home",{method:"POST",headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},body:JSON.stringify({company_id:companyId,invocation_ids,...validAt?{valid_at:validAt,known_at:knownAt}:{}}),cache:"no-store",signal:controller.signal});const data=await response.json();if(!response.ok)throw Error(typeof data.detail==="string"?data.detail:"Company Home is unavailable.");const home=data as CompanyHomeDescriptor;
   if(home.contract!=="g8-company-home/1"||home.company.resource_id!==companyId||home.current_use_authorized!==false||home.business_effect_authorized!==false||home.operations.authority!=="GEOGRAPHY_CONTEXT_ONLY"||home.analyses.length!==invocation_ids.length)throw Error("Home did not match the selected company and retained references.");
   if(validAt&&(restorationInstant(home.valid_at)!==restorationInstant(validAt)||restorationInstant(home.known_at)!==restorationInstant(knownAt)))throw Error("Home did not preserve the requested company snapshot.");
   for(const [index,analysis] of home.analyses.entries())assertProjection(analysis,{company_id:companyId,invocation_id:invocation_ids[index]});
   if(!disposed){setResult(home);setError("");}
  }catch(failure){if(!disposed){setResult(null);setError(controller.signal.aborted?"Company Home timed out. Retry the same company context.":String(failure));}}finally{clearTimeout(timer);}}
  void load();return()=>{disposed=true;clearTimeout(timer);controller.abort();};
 },[token,companyId,revision,validAt,knownAt]);
 if(!companyId)return <section className="company-home-state"><h2>Choose your company</h2><p>Financial results, operating context and review work use its canonical identity.</p></section>;
 if(error)return <section className="company-home-state" role="alert"><h2>Company Home unavailable</h2><p>{error}</p><button onClick={()=>setRevision(value=>value+1)}>Retry company Home</button><button onClick={()=>void clearHomeAnalysisPins(token,companyId).then(()=>setRevision(value=>value+1)).catch(failure=>setError(String(failure)))}>Clear saved Home references</button><p>Clearing device references does not delete retained analyses.</p></section>;
 if(!result)return <p role="status">Resolving company capabilities and retained analyses…</p>;
 const unavailable=result.unavailable_financials.find(item=>item.key===financial);
 return <div className="company-home">
  <section className="home-financials" aria-label="Key financials"><header><div><p className="overline">KEY FINANCIALS</p><h2>Financial condition</h2></div><button className="g8-link" onClick={onData}>Explore source analyses</button></header>
   <div className="home-financial-tabs" aria-label="Financial view">{result.unavailable_financials.map(item=><button key={item.key} aria-pressed={financial===item.key} onClick={()=>setFinancial(item.key)}>{item.label}</button>)}</div>
   {unavailable&&<p className="home-dependency"><strong>{unavailable.label} unavailable.</strong> {unavailable.reason}</p>}
   <h3>Retained source analyses</h3><p className="home-scope-note">Each result retains its own financial period, currency and authority. Source movement is not a financial statement.</p>
   {!result.analyses.length?<div className="home-pin-prompt"><p>No analyses pinned for this company. Open a verified source review and choose <strong>Pin to company Home</strong>.</p><button onClick={onData}>Open Data & evidence</button></div>:result.analyses.map(analysis=>{const d=analysis.descriptor;const fields=d.fields.slice(0,4);return <article className="home-analysis" key={d.invocation_id}><header><h3>{d.title}</h3><button onClick={()=>open({companyId,invocationId:d.invocation_id})}>Investigate source review</button></header><div className="home-result-context"><span>{human(d.authority)}</span>{d.context.map((item,index)=><span key={`${item.label}:${index}`}>{item.label}: {contextValue(item.value)}</span>)}</div><div className="home-result-grid"><table><thead><tr>{fields.map(field=><th key={field.key}>{field.label}{field.unit&&<small>{field.unit}</small>}</th>)}</tr></thead><tbody>{analysis.rows.slice(0,6).map(row=><tr key={row.key}>{fields.map(field=><td key={field.key}>{cell(row.values[field.key],field)}</td>)}</tr>)}</tbody></table></div><footer><span>First {Math.min(6,analysis.rows.length)} of {analysis.total_rows} retained rows · Recorded {stamp(d.recorded_at)}</span><details><summary>Coverage & authority</summary>{d.coverage.map((item,index)=><p key={index}>{item.label}: {item.value}</p>)}<p>{d.unavailable_operations.map(human).join(" · ")}</p></details><details><summary>Advanced</summary><p>Descriptor {analysis.descriptor_sha256}</p><p>Receipt {d.receipt_hash}</p><p>Effective {d.valid_at} · known {d.known_at}</p></details></footer></article>;})}
  </section>
  <section className="home-operations" aria-label="Company operations"><header><div><p className="overline">OPERATIONS</p><h2>{result.domain_packs.length?result.domain_packs.map(pack=>displayName(pack.display_name)).join(" · "):"Company operating context"}</h2></div><span className="home-status-neutral">Accepted geography</span></header><p>{result.operations.limitation}</p><HomeMap key={`${companyId}:${result.operations.valid_at}:${result.operations.known_at}`} token={token} companyId={companyId} descriptor={result} onOpen={onOperations} onSelect={onMapSelection}/><p className="home-scope-note">Operations as of {stamp(result.operations.valid_at)} · known {stamp(result.operations.known_at)}. Separate from each financial result’s period.</p></section>
 </div>;
}
function HomeMap({token,companyId,descriptor,onOpen,onSelect}:{token:string;companyId:string;descriptor:CompanyHomeDescriptor;onOpen:(state:MapWorkspaceState)=>void;onSelect:(selection:MapSelection|null)=>void}){
 const [state,setState]=useState<MapWorkspaceState>({...initialMapState,lens:descriptor.operations.lens,validAt:descriptor.operations.valid_at,knownAt:descriptor.operations.known_at});
 return <OperationsMap token={token} companyId={companyId} canPropose={false} state={state} onState={setState} onSelect={onSelect} onReview={()=>{}} compact onOpen={()=>onOpen(state)}/>;
}
