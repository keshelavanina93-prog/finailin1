"use client";

import {useEffect,useMemo,useRef,useState,type ComponentProps} from "react";
import type {CanonicalResource,ObjectSetQuery,ObjectSetResult,SchemaField} from "@finai/contracts";
import {createOntologyClient} from "@g8/ontology-client";
import ObjectSets from "./object-sets";
import AnalysisSourceEvidence from "./analysis-source-evidence";
import {Badge,Empty} from "./g8-ui";
import {compileAnalysis,emptySelection,type AnalysisSelection} from "./finance-analysis-query";
import "./finance-analysis.css";

type Props=ComponentProps<typeof ObjectSets>&{companyId:string;companyName:string};
const human=(value:string)=>value.toLowerCase().replaceAll("_"," ");
const text=(value:unknown)=>typeof value==="string"?value:"Not established";
const accountLabel=(resource:CanonicalResource)=>resource.display_name.startsWith(`${text(resource.attributes.account_code)} ·`)?resource.display_name:`${text(resource.attributes.account_code)} · ${resource.display_name}`;
export default function FinanceAnalysis(props:Props){return <Analysis key={`${props.companyId}:${props.token}`} {...props}/>;}
function Analysis({companyId,companyName,token,viewStateKey,onInspect,onHistory,onTrace,onProposal}:Props){
  const client=useMemo(()=>createOntologyClient({baseUrl:"/api/ontology",getToken:()=>token}),[token]);
  const storageKey=`${viewStateKey}:finance`;
  const [restored]=useState(()=>{try{
    const raw=sessionStorage.getItem(storageKey);if(!raw||raw.length>16000)return null;
    const value=JSON.parse(raw);
    if(value?.companyId!==companyId||value.query?.object_type!=="SourceJournalMovement"||value.query.traversal?.length!==0||!value.query.filters?.some((filter:{field:string;value:unknown})=>filter.field==="legal_entity_id"&&filter.value===companyId))return null;
    if(!value.selection||!["either","debit","credit"].includes(value.selection.side)||!["account","from","to","minimum","maximum"].every(key=>typeof value.selection[key]==="string"))return null;
    return value;
  }catch{return null;}});
  const [selection,setSelection]=useState<AnalysisSelection>(restored?.selection??emptySelection);
  const [catalog,setCatalog]=useState<CanonicalResource[]>([]);
  const [accounts,setAccounts]=useState<CanonicalResource[]>([]);
  const [accountPage,setAccountPage]=useState<ObjectSetResult|null>(null);
  const [result,setResult]=useState<ObjectSetResult|null>(null);
  const [error,setError]=useState("");const [lookupError,setLookupError]=useState("");
  const [busy,setBusy]=useState(Boolean(restored));const [lookupBusy,setLookupBusy]=useState(true);
  const [revision,setRevision]=useState(0);const [advanced,setAdvanced]=useState(false);
  const [selected,setSelected]=useState<string>(restored?.selected??"");
  const [evidenceRow,setEvidenceRow]=useState<CanonicalResource|null>(null);
  const [applied,setApplied]=useState<AnalysisSelection|null>(restored?.selection??null);
  const request=useRef<AbortController|null>(null);const scroll=useRef<HTMLDivElement>(null);
  const studioKey=`${storageKey}:studio`;
  const fields=(catalog.find(item=>item.identity_key==="SourceJournalMovement")?.attributes.fields??{}) as Record<string,SchemaField>;
  useEffect(()=>{
    const controller=new AbortController();
    async function load(){
      try{
        const response=await fetch("/api/ontology/catalog",{headers:{Authorization:`Bearer ${token}`},signal:controller.signal});
        if(!response.ok)throw Error(response.status===403?"You do not have access to this company’s analysis resources.":`Analysis resources unavailable (${response.status}).`);
        const definitions=await response.json();if(!Array.isArray(definitions))throw Error("Analysis definitions unavailable.");
        setCatalog(definitions);
        const base:ObjectSetQuery={object_type:"LocalChartOfAccounts",search:"",filters:[{field:"legal_entity_id",value:companyId}],traversal:[],offset:0,limit:100};
        const charts=await client.query(base,{signal:controller.signal});
        if(charts.next_offset!==null)throw Error("Company account charts exceed this selector’s supported range. Account selection is unavailable.");
        const page=await client.query({...base,object_type:"LocalAccount",filters:[],resource_ids:charts.objects.length?undefined:[],...(charts.objects.length?{filters:[{field:"chart_id",operator:"in" as const,value:charts.objects.map(item=>item.resource_id)}]}:{}),valid_at:charts.query.valid_at,known_at:charts.query.known_at,limit:200},{signal:controller.signal});
        if(!controller.signal.aborted){setAccounts(page.objects);setAccountPage(page);setLookupError("");}
      }catch(cause){if(!controller.signal.aborted)setLookupError(cause instanceof Error?cause.message:"Account choices unavailable.");}
      finally{if(!controller.signal.aborted)setLookupBusy(false);}
    }
    if(companyId)void load();
    return()=>controller.abort();
  },[client,token,companyId,revision]);
  useEffect(()=>{
    if(!restored?.query)return;
    const controller=new AbortController();request.current=controller;
    // Revalidate access through the canonical client. Never display cached result rows.
    void client.query(restored.query,{signal:controller.signal}).then(data=>{if(!controller.signal.aborted)setResult(data);}).catch(cause=>{if(!controller.signal.aborted)setError(String(cause));}).finally(()=>{if(!controller.signal.aborted)setBusy(false);});
    return()=>controller.abort();
  },[client,restored]);
  useEffect(()=>()=>request.current?.abort(),[]);
  useEffect(()=>{
    if(!result||!applied)return;
    try{sessionStorage.setItem(storageKey,JSON.stringify({companyId,selection:applied,query:result.query,selected,scroll:scroll.current?.scrollTop??0}));}catch{/* Results stay usable without browser storage. */}
  },[result,applied,selected,companyId,storageKey]);
  useEffect(()=>{if(result&&scroll.current&&restored)scroll.current.scrollTop=restored.scroll??0;},[result,restored]);
  async function execute(query:ObjectSetQuery,chosen=selection){
    request.current?.abort();const controller=new AbortController();request.current=controller;
    setBusy(true);setError("");setResult(null);
    try{const data=await client.query(query,{signal:controller.signal});if(!controller.signal.aborted){setResult(data);setApplied({...chosen});}}
    catch(cause){if(!controller.signal.aborted)setError(cause instanceof Error?cause.message:"Analysis unavailable.");}
    finally{if(!controller.signal.aborted)setBusy(false);}
  }
  function apply(){try{const query=compileAnalysis(companyId,selection,fields);setSelected("");void execute(query);}catch(cause){setError(String(cause));}}
  function openStudio(){
    if(!result)return;
    try{sessionStorage.setItem(studioKey,JSON.stringify({query:result.query,family:null}));setAdvanced(true);}catch{setError("Browser storage is unavailable. The exact query remains inspectable below.");}
  }
  function evidence(resource:CanonicalResource){
    setSelected(resource.version_id);
    setEvidenceRow(resource);
  }
  async function moreAccounts(){
    if(!accountPage||accountPage.next_offset===null)return;
    setLookupBusy(true);
    try{const page=await client.query({...accountPage.query,offset:accountPage.next_offset});setAccounts(previous=>[...previous,...page.objects]);setAccountPage(page);}
    catch(cause){setLookupError(String(cause));}finally{setLookupBusy(false);}
  }
  const names=new Map(accounts.map(item=>[item.resource_id,accountLabel(item)]));
  const changed=applied&&JSON.stringify(applied)!==JSON.stringify(selection);
  if(!companyId)return <Empty title="Choose a company">Select a company to explore its account contributors.</Empty>;
  return <section className="finance-analysis" aria-label="Financial contributor analysis">
    <header><div><p className="overline">{companyName}</p><h2>Account contributors</h2><p>Investigate retained source movements by account and posting date.</p></div><Badge tone="warning">Source observations</Badge></header>
    <p className="g8-subtle">Amounts are transcribed source values. Currency, accounting eligibility and report totals are not established by this view. No variance or certified financial result is inferred.</p>
    <div hidden={advanced||Boolean(evidenceRow)}>
      <form className="finance-analysis-filters" onSubmit={event=>{event.preventDefault();apply();}}>
        <label>Account<select value={selection.account} disabled={lookupBusy||Boolean(lookupError)} onChange={event=>setSelection({...selection,account:event.target.value})}><option value="">All company accounts</option>{selection.account&&!names.has(selection.account)&&<option value={selection.account}>Previously selected account · loading label</option>}{accounts.map(account=><option key={account.version_id} value={account.resource_id}>{accountLabel(account)}</option>)}</select></label>
        <label>Side<select value={selection.side} disabled={!selection.account} onChange={event=>setSelection({...selection,side:event.target.value as AnalysisSelection["side"]})}><option value="either">Debit or credit</option><option value="debit">Debit</option><option value="credit">Credit</option></select></label>
        <label>From<input type="date" value={selection.from} onChange={event=>setSelection({...selection,from:event.target.value})}/></label>
        <label>Through<input type="date" value={selection.to} onChange={event=>setSelection({...selection,to:event.target.value})}/></label>
        {fields.amount?.kind==="decimal"&&<><label>Minimum source amount<input inputMode="decimal" value={selection.minimum} onChange={event=>setSelection({...selection,minimum:event.target.value})}/></label><label>Maximum source amount<input inputMode="decimal" value={selection.maximum} onChange={event=>setSelection({...selection,maximum:event.target.value})}/></label></>}
        <button disabled={busy||lookupBusy||Boolean(lookupError)||!fields.legal_entity_id}>{busy?"Reading contributors…":"Apply filters"}</button>
      </form>
      {lookupBusy&&<p role="status">Loading company account choices…</p>}
      {lookupError&&<p role="alert">{lookupError} <button onClick={()=>{setLookupBusy(true);setRevision(value=>value+1);}}>Retry account choices</button></p>}
      {accountPage?.next_offset!==null&&accountPage&&<button disabled={lookupBusy} onClick={()=>void moreAccounts()}>Load more account choices ({accounts.length} of {accountPage.total})</button>}
      {changed&&<p role="status">Filters changed. Apply filters to update the contributors below.</p>}
      {error&&<p role="alert">{error}</p>}
      {busy&&<p role="status">Reading the selected company’s source evidence…</p>}
      {!result&&!busy&&!error&&<Empty title="Explore account contributors">Choose an account or apply all company accounts to begin.</Empty>}
      {result&&<><div className="finance-analysis-summary"><strong>{result.total} contributors</strong><span>{applied?.account?names.get(applied.account)??"Retained account selection":"All company accounts"} · {applied?.side==="either"?"Debit or credit":applied?.side} · {applied?.from||"All dates"}{applied?.to?` through ${applied.to}`:""}</span><small>As read {new Date(result.query.known_at!).toLocaleString()}</small></div>
        {!result.objects.length?<Empty title="No contributors match">This selection returned no source movements. It does not establish a zero accounting balance.</Empty>:<div className="finance-analysis-table" ref={scroll} onScroll={()=>{try{const saved=JSON.parse(sessionStorage.getItem(storageKey)??"null");if(saved)sessionStorage.setItem(storageKey,JSON.stringify({...saved,scroll:scroll.current?.scrollTop??0}));}catch{/* Optional persistence. */}}}><table><thead><tr><th>Source / document</th><th>Posting date</th><th>Debit account</th><th>Credit account</th><th>Source amount</th><th>Evidence / status</th></tr></thead><tbody>{result.objects.map(resource=><tr key={resource.version_id} aria-selected={selected===resource.version_id}><th scope="row">{text(resource.attributes.document_reference)}<small>{resource.display_name}</small></th><td>{text(resource.attributes.posting_date)}</td><td>{names.get(text(resource.attributes.debit_account_id))??"Account label unavailable"}</td><td>{names.get(text(resource.attributes.credit_account_id))??"Account label unavailable"}</td><td className="amount">{text(resource.attributes.amount)}<small>Unit {human(text(resource.attributes.unit_status))}</small></td><td><Badge>{human(resource.evidence_class)}</Badge><small>Definition {human(resource.authority_state)}</small><button onClick={()=>evidence(resource)} disabled={!onTrace}>Source evidence</button>{onInspect&&<button onClick={()=>{setSelected(resource.version_id);onInspect(resource,{known_at:result.query.known_at!,valid_at:result.query.valid_at!});}}>Investigate in NYX</button>}</td></tr>)}</tbody></table></div>}
        <footer><button disabled={busy||result.query.offset===0} onClick={()=>void execute({...result.query,offset:Math.max(0,result.query.offset-result.query.limit)},applied!)}>Previous</button><span>{result.objects.length?result.query.offset+1:0}–{result.query.offset+result.objects.length} of {result.total}</span><button disabled={busy||result.next_offset===null} onClick={()=>void execute({...result.query,offset:result.next_offset!},applied!)}>Next</button></footer>
        <details><summary>Show system query</summary><p>The exact request is executed by the shared Object Set client. The same snapshot opens in Ontology Studio, including its filters and version evidence.</p><pre>{JSON.stringify({query:result.query,filter_schema_versions:result.filter_schema_versions},null,2)}</pre><button onClick={openStudio}>Open same query in Ontology Studio</button></details>
      </>}
    </div>
    {evidenceRow&&result&&<AnalysisSourceEvidence token={token} movement={evidenceRow} knownAt={result.query.known_at!} onClose={()=>{setEvidenceRow(null);requestAnimationFrame(()=>scroll.current?.querySelector<HTMLButtonElement>('tr[aria-selected="true"] button')?.focus({preventScroll:true}));}} onTrace={()=>onTrace?.(evidenceRow,{known_at:result.query.known_at!,valid_at:result.query.valid_at!})}/>}
    {advanced&&<section aria-label="Advanced Ontology Studio"><button onClick={()=>setAdvanced(false)}>Return to account contributors</button><p>Advanced query construction. Changes here do not alter the retained analyst selection.</p><ObjectSets token={token} catalog={catalog} viewStateKey={studioKey} onInspect={onInspect} onHistory={onHistory} onTrace={onTrace} onProposal={onProposal}/></section>}
  </section>;
}
