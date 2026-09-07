"use client";
import {useCallback,useEffect,useRef,useState} from "react";
import type {CanonicalResource} from "@finai/contracts";
import RetainedBindingAction from "./retained-binding-action";
import WorksheetAnalysisResult,{type WorksheetResult} from "./worksheet-analysis-result";
import {displayName} from "./display-name";
import "./saved-analysis-workbench.css";
type Pin={resource_id:string;version_id:string};
type SavedFunction={reference:Pin;display_name:string;attributes:Record<string,unknown>;content_hash:string};
type Request={input_result?:{invocation_id:string};request_id:string;function:Pin;valid_at:string;known_at:string;offset:number;limit:number};
type GroupCounts={contract:"grouped-observation-counts/1";authority:"OBSERVATION_COUNTS_ONLY";coverage:"COMPLETE_BOUNDED_OBJECT_SET";schema:Pin&{content_hash:string};fields:string[];object_count:number;groups:Array<{key:Array<{field:string;state:"MISSING"|"NULL"|"VALUE";value?:string|number|boolean}>;count:number;contributors:Array<Pin&{content_hash:string}>}>};
type SourceResult = {invocation_id:string;receipt_hash:string;run_id:string};
type DerivedValue = {
 object_id:string;object_version_id:string;definition_id?:string;definition_version_id:string;
 name:string;kind?:"text"|"decimal";value:string|number|null;status:string;reason?:string;source_result?:SourceResult;
 source_fields?:unknown[];dependency_values?:DerivedValue[];
};
type ConsumedProperty = DerivedValue & {
 definition_id:string;content_hash:string;schema:Pin&{content_hash:string};
 kind:"text"|"decimal";epistemic_state:"DERIVED";source_result:SourceResult;
};
type BaseOutput={consumed_property_values?:ConsumedProperty[];group_counts?:GroupCounts;input_result?:{invocation_id:string;receipt_hash:string;run_id:string};run_id:string;contract:"function-result/1";function:Pin;mode:"EVIDENCE_ANALYSIS_ONLY";coverage:"QUERY_PAGE_ONLY"|"REVIEWED_WORKSHEET_PAGE_ONLY"|"RETAINED_INPUT_PAGE_ONLY";current_use_authorized:false;business_effect_authorized:false;invocation_request_id:string;query:{valid_at:string;known_at:string;offset:number;limit:number};objects:CanonicalResource[];total:number;next_offset:number|null;derived_values:DerivedValue[]};
type Output=BaseOutput&Partial<Omit<WorksheetResult,"coverage">>;
function worksheet(output:BaseOutput):output is BaseOutput&WorksheetResult{return output.coverage==="REVIEWED_WORKSHEET_PAGE_ONLY"&&"temporal_semantics" in output&&output.temporal_semantics==="IMMUTABLE_RETAINED_SNAPSHOT_NOT_VALID_TIME_FACTS"&&"authority" in output&&output.authority==="SOURCE_CELLS_ONLY"&&"source_rows" in output&&Array.isArray(output.source_rows)&&"source_document" in output&&typeof output.source_document==="object"&&output.source_document!==null&&"source_query" in output&&typeof output.source_query==="object"&&output.source_query!==null;}
function retainedInput(output:BaseOutput):boolean {return output.coverage==="RETAINED_INPUT_PAGE_ONLY"&&Array.isArray(output.objects)&&Array.isArray(output.derived_values)&&!!output.input_result&&/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(output.input_result.invocation_id)&&/^[a-f0-9]{64}$/.test(output.input_result.receipt_hash)&&/^fcr_[a-f0-9]{64}$/.test(output.input_result.run_id);}
type Invocation={invocation_id:string;status:"SUCCEEDED"|"FAILED"|"INTENT_RETAINED";receipt_hash:string|null;receipt:{request?:Request;recorded_at?:string;failure_code?:string};output:Output|null;current_use_authorized:false;business_effect_authorized:false};
type Props={onProposal?:(id:string)=>void;initialInvocationId?:string;token:string;companyName:string;onInspect:(resource:CanonicalResource,knownAt:string)=>void;onTrace:(resource:CanonicalResource,knownAt:string)=>void};
export default function SavedAnalysisWorkbench(props:Props){return <Workbench key={`${props.token}:${props.initialInvocationId??""}`} {...props}/>;}
function Workbench({initialInvocationId,token,companyName,onInspect,onTrace,onProposal}:Props){
 const [library,setLibrary]=useState<SavedFunction[]>([]);const [after,setAfter]=useState<string|null>(null);const [next,setNext]=useState<string|null>(null);const [libraryRevision,setLibraryRevision]=useState(0);const [libraryBusy,setLibraryBusy]=useState(true);const [libraryError,setLibraryError]=useState("");
 const [selected,setSelected]=useState("");const [validAt,setValidAt]=useState(()=>new Date().toISOString());const [knownAt,setKnownAt]=useState(()=>new Date().toISOString());
 const [request,setRequest]=useState<Request|null>(null);const [result,setResult]=useState<Invocation|null>(null);const [saved,setSaved]=useState("");const [busy,setBusy]=useState(Boolean(initialInvocationId));const [error,setError]=useState("");const pending=useRef<AbortController|null>(null);
 useEffect(()=>()=>{pending.current?.abort();pending.current=null;},[]);
 useEffect(()=>{const controller=new AbortController();let disposed=false;const timer=setTimeout(()=>controller.abort(),20000);
  async function load(){setLibraryBusy(true);setLibraryError("");try{const response=await fetch(`/api/ontology/functions${after?`?after_resource_id=${encodeURIComponent(after)}`:""}`,{headers:{Authorization:`Bearer ${token}`},cache:"no-store",signal:controller.signal});if(!response.ok)throw new Error("Saved analyses are unavailable in your authorized scope.");const data:{items:SavedFunction[];next_cursor:string|null;purpose:string}=await response.json();if(data.purpose!=="EVIDENCE_ANALYSIS_ONLY"||!Array.isArray(data.items)||after&&data.next_cursor===after)throw new Error("Saved analysis catalog could not be verified.");if(!disposed){setLibrary(previous=>Array.from(new Map([...(after?previous:[]),...data.items].map(item=>[item.reference.version_id,item])).values()));setNext(data.next_cursor);}}catch(failure){if(!disposed)setLibraryError(controller.signal.aborted?"Saved analyses timed out. Retry this page.":failure instanceof Error?failure.message:"Catalog unavailable");}finally{clearTimeout(timer);if(!disposed)setLibraryBusy(false);}}
  void load();return()=>{disposed=true;clearTimeout(timer);controller.abort();};
 },[token,after,libraryRevision]);
 const execute=useCallback(async(frozen:Request|null,reopenId?:string)=>{
  pending.current?.abort();const controller=new AbortController();pending.current=controller;const timer=setTimeout(()=>controller.abort(),20000);
  try{const response=await fetch(reopenId?`/api/ontology/functions/invocations/${encodeURIComponent(reopenId)}`:"/api/ontology/functions/invocations",{method:reopenId?"GET":"POST",headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},...(!reopenId?{body:JSON.stringify(frozen)}:{}),cache:"no-store",signal:controller.signal});if(!response.ok)throw new Error("The retained run could not be confirmed. Retry preserves the original request and time cutoffs.");const data:Invocation=await response.json();const output=data.output;
   if(data.invocation_id!==(reopenId??frozen?.request_id)||data.current_use_authorized!==false||data.business_effect_authorized!==false||!["SUCCEEDED","FAILED","INTENT_RETAINED"].includes(data.status)||data.status==="SUCCEEDED"&&(!output||output.contract!=="function-result/1"||output.mode!=="EVIDENCE_ANALYSIS_ONLY"||(output.coverage!=="QUERY_PAGE_ONLY"&&!worksheet(output)&&!retainedInput(output))||output.invocation_request_id!==data.invocation_id||output.current_use_authorized!==false||output.business_effect_authorized!==false)||output&&frozen&&(output.function.resource_id!==frozen.function.resource_id||output.function.version_id!==frozen.function.version_id||Date.parse(output.query.known_at)!==Date.parse(frozen.known_at)||Date.parse(output.query.valid_at)!==Date.parse(frozen.valid_at)||(frozen.input_result?(!retainedInput(output)||output.input_result?.invocation_id!==frozen.input_result.invocation_id||frozen.offset!==0):output.query.offset!==frozen.offset)))throw new Error("The retained result did not match the exact analysis, request and time cutoffs.");
   if(output)validateCalculatedInputs(output);
   if(data.status==="INTENT_RETAINED"&&reopenId){const retained=data.receipt.request;const uuid=/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;const aware=(value:string)=>typeof value==="string"&&/(Z|[+-]\d{2}:\d{2})$/i.test(value)&&Number.isFinite(Date.parse(value));if(!retained||retained.request_id!==data.invocation_id||!uuid.test(retained.function?.resource_id??"")||!uuid.test(retained.function?.version_id??"")||!aware(retained.valid_at)||!aware(retained.known_at)||!Number.isInteger(retained.offset)||retained.offset<0||retained.offset>1000000||!Number.isInteger(retained.limit)||retained.limit<1||retained.limit>200||retained.input_result&&(!uuid.test(retained.input_result.invocation_id)||retained.offset!==0))throw new Error("Retained intent has no valid original request to resume safely.");if(pending.current===controller&&!controller.signal.aborted){setRequest(retained);setSelected(retained.function.version_id);setValidAt(retained.valid_at);setKnownAt(retained.known_at);}}
   if(pending.current===controller&&!controller.signal.aborted){setResult(data);setSaved(data.invocation_id);}
  }catch(failure){if(pending.current===controller)setError(controller.signal.aborted?"The response timed out; the intent may be retained. Retry the same request to check or resume it.":failure instanceof Error?failure.message:"Analysis unavailable");}finally{clearTimeout(timer);if(pending.current===controller)setBusy(false);}
 },[token]);
 // execute updates React state only after awaiting the retained invocation response.
 // eslint-disable-next-line react-hooks/set-state-in-effect
 useEffect(()=>{if(initialInvocationId)void execute(null,initialInvocationId);},[initialInvocationId,execute]);
 function run(frozen:Request|null,reopenId?:string){setBusy(true);setError("");setResult(null);void execute(frozen,reopenId);}
 function worksheetLimit(definition:SavedFunction){const adapter=definition.attributes.definition;if(adapter&&typeof adapter==="object"&&"implementation_id" in adapter&&adapter.implementation_id==="source.retained-xls-worksheet/v1"&&"row_count" in adapter&&typeof adapter.row_count==="number"&&Number.isInteger(adapter.row_count)&&adapter.row_count>=1&&adapter.row_count<=50)return adapter.row_count;return 50;}
 function start(){const definition=library.find(item=>item.reference.version_id===selected);if(!definition)return;const aware=(value:string)=>/(Z|[+-]\d{2}:\d{2})$/i.test(value)&&Number.isFinite(Date.parse(value));if(!aware(validAt)||!aware(knownAt)){setError("Enter effective and known timestamps with an explicit timezone, such as +04:00 or Z.");return;}const frozen={request_id:crypto.randomUUID(),function:definition.reference,valid_at:new Date(validAt).toISOString(),known_at:new Date(knownAt).toISOString(),offset:0,limit:worksheetLimit(definition)};setRequest(frozen);run(frozen);}
 function page(offset:number){if(!request||request.input_result||result?.output?.coverage==="RETAINED_INPUT_PAGE_ONLY")return;const frozen={...request,request_id:crypto.randomUUID(),offset};setRequest(frozen);run(frozen);}
 const output=result?.output;const pageNext=output?(worksheet(output)?(output.source_query.next_offset!==null&&output.source_query.next_offset-output.source_document.first_row<output.source_document.row_count?output.source_query.next_offset-output.source_document.first_row:null):output.next_offset):null;const locked=Boolean(request)||busy;
 return <section className="saved-analysis" aria-label="Saved analysis workbench"><header><p className="overline">REVIEWED SAVED ANALYSES</p><h3>Run an evidence analysis</h3><p>Navigation context: {companyName||"No company selected"}. Analysis inputs come from its reviewed source contract in your authorized scope; this does not establish company ledger applicability.</p></header>
  <div className="saved-analysis-controls"><label>Saved analysis<select value={selected} disabled={locked||libraryBusy} onChange={event=>setSelected(event.target.value)}><option value="">Choose a reviewed analysis</option>{library.map(item=><option value={item.reference.version_id} key={item.reference.version_id}>{displayName(item.display_name)}</option>)}</select></label><label>Effective at — timezone required<input value={validAt} disabled={locked} onChange={event=>setValidAt(event.target.value)}/></label><label>Known at — timezone required<input value={knownAt} disabled={locked} onChange={event=>setKnownAt(event.target.value)}/></label></div>
  {libraryBusy&&<p role="status">Loading reviewed analyses…</p>}{libraryError&&<p role="alert">{libraryError}</p>}{!libraryBusy&&!libraryError&&!library.length&&<p>No reviewed saved analyses were returned in your authorized scope.</p>}{libraryError&&<button disabled={libraryBusy} onClick={()=>setLibraryRevision(value=>value+1)}>Retry analysis catalog</button>}{next&&<button disabled={libraryBusy||locked} onClick={()=>setAfter(next)}>Load more saved analyses</button>}
  <div className="saved-analysis-actions">{!request?<button disabled={busy||!selected} onClick={start}>Run and retain analysis</button>:<><button disabled={busy} onClick={()=>run(request)}>{result?.status==="INTENT_RETAINED"?"Resume retained intent":"Retry exact run"}</button><button disabled={busy} onClick={()=>{setRequest(null);setResult(null);setError("");}}>Start a new analysis</button></>}</div>
  <details><summary>Reopen a retained invocation</summary><label>Invocation reference<input value={saved} disabled={busy} onChange={event=>setSaved(event.target.value)}/></label><button disabled={busy||!/^[a-f0-9-]{36}$/i.test(saved)} onClick={()=>{setRequest(null);run(null,saved);}}>Reopen retained result</button></details>
  {busy&&<p role="status">Awaiting the retained run response…</p>}{error&&<p role="alert">{error}</p>}{result&&<><p>{result.status==="INTENT_RETAINED"?"Invocation intent is retained; completion is not established.":result.status==="FAILED"?`Execution failed: ${result.receipt.failure_code??"reason unavailable"}.` :"Analysis result retained."}</p><details><summary>Exact invocation evidence</summary><p>{result.invocation_id}</p><p>{result.receipt_hash??"No terminal receipt hash"}</p>{output&&<p>{output.run_id}</p>}</details></>}
  {output?.input_result&&<section aria-label="Consumed retained input"><h4>Consumed retained input</h4><p>This downstream result records the exact upstream invocation it consumed. A retained input remains evidence-only; it does not grant financial or current-use authority.</p><details><summary>Exact consumed result provenance</summary><p>Invocation: {output.input_result.invocation_id}</p><p>Receipt hash: {output.input_result.receipt_hash}</p><p>Retained result: {output.input_result.run_id}</p></details></section>}
  {output?.consumed_property_values&&<RetainedCalculatedInputs result={output} onInspect={onInspect} onTrace={onTrace}/>}
  {output&&result?.status==="SUCCEEDED"&&<RetainedBindingAction key={output.run_id} token={token} invocationId={result.invocation_id} output={output} onProposal={onProposal}/>}
  {output?.group_counts&&<GroupedObservationCounts key={output.run_id} result={output} onInspect={onInspect} onTrace={onTrace}/>}
  {output&&<section aria-label="Retained analysis page"><p>{worksheet(output)?"Requested effective context":"Effective"} {new Date(output.query.valid_at).toLocaleString()} · known {new Date(output.query.known_at).toLocaleString()}</p>{worksheet(output)?<WorksheetAnalysisResult key={output.run_id} token={token} result={output} knownAt={output.query.known_at} onInspect={onInspect} onTrace={onTrace}/>:<><p>{retainedInput(output)?`${output.objects.length} objects in the consumed retained page. Derived values apply to this retained page only.`:`${output.objects.length} objects on this page, offset ${output.query.offset}; ${output.total} query matches. Derived values apply to this page only.`}</p><div className="saved-analysis-table"><table><thead><tr><th>Source object</th><th>Derived values & availability</th><th>Investigate</th></tr></thead><tbody>{output.objects.map(object=><tr key={object.version_id}><th scope="row">{displayName(object.display_name)}<small>{object.object_type}</small></th><td>{output.derived_values.filter(value=>value.object_version_id===object.version_id).map(value=><div key={value.definition_version_id}><p>{value.name.replaceAll("_"," ")}: {value.value??"Unavailable"} · {value.status.toLowerCase().replaceAll("_"," ")}{value.reason?` — ${value.reason}`:""}</p>{(value.source_result||value.dependency_values?.some(dependency=>dependency.source_result))&&<details><summary>Evaluated retained values</summary>{[value,...(value.dependency_values??[])].filter(dependency=>dependency.source_result).map(dependency=><div key={dependency.definition_version_id}><p>{dependency.name.replaceAll("_"," ")}: {dependency.value??"Unavailable"} · {dependency.status.toLowerCase().replaceAll("_"," ")}</p><p>This value was read from the retained upstream result, without rereading its source fields.</p><details><summary>Exact evaluated value provenance</summary><pre>{JSON.stringify({object_id:dependency.object_id,object_version_id:dependency.object_version_id,definition_id:dependency.definition_id,definition_version_id:dependency.definition_version_id,source_result:dependency.source_result},null,2)}</pre></details></div>)}</details>}</div>)}{!output.derived_values.some(value=>value.object_version_id===object.version_id)&&<span>No derived value requested for this object.</span>}</td><td><button onClick={()=>onInspect(object,output.query.known_at)}>Inspect</button><button onClick={()=>onTrace(object,output.query.known_at)}>Trace evidence</button></td></tr>)}</tbody></table></div>{!output.objects.length&&<p>{retainedInput(output)?"The consumed retained page contains no objects.":"No objects matched the reviewed query at these cutoffs."}</p>}</>}{request&&!request.input_result&&!retainedInput(output)&&<div className="saved-analysis-actions"><button disabled={busy||output.query.offset===0} onClick={()=>page(Math.max(0,output.query.offset-output.query.limit))}>Previous page</button><button disabled={busy||pageNext===null} onClick={()=>pageNext!==null&&page(pageNext)}>Next page</button></div>}</section>}
  <footer>Evidence analysis only. A retained result does not grant current-use permission, financial authority or a business action.</footer>
 </section>;
}


function GroupedObservationCounts({result,onInspect,onTrace}:{result:Output;onInspect:Props["onInspect"];onTrace:Props["onTrace"]}){
 const counts=result.group_counts;
 if(!counts||counts.contract!=="grouped-observation-counts/1"||counts.authority!=="OBSERVATION_COUNTS_ONLY"||counts.coverage!=="COMPLETE_BOUNDED_OBJECT_SET"||!Array.isArray(counts.groups)||!Array.isArray(counts.fields))return <p role="alert">Grouped observation evidence has an unsupported contract; no count interpretation is shown.</p>;
 return <section aria-label="Grouped source observations"><h4>Grouped source observations</h4><p>{counts.object_count.toLocaleString()} source observations in the complete bounded Object Set. These are observation counts, not journal, transaction or financial totals.</p><p>Grouped by {counts.fields.map(field=>field.replaceAll("_"," ")).join(", ")}.</p><div className="saved-analysis-table"><table><thead><tr><th>Group</th><th>Source observations</th><th>Contributing evidence</th></tr></thead><tbody>{counts.groups.map((group,index)=><tr key={index}><th scope="row">{group.key.map(key=><p key={key.field}>{key.field.replaceAll("_"," ")}: {key.state==="MISSING"?"Not present":key.state==="NULL"?"Explicit null":key.state==="VALUE"?String(key.value):"Unsupported key state"}</p>)}</th><td>{group.count.toLocaleString()}</td><td><details><summary>Inspect group contributions</summary>{group.contributors.map(pin=>{const object=result.objects.find(candidate=>candidate.resource_id===pin.resource_id&&candidate.version_id===pin.version_id&&candidate.content_hash===pin.content_hash);return <div key={`${pin.resource_id}:${pin.version_id}`}>{object?<><p>{displayName(object.display_name)}</p><button onClick={()=>onInspect(object,result.query.known_at)}>Inspect</button><button onClick={()=>onTrace(object,result.query.known_at)}>Trace source</button></>:<p>The exact contributing version is unavailable in this retained result.</p>}</div>;})}</details></td></tr>)}</tbody></table></div>{!counts.groups.length&&<p>No observation groups were returned.</p>}<details><summary>Grouping fields &amp; exact schema provenance</summary><p>Schema resource: {counts.schema.resource_id}</p><p>Schema version: {counts.schema.version_id}</p><p>Schema hash: {counts.schema.content_hash}</p><p>Fields: {counts.fields.join(", ")}</p><p>Coverage: {counts.coverage} · Authority: {counts.authority}</p><p>Result: {result.run_id}</p></details></section>;
}


function validateCalculatedInputs(output:Output) {
 const record=(value:unknown):value is Record<string,unknown>=>!!value&&typeof value==="object"&&!Array.isArray(value);
 const uuid=(value:unknown)=>typeof value==="string"&&/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value);
 const hash=(value:unknown)=>typeof value==="string"&&/^[a-f0-9]{64}$/.test(value);
 const source=(value:unknown):value is SourceResult=>record(value)&&uuid(value.invocation_id)&&hash(value.receipt_hash)&&typeof value.run_id==="string"&&/^fcr_[a-f0-9]{64}$/.test(value.run_id);
 const sameSource=(left:SourceResult,right:SourceResult)=>left.invocation_id===right.invocation_id&&left.receipt_hash===right.receipt_hash&&left.run_id===right.run_id;
 const fail=()=>{throw new Error("Retained calculated-input provenance is malformed or does not match this result. No result interpretation is shown.");};
 const rows:unknown=output.consumed_property_values;
 if(rows!==undefined) {
  if(!Array.isArray(rows)||!source(output.input_result)||!Array.isArray(output.objects))return fail();
  const seen=new Set<string>();
  for(const row of rows) {
   if(!record(row)||!uuid(row.object_id)||!uuid(row.object_version_id)||!uuid(row.definition_id)||!uuid(row.definition_version_id)||
      typeof row.name!=="string"||!row.name||!["text","decimal"].includes(String(row.kind))||row.epistemic_state!=="DERIVED"||
      !["AVAILABLE","MISSING_INPUT","UNAVAILABLE","NOT_APPLICABLE"].includes(String(row.status))||
      !(row.value===null||typeof row.value==="string"||typeof row.value==="number"&&Number.isSafeInteger(row.value))||row.status==="AVAILABLE"&&row.value===null||row.status!=="AVAILABLE"&&row.value!==null||
      row.kind==="text"&&row.value!==null&&typeof row.value!=="string"||
      row.kind==="decimal"&&typeof row.value==="string"&&(row.value.length>4096||!/^[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?$/.test(row.value))||
      row.reason!==undefined&&typeof row.reason!=="string"||!hash(row.content_hash)||!record(row.schema)||
      !uuid(row.schema.resource_id)||!uuid(row.schema.version_id)||!hash(row.schema.content_hash)||
      !source(row.source_result)||!sameSource(row.source_result,output.input_result!)||
      !output.objects.some(object=>object.resource_id===row.object_id&&object.version_id===row.object_version_id))return fail();
   const key=`${row.object_id}:${row.object_version_id}:${row.definition_id}:${row.definition_version_id}`;
   if(seen.has(key))return fail();
   seen.add(key);
  }
 }
 if(!Array.isArray(output.derived_values))return fail();
 for(const root of output.derived_values) {
  if(!record(root)||root.dependency_values!==undefined&&!Array.isArray(root.dependency_values))return fail();
  for(const value of [root,...(root.dependency_values??[])]) {
   if(!record(value))return fail();
   if(value.source_result===undefined)continue;
   if(!source(value.source_result)||!Array.isArray(value.source_fields)||value.source_fields.length!==0||!Array.isArray(rows))return fail();
   const bound=rows.find(row=>record(row)&&row.object_id===value.object_id&&row.object_version_id===value.object_version_id&&row.definition_id===value.definition_id&&row.definition_version_id===value.definition_version_id);
   if(!bound||!sameSource(value.source_result,bound.source_result)||value.status!==bound.status||value.value!==bound.value||
      value.name!==undefined&&value.name!==bound.name||value.kind!==undefined&&value.kind!==bound.kind)return fail();
  }
 }
}

function RetainedCalculatedInputs({result,onInspect,onTrace}:{result:Output;onInspect:Props["onInspect"];onTrace:Props["onTrace"]}) {
 const inputs=result.consumed_property_values??[];
 const evaluated=result.derived_values.flatMap(value=>[value,...(value.dependency_values??[])]).filter(value=>value.source_result);
 return <section className="saved-analysis-calculated" aria-label="Retained calculated inputs">
  <h4>Retained calculated inputs</h4>
  <p>These values were bound from the upstream result for this retained page. Being bound does not mean a value was evaluated; unused fallback values remain listed here. Availability describes the upstream calculation, not financial authority.</p>
  <div className="saved-analysis-table"><table><thead><tr><th>Original object / property</th><th>Retained value & availability</th><th>Use in this calculation</th></tr></thead><tbody>
   {inputs.map(input=>{
    const object=result.objects.find(row=>row.resource_id===input.object_id&&row.version_id===input.object_version_id)!;
    const used=evaluated.some(value=>value.object_id===input.object_id&&value.object_version_id===input.object_version_id&&value.definition_id===input.definition_id&&value.definition_version_id===input.definition_version_id);
    return <tr key={`${input.object_version_id}:${input.definition_version_id}`}>
     <th scope="row">{displayName(object.display_name)}<small>{input.name.replaceAll("_"," ")}</small></th>
     <td><p>{input.value??"No value retained"}</p><small>{input.status.toLowerCase().replaceAll("_"," ")}{input.reason?` — ${input.reason}`:""}</small></td>
     <td><p>{used?"Evaluated from retained input":"Bound; not evaluated"}</p>
      <details><summary>Provenance & original object</summary>
       <p>This reference identifies the bound upstream value. Whether it was evaluated is shown above; no new source-field reads are implied.</p>
       <button onClick={()=>onInspect(object,result.query.known_at)}>Inspect original object</button>
       <button onClick={()=>onTrace(object,result.query.known_at)}>Trace original evidence</button>
       <pre>{JSON.stringify({object_id:input.object_id,object_version_id:input.object_version_id,definition_id:input.definition_id,definition_version_id:input.definition_version_id,content_hash:input.content_hash,schema:input.schema,source_result:input.source_result},null,2)}</pre>
      </details>
     </td>
    </tr>;
   })}
  </tbody></table></div>
  {!inputs.length&&<p>No calculated input values were bound for this retained page.</p>}
 </section>;
}
