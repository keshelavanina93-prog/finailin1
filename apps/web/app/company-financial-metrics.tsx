"use client";
import {AcceptedMovementMetricReview} from "./metric-observation-review";
import {CaretDown,CaretRight} from "@phosphor-icons/react";
import {useEffect,useMemo,useRef,useState} from "react";
import type {AnalysisProjection,FinancialMetricResult} from "@finai/contracts";
import {companyJournalAnalysisEntries} from "./company-journal-analysis-entry-state";
import {homeAnalysisReferences,subscribeHomeAnalysisPins} from "./company-home-pins";
import {assertHomeRevision,homeAnalysisRequest,type HomeAnalysisReference} from "./company-home-revision";
import {assertProjection,formatAnalysisDecimal} from "./semantic-analysis-state";
import {assertProjectionTransport,projectionEndpoint} from "./analysis-projection-identity";
import {assertHomeFinancialMetrics} from "./company-financial-metric-state";
import {homeAnalysisRowTarget} from "./home-analysis-row";
import {displayedAnalysisView} from "./source-review-route";
import {useSourceReview} from "./source-review-navigation";

type Choice={key:string;invocation:string;snapshot:string;label:string;reference?:HomeAnalysisReference};
type Loaded={key:string;metrics:FinancialMetricResult;projection:AnalysisProjection;reference:HomeAnalysisReference};
const stamp=(s:string)=>new Date(s).toLocaleString();
export default function CompanyFinancialMetrics({token,companyId,reviews,onData}:{token:string;companyId:string;reviews:unknown;onData:()=>void}){
 const open=useSourceReview(),[pins,setPins]=useState<HomeAnalysisReference[]>([]),[pinError,setPinError]=useState("");
 const [selected,setSelected]=useState(""),[loaded,setLoaded]=useState<Loaded|null>(null),[error,setError]=useState(""),[busy,setBusy]=useState(false),[revision,setRevision]=useState(0),[expanded,setExpanded]=useState(true),[search,setSearch]=useState(""),[page,setPage]=useState(0);
 const expectedMetric=useRef<{key:string;hash:string}|null>(null);
 useEffect(()=>{let disposed=false;const unsubscribe=subscribeHomeAnalysisPins(token,companyId,()=>{void homeAnalysisReferences(token,companyId).then(value=>{if(!disposed){setPins(value);setPinError("");}}).catch(()=>{if(!disposed){setPins([]);setPinError("Saved financial references could not be read.");}});},()=>{if(!disposed)setPinError("Saved financial references could not be read.");});return()=>{disposed=true;unsubscribe();};},[token,companyId]);
 const discovery=useMemo(()=>{if(!reviews)return {entries:null,error:""};try{return {entries:companyJournalAnalysisEntries(reviews,companyId),error:""};}catch{return {entries:null,error:"Accepted journal source discovery is unavailable."};}},[reviews,companyId]);
 const choices=useMemo(()=>{const result:Choice[]=pins.flatMap(reference=>reference.kind==="EXACT"&&reference.journalSnapshot?[{key:`${reference.invocationId}:${reference.journalSnapshot}`,invocation:reference.invocationId,snapshot:reference.journalSnapshot,label:`Pinned journal snapshot · ${stamp(reference.journalSnapshot)}`,reference}]:[]);
  for(const source of discovery.entries?.sources??[]){const snapshot=discovery.entries!.observedAt,key=`${source.invocationId}:${snapshot}`;if(!result.some(c=>c.key===key))result.push({key,invocation:source.invocationId,snapshot,label:source.title||"Accepted journal source"});}return result;
 },[pins,discovery.entries]);
 const choice=choices.find(c=>c.key===selected)??(!selected&&choices.length===1?choices[0]:null);
 useEffect(()=>{const controller=new AbortController();let disposed=false;const timer=setTimeout(()=>controller.abort(),25000);
  async function load(){setLoaded(null);setError("");if(!choice){setBusy(false);return;}setBusy(true);
   try{const request=choice.reference?homeAnalysisRequest(choice.reference,companyId):{company_id:companyId,invocation_id:choice.invocation};
    const response=await fetch(projectionEndpoint(choice.snapshot),{method:"POST",headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},body:JSON.stringify(request),cache:"no-store",signal:controller.signal});
    const projection=await response.json();if(!response.ok)throw Error("Accepted movements could not be resolved for this source and snapshot.");assertProjection(projection,request);assertProjectionTransport(projection,choice.snapshot);if(choice.reference)assertHomeRevision(projection,choice.reference);
    const metricRequest={company_id:companyId,invocation_id:choice.invocation,snapshot_at:choice.snapshot,expected_reconciliation_sha256:projection.descriptor.receipt_hash,...(expectedMetric.current?.key===choice.key?{expected_result_sha256:expectedMetric.current.hash}:{})};
    const metricResponse=await fetch("/api/ontology/company-journals/reconciliation/metrics",{method:"POST",headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},body:JSON.stringify(metricRequest),cache:"no-store",signal:controller.signal});
    const metrics=await metricResponse.json();if(!metricResponse.ok)throw Error(metricResponse.status===409?"This financial revision changed. Its prior result is withheld; reopen the exact source review.":"Financial movement metrics are unavailable for this selected source.");assertHomeFinancialMetrics(metrics,metricRequest,projection);
    const d=projection.descriptor,reference:HomeAnalysisReference={kind:"EXACT",invocationId:choice.invocation,journalSnapshot:choice.snapshot,revision:{descriptorSha256:projection.descriptor_sha256,receiptHash:d.receipt_hash,validAt:d.valid_at,knownAt:d.known_at}};
    if(!disposed){expectedMetric.current={key:choice.key,hash:metrics.result_sha256};setLoaded({key:choice.key,metrics,projection,reference});}
   }catch(failure){if(!disposed)setError(controller.signal.aborted?"Financial movement read timed out. Retry the same snapshot.":failure instanceof Error?failure.message:"Financial movements are unavailable.");}finally{clearTimeout(timer);if(!disposed)setBusy(false);}}
  void load();return()=>{disposed=true;controller.abort();clearTimeout(timer);};
 },[token,companyId,choice,revision]);
 const shown=loaded?.key===choice?.key?loaded:null;
 function review(rowKey?:string){const loaded=shown;if(!loaded)return;try{if(rowKey){const target=homeAnalysisRowTarget(loaded.projection,loaded.reference,companyId,rowKey);if(!target)throw Error("No retained contributor is available for this account.");open(target);}else open({companyId,invocationId:loaded.metrics.invocation_id,journalSnapshot:loaded.metrics.snapshot_at,view:displayedAnalysisView(loaded.projection,companyId,loaded.metrics.snapshot_at)});}catch(failure){setError(failure instanceof Error?failure.message:"Exact source review is unavailable.");}}
 const result=shown?.metrics,root=result?.nodes[0],children=result?.nodes.slice(1).filter(n=>`${n.account_code??""} ${n.label}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()))??[];
 const currentPage=Math.min(page,Math.max(0,Math.ceil(children.length/6)-1));
 return <div className="home-financial-metrics">
  <div className="home-financial-controls"><label>Journal source<select value={choice?.key??""} onChange={e=>{setSelected(e.target.value);setSearch("");setPage(0);}}><option value="">Choose an accepted source</option>{choices.map(c=><option key={c.key} value={c.key}>{c.label}</option>)}</select></label>{choice&&<button onClick={()=>setRevision(v=>v+1)}>Refresh exact snapshot</button>}</div>
  {(pinError||discovery.error)&&<p role="status" className="home-dependency">{pinError||discovery.error}</p>}
  {!choice&&!busy&&<p className="home-metric-missing">{reviews===null?"Resolving accepted company journal sources…":selected?"The selected source is no longer in the returned collection. Choose explicitly; no replacement was selected.":choices.length?"Select a source and fixed journal snapshot to inspect financial movements.":"No accepted journal source is available in this bounded company review collection."} <button className="g8-link" onClick={onData}>Review source evidence</button></p>}
  {busy&&<p role="status">Resolving accepted financial movements…</p>}{error&&<p role="alert" className="home-dependency">{error}</p>}
  {shown&&result&&root&&<><div className="home-metric-context"><strong>Accepted movements</strong><span>{result.definitions[0]?.unit_label??"Currency label unavailable"}</span><span>{result.coverage.state==="RECONCILED"?"Eligible source reconciled":result.coverage.state==="PARTIAL"?"Partial source coverage":"No accepted values"}</span><span>Observed {stamp(result.snapshot_at)}</span></div>
   <dl className="home-metric-book-context">{([["period_id","Period"],["ledger_id","Ledger"],["book_id","Book"]] as const).map(([key,label])=><div key={key}><dt>{label}</dt><dd>{result.display_context?.[key]?.label??"Label unavailable"}</dd></div>)}</dl>
   <label className="home-account-search">Find contributing account<input value={search} onChange={e=>{setSearch(e.target.value.slice(0,200));setPage(0);}} placeholder="Account code or description" maxLength={200}/></label>
   <div className="home-result-grid"><table><caption>Company movements and contributing accounts · values are not additive across hierarchy levels</caption><thead><tr><th>Account / company</th>{result.definitions.map(d=><th key={d.code} data-numeric="true">{d.label.replace("Accepted ","")}</th>)}</tr></thead><tbody>{[root,...(expanded?children.slice(currentPage*6,(currentPage+1)*6):[])].map(node=><tr key={node.key} className={node===root?"home-metric-root":"home-metric-account"}><th scope="row">{node===root?<button aria-expanded={expanded} onClick={()=>setExpanded(v=>!v)}>{expanded?<CaretDown size={12} aria-hidden/>:<CaretRight size={12} aria-hidden/>}{node.label}</button>:<button onClick={()=>review(node.analysis_row_key??undefined)}><span className="home-account-code">{node.account_code}</span><span>{node.label}</span></button>}</th>{result.definitions.map(d=>{const v=node.metrics[d.code],field=shown.projection.descriptor.fields.find(f=>f.key===d.code);return <td key={d.code} data-numeric="true">{v.state==="UNAVAILABLE"?"Unavailable":field?formatAnalysisDecimal(v.value,field):v.value}</td>;})}</tr>)}</tbody></table></div>
   {expanded&&children.length>6&&<nav className="home-account-pages" aria-label="Contributing accounts"><button disabled={currentPage===0} onClick={()=>setPage(currentPage-1)}>Previous accounts</button><span>{currentPage*6+1}–{Math.min((currentPage+1)*6,children.length)} of {children.length} matching accounts</span><button disabled={(currentPage+1)*6>=children.length} onClick={()=>setPage(currentPage+1)}>Next accounts</button></nav>}
   <footer className="home-metric-footer"><span>{result.coverage.accepted_journals} accepted journals · {result.coverage.unmatched_source_rows} unmatched source rows · {result.coverage.excluded_source_rows} excluded</span><button className="g8-link" onClick={()=>review()}>Open financial source review</button></footer>
   <p className="home-scope-note">Accepted movements only. Opening/closing balances and financial statements are not established.</p><details className="home-metric-provenance"><summary>Advanced · exact authority, coverage and revision</summary><p>Code-defined movement recipe; no new canonical MetricDefinition has been published.</p><pre>{JSON.stringify({selection:result.selection,display_context:result.display_context,binding:result.binding,source_function:result.source_function,definitions:result.definitions,coverage:result.coverage,result_sha256:result.result_sha256,implementation_sha256:result.implementation_sha256,reconciliation_receipt_hash:result.reconciliation_receipt_hash,journals:result.journals},null,2)}</pre></details>
   <AcceptedMovementMetricReview token={token} companyId={companyId} metrics={result} projection={shown.projection} onSource={()=>review()}/>
  </>}
 </div>;
}
