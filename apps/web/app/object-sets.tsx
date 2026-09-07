"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import type { CanonicalResource, SchemaField, ObjectSetQuery, ObjectSetResult } from "@finai/contracts";
import {createOntologyClient} from "@g8/ontology-client";
import ObjectBindingAction from "./object-binding-action";
import DerivedPropertyRun from "./derived-property-run";
import OntologyDefinitionEditor from "./ontology-definition-editor";
import "./object-sets.css";

type FilterOperator="eq"|"lt"|"lte"|"gt"|"gte"|"in"|"not_in";
const operators:Record<FilterOperator,string>={eq:"Equals",lt:"Less than / before",lte:"At most / on or before",gt:"Greater than / after",gte:"At least / on or after",in:"Is one of",not_in:"Is not one of"};
const membershipKinds=new Set(["text","identifier","reference","integer","decimal","boolean","date","datetime"]);
const membership=(operator:string)=>operator==="in"||operator==="not_in";
const rangeKinds=new Set(["integer","decimal","date","datetime"]);

export type Query = ObjectSetQuery;
type Result = ObjectSetResult;
const label = (value: string) => value.replaceAll("_", " ").replace(/([a-z])([A-Z])/g, "$1 $2");

export type ObjectSetInvestigationContext = {valid_at?:string;known_at?:string;definition_id?:string;definition_version_id?:string};
type InvestigationAction = (node:CanonicalResource, context:ObjectSetInvestigationContext)=>void;
type FilterSchema=Pick<SchemaField,"kind"|"target_type">;
type FilterRow={field:string;operator:FilterOperator;value:string|null;retained?:Query["filters"][number]["value"]};
type StepRow={kind:"reference"|"link";name:string;direction:"outgoing"|"incoming";filters:FilterRow[]};
const restoreFilters=(filters:Query["filters"])=>filters.map(filter=>({field:filter.field,operator:filter.operator??"eq",value:filter.value===null?null:Array.isArray(filter.value)?filter.value.map(String).join("\n"):String(filter.value),...(membership(filter.operator??"eq")?{retained:filter.value}:{})}));
const restoreSteps=(steps:Query["traversal"]):StepRow[]=>steps.map(step=>({...step,filters:restoreFilters(step.filters??[])}));
function validFilter(filter:Query["filters"][number]):boolean {
 if(!filter||typeof filter.field!=="string"||filter.field.length>128||!Object.hasOwn(operators,filter.operator??"eq"))return false;
 const scalar=(value:unknown)=>typeof value==="string"||typeof value==="boolean"||typeof value==="number"&&Number.isSafeInteger(value);
 if(membership(filter.operator??"eq"))return Array.isArray(filter.value)?filter.value.length>=1&&filter.value.length<=100&&filter.value.every(scalar)&&new Set(filter.value.map(value=>typeof value)).size===1&&new Set(filter.value.map(value=>JSON.stringify(value))).size===filter.value.length:false;
 return !Array.isArray(filter.value)&&(filter.value===null||["string","boolean"].includes(typeof filter.value)||typeof filter.value==="number"&&Number.isFinite(filter.value));
}

type SavedExecution = {query:Query;family:"sets"|"groups"|null;definition_id?:string;definition_version_id?:string};
function restoreExecution(key?:string):SavedExecution|null {
  if(!key||typeof window==="undefined")return null;
  try {
    const raw=sessionStorage.getItem(key);if(!raw||raw.length>131072)return null;
    const data=JSON.parse(raw) as SavedExecution;
    const query=data.query;
    if(!query||typeof query.object_type!=="string"||typeof query.search!=="string"||!Array.isArray(query.filters)||!Array.isArray(query.traversal)||!Number.isInteger(query.offset)||query.offset<0||!Number.isInteger(query.limit)||query.limit<1||query.limit>200||!query.valid_at||!query.known_at||!Number.isFinite(Date.parse(query.valid_at))||!Number.isFinite(Date.parse(query.known_at)))return null;
    if(query.filters.length>20||query.filters.some(filter=>!validFilter(filter)))return null;
    if(query.traversal.length>4||query.traversal.some(step=>!step||!["reference","link"].includes(step.kind)||!["outgoing","incoming"].includes(step.direction)||typeof step.name!=="string"||step.name.length>128||step.filters!==undefined&&!Array.isArray(step.filters)))return null;
    const allFilters=[...query.filters,...query.traversal.flatMap(step=>step.filters??[])];
    if(allFilters.length>20||allFilters.some(filter=>!validFilter(filter))||allFilters.reduce((count,filter)=>count+(membership(filter.operator??"eq")?(Array.isArray(filter.value)?filter.value.length:1):0),0)>100)return null;
    if(query.resource_ids!==undefined&&query.resource_ids!==null&&(!Array.isArray(query.resource_ids)||query.resource_ids.length>100||query.resource_ids.some(id=>typeof id!=="string"||!/^[a-f0-9-]{36}$/i.test(id))))return null;
    if(![null,"sets","groups"].includes(data.family))return null;
    const uuid=/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
    if(data.family&&(!uuid.test(data.definition_id??"")||!uuid.test(data.definition_version_id??"")))return null;
    if(query.interface&&(query.object_type!=="ObjectInterface"||!uuid.test(query.interface.resource_id)||!uuid.test(query.interface.version_id)||!Array.isArray(query.interface.implementations)||query.interface.implementations.length<1||query.interface.implementations.length>100||query.interface.implementations.some(pin=>!pin||!uuid.test(pin.resource_id)||!uuid.test(pin.version_id))||new Set(query.interface.implementations.map(pin=>pin.resource_id)).size!==query.interface.implementations.length))return null;
    if(query.type_group&&(query.interface||query.object_type!=="ObjectTypeGroup"||!uuid.test(query.type_group.resource_id)||!uuid.test(query.type_group.version_id)))return null;
    return data;
  } catch{return null;}
}

export default function ObjectSets({ token, catalog: suppliedCatalog, onProposal,onInspect,onHistory,onTrace,viewStateKey }: { token: string; catalog?: CanonicalResource[]; onProposal?: (id: string) => void;onInspect?:InvestigationAction;onHistory?:InvestigationAction;onTrace?:InvestigationAction;viewStateKey?:string }) {
  const client=useMemo(()=>createOntologyClient({baseUrl:"/api/ontology",getToken:()=>token}),[token]);
  const executionController=useRef<AbortController|null>(null);
  const [restored]=useState(()=>restoreExecution(viewStateKey));
  const [loadedCatalog, setLoadedCatalog] = useState<CanonicalResource[]>([]);
  const catalog = suppliedCatalog ?? loadedCatalog;
  const schemas = catalog.filter(item => item.object_type === "SchemaDefinition");
  const [kind, setKind] = useState(restored?.query.object_type??"LegalEntity");
  const [filterRows,setFilterRows]=useState<FilterRow[]>(()=>restoreFilters(restored?.query.filters??[]));
  const [groupRoot,setGroupRoot]=useState<Query["type_group"]>(restored?.query.type_group);
  const [groupBindings,setGroupBindings]=useState<Result["type_group_bindings"]>();
  const [interfaceRoot,setInterfaceRoot]=useState<Query["interface"]>(restored?.query.interface);
  const [interfaceBindings,setInterfaceBindings]=useState<Result["interface_bindings"]>();
  const [rootIds,setRootIds]=useState<string[]|null|undefined>(restored?.query.resource_ids);
  const [formSearch,setFormSearch]=useState(restored?.query.search??"");
  const [steps,setSteps]=useState<StepRow[]>(()=>restoreSteps(restored?.query.traversal??[]));
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(Boolean(restored));
  const [definitions, setDefinitions] = useState<CanonicalResource[]>([]);
  const [libraryId, setLibraryId] = useState("");
  const [publication, setPublication] = useState("");
  const [executionFamily, setExecutionFamily] = useState<"sets" | "groups" | null>(null);
  const generation = useRef(0);
  useEffect(()=>()=>{generation.current++;executionController.current?.abort();},[token]);
  const [definitionError,setDefinitionError]=useState("");
  useEffect(()=>{
    if(!restored)return;
    const controller=new AbortController();const request=++generation.current;
    executionController.current=controller;
    const options={offset:restored.query.offset,limit:restored.query.limit,valid_at:restored.query.valid_at,known_at:restored.query.known_at,signal:controller.signal};
    const replayDefinition=Boolean(restored.family&&!restored.query.interface&&!restored.query.type_group);
    const exactPin={resource_id:restored.definition_id!,version_id:restored.definition_version_id!};
    const execution=replayDefinition?(restored.family==="sets"?client.runSavedSet(exactPin,options):client.runGroup(exactPin,options)):client.query(restored.query,{signal:controller.signal});
    void execution.then(data=>{if(!controller.signal.aborted&&generation.current===request){setResult({...data,...restored.definition_id?{definition_id:restored.definition_id,definition_version_id:restored.definition_version_id}:{}});setExecutionFamily(restored.family);setLibraryId(restored.definition_id??"");setKind(data.query.object_type);setFilterRows(restoreFilters(data.query.filters));setFormSearch(data.query.search);setRootIds(data.query.resource_ids);setSteps(restoreSteps(data.query.traversal));setInterfaceRoot(data.query.interface);setInterfaceBindings(data.interface_bindings);setGroupRoot(data.query.type_group);setGroupBindings(data.type_group_bindings);}})
      .catch(cause=>{if(!controller.signal.aborted&&generation.current===request)setError(cause instanceof Error?cause.message:"Query replay failed");})
      .finally(()=>{if(!controller.signal.aborted&&generation.current===request)setBusy(false);});
    return()=>controller.abort();
  },[client,restored]);
  useEffect(()=>{
    if(!viewStateKey||!result)return;
    try{sessionStorage.setItem(viewStateKey,JSON.stringify({query:result.query,family:executionFamily,definition_id:result.definition_id,definition_version_id:result.definition_version_id}));}catch{/* Storage restrictions do not block server-backed queries. */}
  },[viewStateKey,result,executionFamily]);
  const investigationContext:ObjectSetInvestigationContext=result?{valid_at:result.query.valid_at,known_at:result.query.known_at,definition_id:result.definition_id,definition_version_id:result.definition_version_id}:{};
  function investigate(node:CanonicalResource){return <span className="object-set-actions">{onInspect&&<button type="button" onClick={()=>onInspect(node,investigationContext)}>Inspect</button>}{onHistory&&<button type="button" onClick={()=>onHistory(node,investigationContext)}>History</button>}{onTrace&&<button type="button" onClick={()=>onTrace(node,investigationContext)}>Trace evidence</button>}</span>;}
  async function inspectDefinition(action:InvestigationAction){
    if(!result?.definition_id||!result.definition_version_id)return;
    const captured=result;const request=generation.current;setDefinitionError("");
    // Definition publication may postdate the historical data it queries. Trace its
    // immutable version without applying the data query knowledge cutoff.
    const context:ObjectSetInvestigationContext={definition_id:captured.definition_id,definition_version_id:captured.definition_version_id};
    try {
      const existing=definitions.find(node=>node.resource_id===captured.definition_id&&node.version_id===captured.definition_version_id);
      if(existing){action(existing,context);return;}
      const response=await fetch(`/api/ontology/resources/${captured.definition_id}`,{headers:{Authorization:`Bearer ${token}`},cache:"no-store"});
      if(!response.ok)throw Error("The published definition version could not be inspected.");
      const data=await response.json() as {versions:CanonicalResource[]};
      const exact=data.versions.find(node=>node.version_id===captured.definition_version_id);
      if(!exact)throw Error("The published definition version is unavailable. No current version was substituted.");
      if(generation.current===request)action(exact,context);
    }catch(cause){if(generation.current===request)setDefinitionError(cause instanceof Error?cause.message:"Definition unavailable");}
  }
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/ontology/model/definitions", { headers: { Authorization: `Bearer ${token}` }, cache: "no-store", signal: controller.signal })
      .then(async response => { if (!response.ok) throw new Error("Published ontology definitions are unavailable."); return response.json(); })
      .then(data => { if (!controller.signal.aborted) setDefinitions(data); })
      .catch(cause => { if (!controller.signal.aborted) setError(cause.message); });
    return () => controller.abort();
  }, [token]);
  useEffect(() => {
    if (suppliedCatalog) return;
    const controller = new AbortController();
    fetch("/api/ontology/catalog", { headers: { Authorization: `Bearer ${token}` }, cache: "no-store", signal: controller.signal })
      .then(async response => { if (!response.ok) throw new Error("Ontology definitions are unavailable."); return response.json(); })
      .then(data => { if (!controller.signal.aborted) setLoadedCatalog(data); })
      .catch(cause => { if (!controller.signal.aborted) setError(cause.message); });
    return () => controller.abort();
  }, [token, suppliedCatalog]);
  const fields = interfaceRoot ? interfaceBindings?.fields??{} : groupRoot?groupBindings?.fields??{}: (schemas.find(item => item.identity_key === kind)?.attributes.fields ?? {}) as Record<string, FilterSchema>;
  const links = catalog.filter(item => item.object_type === "LinkType");
  const schemaFields=(type:string)=>type==="ObjectInterface"&&interfaceRoot?(interfaceBindings?.fields??{}):type==="ObjectTypeGroup"&&groupRoot?(groupBindings?.fields??{}):(schemas.find(schema=>schema.identity_key===type)?.attributes.fields??{}) as Record<string,FilterSchema>;
  const names=(value:unknown):string[]=>Array.isArray(value)?value.filter((item):item is string=>typeof item==="string"):[];
  function choices(types:string[],direction:StepRow["direction"],firstStep=false){
    const concreteTypes=firstStep&&interfaceRoot?(interfaceBindings?.implementations.map(binding=>binding.object_type)??[]):firstStep&&groupRoot?(groupBindings?.schemas.map(binding=>binding.object_type)??[]):types;
    const result=new Map<string,{kind:StepRow["kind"];name:string;targets:string[]}>();
    if(direction==="outgoing"){for(const type of types)for(const [name,spec] of Object.entries(schemaFields(type)))if(spec.kind==="reference"){
      const key=`reference:${name}`;result.set(key,{kind:"reference",name,targets:[...new Set([...(result.get(key)?.targets??[]),spec.target_type??"*"])]});
    }
    }else {for(const schema of schemas)for(const [name,spec] of Object.entries(schemaFields(schema.identity_key)))if(spec.kind==="reference"&&(spec.target_type==="*"||concreteTypes.includes(spec.target_type??""))){
      const key=`reference:${name}`;result.set(key,{kind:"reference",name,targets:[...new Set([...(result.get(key)?.targets??[]),schema.identity_key])]});
    }
    }
    for(const link of links){const from=names(link.attributes[direction==="outgoing"?"sources":"targets"]);if(from.includes("*")||concreteTypes.some(type=>from.includes(type)))result.set(`link:${link.identity_key}`,{kind:"link",name:link.identity_key,targets:names(link.attributes[direction==="outgoing"?"targets":"sources"])});}
    return [...result.values()];
  }
  const stages=steps.reduce<Array<{available:ReturnType<typeof choices>;targets:string[];fields:Record<string,FilterSchema>;usable:boolean}>>((previous,step)=>{
    const reached=previous.at(-1)?.targets??[kind];
    const available=choices(reached,step.direction,previous.length===0);const targets=available.find(choice=>choice.kind===step.kind&&choice.name===step.name)?.targets??[];
    const usable=targets.length>0&&!targets.includes("*")&&targets.every(type=>schemas.some(schema=>schema.identity_key===type));
    const typed=usable?Object.fromEntries(Object.entries(schemaFields(targets[0])).filter(([name,spec])=>targets.every(type=>schemaFields(type)[name]?.kind===spec.kind))):{};
    return [...previous,{available,targets,fields:typed,usable}];
  },[]);
  const predicateCount=filterRows.length+steps.reduce((count,step)=>count+step.filters.length,0);
  function filterEditor(rows:FilterRow[],specs:Record<string,FilterSchema>,update:(rows:FilterRow[])=>void,scope:string){return <fieldset className="object-set-filters"><legend>{scope} · all conditions must match</legend>{rows.map((row,index)=><div className="object-set-filter-row" key={index}>
    <label>Property<select value={row.field} onChange={event=>update(rows.map((item,i)=>i===index?{field:event.target.value,operator:"eq",value:specs[event.target.value]?.kind==="boolean"?"true":""}:item))}><option value="">Choose property</option>{row.field&&!specs[row.field]&&<option value={row.field}>{label(row.field)} · schema unavailable</option>}{Object.entries(specs).filter(([,spec])=>!["money","quantity","geometry","geojson","definition"].includes(spec.kind)).map(([name])=><option key={name} value={name}>{label(name)}</option>)}</select></label>
    <label>Comparison<select value={row.operator} onChange={event=>update(rows.map((item,i)=>i===index?{...item,operator:event.target.value as FilterOperator,retained:membership(item.operator)&&membership(event.target.value)?item.retained:undefined,value:membership(item.operator)&&!membership(event.target.value)||item.value===null&&membership(event.target.value)?"":item.value}:item))}>{(Object.keys(operators) as FilterOperator[]).filter(item=>item==="eq"||item===row.operator||(membership(item)?membershipKinds.has(specs[row.field]?.kind):rangeKinds.has(specs[row.field]?.kind))).map(item=><option key={item} value={item}>{operators[item]}</option>)}</select></label>
    <label>{membership(row.operator)?"Values — one per line":"Value"}{membership(row.operator)?<><textarea required rows={3} maxLength={25700} value={row.value??""} placeholder={specs[row.field]?.kind==="boolean"?"true\nfalse":"One exact value per line"} onChange={event=>update(rows.map((item,i)=>i===index?{...item,value:event.target.value,retained:undefined}:item))}/><small>1–100 unique values; 100 across the whole query. Blank lines are rejected. Null/missing source values never match. Text spaces are preserved; one final newline is allowed.</small>{row.retained!==undefined&&<details><summary>Exact retained membership values</summary>{(Array.isArray(row.retained)?row.retained:[row.retained]).map((value,i)=><pre key={i}>{JSON.stringify(value)}</pre>)}</details>}</>:row.value===null?<input readOnly value="Null"/>:specs[row.field]?.kind==="boolean"?<select value={row.value} onChange={event=>update(rows.map((item,i)=>i===index?{...item,value:event.target.value}:item))}><option value="true">True</option><option value="false">False</option></select>:<input required maxLength={256} value={row.value} type={specs[row.field]?.kind==="date"?"date":"text"} placeholder={specs[row.field]?.kind==="datetime"?"YYYY-MM-DDTHH:mm:ss+04:00":specs[row.field]?.kind==="decimal"?"Exact decimal text":"Exact value"} onChange={event=>update(rows.map((item,i)=>i===index?{...item,value:event.target.value}:item))}/>}</label>
    <button type="button" disabled={row.operator!=="eq"} onClick={()=>update(rows.map((item,i)=>i===index?{...item,value:item.value===null?"":null}:item))}>{row.value===null?"Use a value":"Match null"}</button>
    <button type="button" onClick={()=>update(rows.filter((_,i)=>i!==index))} aria-label={`Remove ${scope} filter ${index+1}`}>Remove</button>
  </div>)}<button type="button" disabled={predicateCount>=20||!Object.keys(specs).length} onClick={()=>update([...rows,{field:"",operator:"eq",value:""}])}>Add property filter</button></fieldset>;}
  function parseFilters(rows:FilterRow[],specs:Record<string,FilterSchema>):Query["filters"]{
    return rows.map(row=>{
      const {field,operator}=row;const spec=specs[field];
      if(!field||!spec||operator!=="eq"&&!(membership(operator)?membershipKinds.has(spec.kind):rangeKinds.has(spec.kind)))throw Error("Choose an available schema property and supported comparison for every filter. Ambiguous targets require common typed properties.");
      function scalar(text:string):string|number|boolean {
        if(spec.kind==="datetime"&&operator!=="eq"&&!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/i.test(text))throw Error("Enter timestamps with seconds and an explicit timezone; values are sent unchanged.");
        if(membership(operator)&&spec.kind==="date"&&!/^\d{4}-\d{2}-\d{2}$/.test(text))throw Error("Use YYYY-MM-DD for every date. Values are sent unchanged.");
        if(membership(operator)&&spec.kind==="decimal"&&!/^[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?$/.test(text))throw Error("Every decimal must be exact finite decimal text.");
        if(spec.kind==="integer"){if(!/^-?\d+$/.test(text)||!Number.isSafeInteger(Number(text)))throw Error("Integer input must be exact and between -9007199254740991 and 9007199254740991.");return Number(text);}
        if(spec.kind==="boolean"){if(text!=="true"&&text!=="false")throw Error("Enter true or false exactly, one value per line.");return text==="true";}
        return text;
      }
      if(membership(operator)) {
        if(row.value===null)throw Error("Membership excludes null and missing values; enter explicit values.");
        let value:Query["filters"][number]["value"];
        if(row.retained!==undefined){
          const originals=Array.isArray(row.retained)?row.retained:[row.retained];
          for(const original of originals){if(original===null||Array.isArray(original)||scalar(String(original))!==original)throw Error("The retained membership type does not match this canonical property. Edit the values explicitly before running.");}
          value=row.retained;
        }else{
          const lines=row.value.replace(/\r\n/g,"\n").split("\n");if(lines.at(-1)==="")lines.pop();
          if(!lines.length||lines.length>100||lines.some(line=>line.length===0||line.includes("\r")))throw Error("Enter 1–100 values with no blank lines. A single final newline is allowed.");
          value=lines.map(scalar);
        }
        const filter={field,operator,value};if(!validFilter(filter))throw Error("Membership values must be non-null, typed, unique, and bounded to 100 values.");
        return filter;
      }
      if(row.value===null){if(operator!=="eq")throw Error("Null comparisons support equality only.");return {field,value:null};}
      return {field,value:scalar(row.value),...(operator!=="eq"?{operator}:{})};
    });
  }


  async function openPublished() {
    const selected=definitions.find(item=>item.resource_id===libraryId);
    if(!selected)return;
    const request=++generation.current;
    executionController.current?.abort();const controller=new AbortController();executionController.current=controller;
    setBusy(true);setError("");setResult(null);
    try {
      const family=selected.object_type==="ObjectSetDefinition"?"sets":"groups";
      const exactPin={resource_id:selected.resource_id,version_id:selected.version_id};
      const options={offset:0,limit:50,signal:controller.signal};
      const data=await (family==="sets"?client.runSavedSet(exactPin,options):client.runGroup(exactPin,options));
      if(generation.current===request&&!controller.signal.aborted){setResult(data);setExecutionFamily(family);setKind(data.query.object_type);setFormSearch(data.query.search);setFilterRows(restoreFilters(data.query.filters));setRootIds(data.query.resource_ids);setInterfaceRoot(data.query.interface);setInterfaceBindings(data.interface_bindings);setGroupRoot(data.query.type_group);setGroupBindings(data.type_group_bindings);setSteps(restoreSteps(data.query.traversal));}
    }catch(cause){if(generation.current===request&&!controller.signal.aborted)setError(cause instanceof Error?cause.message:"Query failed");}
    finally{if(generation.current===request)setBusy(false);}
  }

  async function publish(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!result || executionFamily === "groups"&&!result.query.interface&&!result.query.type_group) return;
    const fields = new FormData(event.currentTarget);
    const name = String(fields.get("setName") ?? "").trim();
    const rationale = String(fields.get("rationale") ?? "").trim();
    const fixed = fields.get("fixed") === "on";
    setBusy(true); setError(""); setPublication("");
    try {
      const response = await fetch("/api/ontology/model/definitions", { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ kind: "ObjectSetDefinition", key: `set:${crypto.randomUUID()}`, name, rationale, attributes: { definition: { ...result.query, offset: 0, valid_at: fixed ? result.query.valid_at : null, known_at: fixed ? result.query.known_at : null } } }) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "The definition could not be proposed.");
      setPublication(data.proposal.proposal_id);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Publication failed"); }
    finally { setBusy(false); }
  }

  async function run(query: Query) {
    const request=++generation.current;
    executionController.current?.abort();const controller=new AbortController();executionController.current=controller;
    setBusy(true);setError("");setResult(null);
    try {
      const data=await client.query(query,{signal:controller.signal});
      if(request===generation.current&&!controller.signal.aborted){setResult(data);setExecutionFamily(null);setInterfaceRoot(data.query.interface);setInterfaceBindings(data.interface_bindings);setGroupRoot(data.query.type_group);setGroupBindings(data.type_group_bindings);}
    }catch(cause){if(request===generation.current&&!controller.signal.aborted)setError(cause instanceof Error?cause.message:"Query failed");}
    finally{if(request===generation.current)setBusy(false);}
  }

  async function goToPage(offset: number) {
    if(!result)return;
    const previous=result;const request=++generation.current;
    executionController.current?.abort();const controller=new AbortController();executionController.current=controller;
    setBusy(true);setError("");setResult(null);
    try{
      const data=await client.page(previous,offset,{signal:controller.signal});
      if(!data)throw Error("The requested query page is unavailable.");
      if(request===generation.current&&!controller.signal.aborted){setResult(data);setInterfaceRoot(data.query.interface);setInterfaceBindings(data.interface_bindings);setGroupRoot(data.query.type_group);setGroupBindings(data.type_group_bindings);}
    }catch(cause){if(request===generation.current&&!controller.signal.aborted)setError(cause instanceof Error?cause.message:"Query page failed");}
    finally{if(request===generation.current)setBusy(false);}
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    try{
      if(kind==="ObjectInterface"&&!interfaceRoot)throw Error("Open a published executable interface or choose a concrete object type. Choose the exact shared query root first.");
      if(kind==="ObjectTypeGroup"&&!groupRoot)throw Error("Open a published type group before rerunning; do not query group definition records as group members.");
      if(groupRoot&&!groupBindings)throw Error("Exact type-group field bindings are unavailable; reopen the published group before editing.");
      if(interfaceRoot&&!interfaceBindings)throw Error("Exact interface field bindings are unavailable; reopen the published interface before editing.");
      if(steps.length>4||predicateCount>20)throw Error("A query supports at most four relationship steps and twenty property filters in total.");
      const traversal:Query["traversal"]=steps.map((step,index)=>{
        if(!step.name)throw Error(`Choose a relationship for step ${index+1}.`);
        const filters=parseFilters(step.filters,stages[index].fields);
        return {kind:step.kind,name:step.name,direction:step.direction,...(filters.length?{filters}:{})};
      });
      const rootFilters=parseFilters(filterRows,fields);
      const membershipCount=[...rootFilters,...traversal.flatMap(step=>step.filters??[])].reduce((count,filter)=>count+(membership(filter.operator??"eq")?(Array.isArray(filter.value)?filter.value.length:1):0),0);
      if(membershipCount>100)throw Error("Membership filters support at most 100 values across starting objects and all relationship steps.");
      void run({object_type:kind,...(interfaceRoot?{interface:interfaceRoot}:{}),...(groupRoot?{type_group:groupRoot}:{}),...(rootIds!==undefined?{resource_ids:rootIds}:{}),search:String(data.get("search")??""),filters:rootFilters,traversal,offset:0,limit:50});
    }catch(cause){setError(cause instanceof Error?cause.message:"Query choices are unavailable.");}
  }

  return <section className="data-panel object-set-workspace">
    <div className="toolbar"><div><h2>Object Sets</h2><p className="muted">Explore across companies in your workspace. Find canonical objects and follow their version-bound relationships.</p></div></div>
    <details className="object-set-studio"><summary>Ontology Studio  -  define shared query contracts</summary><OntologyDefinitionEditor token={token} definitions={definitions} onProposal={onProposal}/></details>
    <div className="resource-form"><label>Published sets and type groups<select value={libraryId} onChange={event => setLibraryId(event.target.value)}><option value="">Choose a published definition</option>{definitions.filter(item => ["ObjectSetDefinition", "ObjectInterface", "ObjectTypeGroup"].includes(item.object_type)).map(item => <option key={item.resource_id} value={item.resource_id}>{item.display_name} · {label(item.object_type)}</option>)}</select></label><button type="button" disabled={busy || !libraryId} onClick={() => void openPublished()}>Open published set</button></div>
    <form className="resource-form" onSubmit={submit}>
      <label>Object type<select value={kind} onChange={event => { setKind(event.target.value); setFilterRows([]);setSteps([]);setRootIds(undefined);setInterfaceRoot(undefined);setInterfaceBindings(undefined);setGroupRoot(undefined);setGroupBindings(undefined); }}>{schemas.map(schema => <option key={schema.resource_id} value={schema.identity_key}>{label(schema.identity_key)}</option>)}</select></label>
      {interfaceRoot&&<section className="object-set-interface-context"><h4>Executable shared interface</h4><p>{definitions.find(item=>item.resource_id===interfaceRoot.resource_id&&item.version_id===interfaceRoot.version_id)?.display_name??"Exact published interface"} · {interfaceRoot.implementations.length} pinned implementations. Changing the root object type explicitly clears this interface context.</p><details><summary>Exact interface and implementation bindings</summary><p>Interface: {interfaceRoot.resource_id} · {interfaceRoot.version_id}</p>{interfaceBindings?.implementations.map(binding=><div key={binding.implementation.version_id}><p>{label(binding.object_type)} · implementation {binding.implementation.resource_id} · {binding.implementation.version_id}</p><p>Schema: {binding.schema.resource_id} · {binding.schema.version_id}</p>{Object.entries(binding.fields).map(([alias,field])=><p key={alias}>{label(alias)} → {label(field)}</p>)}</div>)}</details></section>}
      {groupRoot&&<section className="object-set-interface-context"><h4>Executable type group</h4><p>{definitions.find(item=>item.resource_id===groupRoot.resource_id&&item.version_id===groupRoot.version_id)?.display_name??"Exact published type group"} · {groupBindings?.schemas.map(binding=>label(binding.object_type)).join(", ")??"Reading schema bindings"}. Filters use properties common to the exact member schemas. Change the root object type explicitly to clear this group context.</p><details><summary>Exact group and schema bindings</summary><p>Group: {groupRoot.resource_id} · {groupRoot.version_id}</p>{groupBindings?.schemas.map(binding=><p key={binding.schema.version_id}>{label(binding.object_type)} · {binding.schema.resource_id} · {binding.schema.version_id}</p>)}</details></section>}
      {kind==="ObjectTypeGroup"&&!groupRoot&&<p role="status">Open a published executable type group or choose a concrete type before querying.</p>}
      {kind==="ObjectInterface"&&!interfaceRoot&&<p role="status">This listing is not an executable interface query. Open a published interface or explicitly choose a concrete root type before rerunning or publishing.</p>}
      <label>Name or business key<input name="search" value={formSearch} onChange={event=>setFormSearch(event.target.value)} maxLength={128} placeholder="Search this object type" /></label>
      {rootIds!==undefined&&rootIds!==null&&<details><summary>{rootIds.length} explicit starting object IDs retained</summary><p>This query remains constrained to these canonical roots. Clearing them broadens the starting selection.</p>{rootIds.map(id=><p key={id}><code>{id}</code></p>)}<button type="button" onClick={()=>setRootIds(undefined)}>Clear explicit starting objects</button></details>}
      {filterEditor(filterRows,fields,setFilterRows,"Starting objects")}
      <fieldset className="object-set-traversal"><legend>Follow relationships · up to four steps</legend>
        {steps.map((step,index)=><section key={index} className="object-set-step"><h4>Step {index+1}</h4><div className="object-set-step-controls">
          <label>Direction<select value={step.direction} onChange={event=>setSteps(previous=>previous.map((item,i)=>i===index?{...item,direction:event.target.value as StepRow["direction"]}:item))}><option value="outgoing">From matching objects</option><option value="incoming">Into matching objects</option></select></label>
          <label>Relationship<select value={`${step.kind}:${step.name}`} onChange={event=>{const [kind,...name]=event.target.value.split(":");setSteps(previous=>previous.map((item,i)=>i===index?{...item,kind:kind as StepRow["kind"],name:name.join(":")}:item));}}><option value="reference:">Choose relationship</option>{step.name&&!stages[index].available.some(choice=>choice.kind===step.kind&&choice.name===step.name)&&<option value={`${step.kind}:${step.name}`}>{label(step.name)} · current schema unavailable</option>}{stages[index].available.map(choice=><option key={`${choice.kind}:${choice.name}`} value={`${choice.kind}:${choice.name}`}>{label(choice.name)} · {choice.kind}</option>)}</select></label>
          <button type="button" onClick={()=>setSteps(previous=>previous.filter((_,i)=>i!==index))}>Remove step {index+1}</button>
        </div><p>Reached types: {stages[index].targets.map(label).join(", ")||"Unresolved"}. Filters apply before the next step.</p>
        {!stages[index].usable&&<p role="status">The reached schema is ambiguous or unavailable. New typed filters cannot be inferred; retained comparisons remain visible and require a resolvable schema.</p>}
        {filterEditor(step.filters,stages[index].fields,filters=>setSteps(previous=>previous.map((item,i)=>i===index?{...item,filters}:item)),`Step ${index+1} reached objects`)}
        </section>)}
        <button type="button" disabled={steps.length>=4} onClick={()=>setSteps(previous=>[...previous,{kind:"reference",name:"",direction:"outgoing",filters:[]}])}>Add relationship step</button>
      </fieldset>
      <p className="muted">{predicateCount} of 20 total property conditions. Decimal and timezone timestamp text remains exact. Returned objects are endpoints; per-hop path receipts are not provided.</p>
      <button disabled={busy || !schemas.length || (kind==="ObjectInterface"&&!interfaceRoot||kind==="ObjectTypeGroup"&&!groupRoot)}>{busy ? "Querying…" : "Explore objects"}</button>
    </form>
    {busy&&<p role="status">{restored&&!result?"Replaying the saved request against current authorized access at its retained query time - ":"Querying shared object authority - "}</p>}
    {error && <p className="error-banner" role="alert">{error}</p>}
    {definitionError&&<p className="error-banner" role="alert">{definitionError}</p>}
    {result && <>
      <div className="object-set-time"><div><span>Effective at</span><time>{result.query.valid_at}</time></div><div><span>Known at</span><time>{result.query.known_at}</time></div><p>Query time is retained across pages and return visits. New searches resolve a new query time.</p></div>
      {result.definition_id&&<div className="object-set-definition"><strong>Published query  -  exact retained version</strong><span className="object-set-actions">{onInspect&&<button onClick={()=>void inspectDefinition(onInspect)}>Inspect definition</button>}{onHistory&&<button onClick={()=>void inspectDefinition(onHistory)}>Definition history</button>}{onTrace&&<button onClick={()=>void inspectDefinition(onTrace)}>Trace definition</button>}</span><details><summary>Published definition reference</summary><code>{result.definition_id}<br/>{result.definition_version_id}</code></details></div>}
      <div className="toolbar"><h3>{result.total.toLocaleString()} matching object versions</h3><span>{Object.entries(result.counts_by_type).map(([type, count]) => `${label(type)}: ${count}`).join(" · ")}</span></div>
      <p className="muted">{result.query.traversal.length ? "Relationships return the exact versions they reference, which may differ from today's values. " : "Effective objects at the query time. "}Counts cover the full result, not just this page.</p>
      {!!result.query.filters.length&&<section aria-label="Applied property comparisons"><h4>Applied comparisons</h4>{result.query.filters.map((filter,index)=><p key={index}>{label(filter.field)} · {operators[filter.operator??"eq"]} · <code style={{whiteSpace:"pre-wrap"}}>{Array.isArray(filter.value)?filter.value.map(value=>JSON.stringify(value)).join("\n"):String(filter.value)}</code></p>)}</section>}
      {!!result.query.traversal.length&&<section aria-label="Applied relationship steps"><h4>Applied relationship steps</h4>{result.query.traversal.map((step,index)=><div key={index}><p>Step {index+1} · {label(step.name)} · {step.direction} {step.kind}</p>{step.filters?.map((filter,i)=><p key={i}>{label(filter.field)} · {operators[filter.operator??"eq"]} · <code style={{whiteSpace:"pre-wrap"}}>{Array.isArray(filter.value)?filter.value.map(value=>JSON.stringify(value)).join("\n"):String(filter.value)}</code></p>)}</div>)}</section>}
      {!!result.traversal_schema_versions?.length&&<details><summary>Reached-object query-time schema versions</summary>{result.traversal_schema_versions.map(schema=><p key={`${schema.step}:${schema.version_id}`}>Step {schema.step} · {label(schema.object_type)} · <code>{schema.resource_id} · {schema.version_id}</code></p>)}</details>}
      {!!result.filter_schema_versions?.length && <details><summary>Property filters validated against the query-time schema</summary>{result.filter_schema_versions.map(schema=><p key={schema.version_id}>{label(schema.object_type)} · Schema version <code>{schema.version_id}</code></p>)}</details>}
      {result.query.type_group&&<section className="object-set-interface-values" aria-label="Type-group schema compatibility"><h4>Type-group member compatibility</h4><p>Member records keep their original business identities. Compatibility is checked against the schemas retained by the exact group definition.</p>{result.query.traversal.length?<p>The result contains reached endpoints. Starting-group compatibility receipts are not assigned to these endpoint objects.</p>:<div className="data-scroll"><table><thead><tr><th>Original member</th><th>Schema compatibility</th><th>Retained schema references</th></tr></thead><tbody>{result.type_group_values?.map(value=>{
        const source=result.objects.find(object=>object.resource_id===value.object_id&&object.version_id===value.object_version_id);
        const binding=result.type_group_bindings?.schemas.find(item=>item.schema.version_id===value.schema_version_id&&item.object_type===source?.object_type);
        return <tr key={value.object_version_id}><th scope="row">{source?.display_name??"Original member unavailable"}{source&&investigate(source)}</th><td>{binding&&source?label(value.status):"Retained schema binding unavailable"}</td><td><details><summary>{source?label(source.object_type):"Member schema"} · exact references</summary><p>Expected schema: {value.schema_version_id}</p><p>Actual object schema: {source?.schema_version_id??"Unavailable"}</p><p>Object: {value.object_id} · {value.object_version_id}</p></details></td></tr>;
      })}</tbody></table>{!result.type_group_values?.length&&result.objects.length>0&&<p role="status">Member compatibility receipts were not returned; no compatibility claim is inferred.</p>}</div>}</section>}
      {result.query.interface&&<section className="object-set-interface-values" aria-label="Shared interface values"><h4>Shared interface fields</h4><p>Values retain original object identities and exact implementation/schema bindings. They do not create replacement business objects.</p>{result.query.traversal.length?<p>The result contains reached endpoints. Interface values describe starting objects only and are not projected onto these endpoints.</p>:<div className="data-scroll"><table><thead><tr><th>Original object</th><th>Shared values</th><th>Mapping state</th></tr></thead><tbody>{result.interface_values?.map(value=>{
        const source=result.objects.find(object=>object.resource_id===value.object_id&&object.version_id===value.object_version_id);
        const binding=result.interface_bindings?.implementations.find(item=>item.implementation.resource_id===value.implementation_resource_id&&item.implementation.version_id===value.implementation_version_id&&item.schema.version_id===value.schema_version_id);
        return <tr key={`${value.object_version_id}:${value.implementation_version_id}`}><th scope="row">{source?.display_name??"Original object unavailable"}{source&&investigate(source)}</th><td>{value.status==="AVAILABLE"&&binding&&value.values?<dl>{Object.entries(value.values).map(([field,entry])=><div key={field}><dt>{label(field)}</dt><dd>{result.interface_bindings?.fields[field]?.kind==="reference"&&typeof entry==="string"?<details><summary>Linked {label(result.interface_bindings.fields[field].target_type??"resource")}</summary><code>{entry}</code></details>:entry===null?"No value retained":typeof entry==="object"?JSON.stringify(entry):String(entry)}</dd></div>)}</dl>:"Shared fields unavailable for this retained schema/implementation"}</td><td>{label(value.status)}<details><summary>Exact projection references</summary><p>Object: {value.object_id} · {value.object_version_id}</p><p>Implementation: {value.implementation_resource_id} · {value.implementation_version_id}</p><p>Schema: {value.schema_version_id}</p></details></td></tr>;
      })}</tbody></table></div>}</section>}
      <div className="data-scroll"><table><thead><tr><th>Object</th><th>Type</th><th>Authority & investigation</th><th>Values & provenance</th></tr></thead><tbody>{result.objects.map(object => <tr key={object.version_id}><td>{object.display_name}<small>{object.identity_key}</small></td><td>{label(object.object_type)}</td><td><span>{label(object.authority_state)}  -  {label(object.evidence_class)}</span>{investigate(object)}</td><td><details><summary>Inspect returned version</summary><dl className="resource-fields">{Object.entries(object.attributes).map(([key, value]) => <div key={key}><dt>{label(key)}</dt><dd>{typeof value === "object" ? JSON.stringify(value) : String(value)}</dd></div>)}</dl><p>Object: {object.resource_id}</p><p>Version: {object.version_id}</p><p>Evidence: {label(object.evidence_class)}</p><p>Effective from: {object.valid_from}</p></details></td></tr>)}</tbody></table></div>
      {!result.total && <p className="empty-state">No objects match this query. Try another type, value or relationship.</p>}
      <div className="toolbar"><button className="quiet" disabled={busy || result.query.offset === 0} onClick={() => goToPage(Math.max(0, result.query.offset - result.query.limit))}>Previous</button><span>{result.total ? result.query.offset + 1 : 0}–{Math.min(result.query.offset + result.objects.length, result.total)} of {result.total}</span><button className="quiet" disabled={busy || result.next_offset === null} onClick={() => goToPage(result.next_offset ?? 0)}>Next</button></div>
      <details><summary>Reusable query contract</summary><p>Time is fixed across pages. Run Explore objects again to refresh.</p><pre>{JSON.stringify(result.query, null, 2)}</pre></details>
      {(executionFamily!=="groups"||Boolean(result.query.interface||result.query.type_group))&&<DerivedPropertyRun key={`derived:${JSON.stringify(result.query)}`} token={token} definitions={definitions.filter(item => item.object_type === "DerivedProperty")} query={result.query}/>}
      {executionFamily !== "groups" && <ObjectBindingAction key={JSON.stringify(result.query)} token={token} bindings={definitions.filter(item => item.object_type === "ObjectBinding")} query={result.query} count={result.total} onProposal={onProposal}/>}
      {(executionFamily !== "groups" || Boolean(result.query.interface||result.query.type_group)) && <details><summary>Save this Object Set for shared use</summary><form className="resource-form" onSubmit={publish}><label>Set name<input name="setName" required maxLength={200}/></label><label>Purpose and review rationale<input name="rationale" required minLength={10} maxLength={2000}/></label><label><input type="checkbox" name="fixed"/>Keep this exact query time</label><button disabled={busy}>Propose publication</button></form><p>Without a fixed time, the accepted definition returns effective objects when it is run. Publication uses the shared change-review process.</p></details>}
    </>}
    {publication && <p role="status">Object Set proposed for review. {onProposal ? <button onClick={() => onProposal(publication)}>Open change review</button> : <span>Proposal: {publication}</span>}</p>}
  </section>;
}
