"use client";

import {useEffect,useState} from "react";
import type {CanonicalResource} from "@finai/contracts";
import ObjectBindingAction from "./object-binding-action";
import {displayName} from "./display-name";

type Pin={resource_id:string;version_id:string};
type Value={object_id:string;object_version_id:string;definition_id?:string;definition_version_id:string;name:string;kind?:string;status:string;value:string|number|null};
type Output={query:unknown;objects:CanonicalResource[];total:number;next_offset:number|null;derived_values:Value[];coverage:string};
type Spec={identity_mode?:string;identity_field:string;display_field?:string;display_property?:Pin;fields:{source_field?:string;derived_property?:Pin;target_field:string}[]};
type Binding=CanonicalResource&{dependencies?:Array<Pin&{relation:string}>};
const record=(value:unknown):value is Record<string,unknown>=>!!value&&typeof value==="object"&&!Array.isArray(value);
const uuid=(value:unknown)=>typeof value==="string"&&/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value);
const pin=(value:unknown):value is Pin=>record(value)&&uuid(value.resource_id)&&uuid(value.version_id);
function specification(binding:CanonicalResource):Spec|null {
 const value=binding.attributes.definition;
 if(!record(value)||typeof value.identity_field!=="string"||!Array.isArray(value.fields)||
    !(typeof value.display_field==="string"&&!value.display_property||pin(value.display_property)&&!value.display_field)||
    !value.fields.every(field=>record(field)&&typeof field.target_field==="string"&&(typeof field.source_field==="string"&&!field.derived_property||pin(field.derived_property)&&!field.source_field)))return null;
 return value as Spec;
}
function properties(spec:Spec):Pin[]{return [...(spec.display_property?[spec.display_property]:[]),...spec.fields.flatMap(field=>field.derived_property?[field.derived_property]:[])];}
function calculated(output:Output,object:CanonicalResource,property:Pin){return output.derived_values.find(value=>value.object_id===object.resource_id&&value.object_version_id===object.version_id&&value.definition_id===property.resource_id&&value.definition_version_id===property.version_id);}

export default function RetainedBindingAction(props:{token:string;invocationId:string;output:Output;onProposal?:(id:string)=>void}) {
 const [opened,setOpened]=useState(false);
 return <details onToggle={event=>{if(event.currentTarget.open)setOpened(true);}}><summary>Prepare a reviewed change from this analysis</summary>{opened&&<BindingSelection {...props}/>}</details>;
}
function BindingSelection({token,invocationId,output,onProposal}:{token:string;invocationId:string;output:Output;onProposal?:(id:string)=>void}) {
 const [catalog,setCatalog]=useState<CanonicalResource[]>([]);
 const [selected,setSelected]=useState("");
 const [frozen,setFrozen]=useState(false);
 const [binding,setBinding]=useState<Binding|null>(null);
 const [error,setError]=useState("");
 const [busy,setBusy]=useState(true);
 const [revision,setRevision]=useState(0);
 useEffect(()=>{
  const controller=new AbortController();
  fetch("/api/ontology/model/definitions",{headers:{Authorization:`Bearer ${token}`},signal:controller.signal,cache:"no-store"}).then(async response=>{
   if(!response.ok)throw new Error("Reviewed binding definitions are unavailable.");
   const data:unknown=await response.json();
   if(!Array.isArray(data))throw new Error("Binding catalog response is invalid.");
   if(!controller.signal.aborted)setCatalog(data.filter((row:CanonicalResource)=>{
    if(row.object_type!=="ObjectBinding"||row.authority_state!=="APPROVED")return false;
    const spec=specification(row);return spec&&properties(spec).length>0&&output.objects.every(object=>properties(spec).every(property=>{
     const value=calculated(output,object,property);return value?.status==="AVAILABLE"&&value.value!==null;
    }));
   }));
  }).catch(failure=>{if(!controller.signal.aborted)setError(failure instanceof Error?failure.message:"Binding catalog unavailable");}).finally(()=>{if(!controller.signal.aborted)setBusy(false);});
  return ()=>controller.abort();
 },[token,output,revision]);
 const candidate=catalog.find(row=>row.version_id===selected);
 useEffect(()=>{
  if(!candidate)return;
  const controller=new AbortController();
  fetch(`/api/ontology/model/definitions/${candidate.resource_id}?version=${candidate.version_id}`,{headers:{Authorization:`Bearer ${token}`},signal:controller.signal,cache:"no-store"}).then(async response=>{
   if(!response.ok)throw new Error("The exact reviewed binding is unavailable.");
   const data:Binding=await response.json();
   if(data.resource_id!==candidate.resource_id||data.version_id!==candidate.version_id||data.object_type!=="ObjectBinding"||data.authority_state!=="APPROVED"||!specification(data))throw new Error("The binding response does not match the selected reviewed version.");
   if(!controller.signal.aborted)setBinding(data);
  }).catch(failure=>{if(!controller.signal.aborted)setError(failure instanceof Error?failure.message:"Binding unavailable");});
  return ()=>controller.abort();
 },[token,candidate]);
 const spec=binding?specification(binding):null;
 const query=record(output.query)?output.query:null;
 const source=binding?.dependencies?.find(dependency=>dependency.relation==="FIELD:source_schema_id");
 const complete=query?.offset===0&&output.total===output.objects.length&&output.next_offset===null&&output.objects.length>=1&&output.objects.length<=100;
 let blocked="";
 if(!complete)blocked="A binding requires a complete retained source page of 1–100 objects, starting at offset zero.";
 else if(!source||!output.objects.every(object=>object.schema_version_id===source.version_id&&object.evidence_class==="SOURCE_BOUND"))blocked="The retained source versions do not match this binding’s exact source schema and source-evidence requirements.";
 else if(spec?.display_property&&output.objects.some(object=>calculated(output,object,spec.display_property!)?.kind!=="text"))blocked="The reviewed display property must provide an available text result for every source object.";
 else if(spec&&output.objects.some(object=>typeof object.attributes[spec.identity_field]!=="string"||!String(object.attributes[spec.identity_field]).trim()||spec.identity_mode==="CANONICAL_REFERENCE"&&!uuid(object.attributes[spec.identity_field])))blocked="A source object has no valid stored target identity. Calculated values cannot supply identity.";
 return <section className="retained-binding-action" aria-label="Reviewed calculated binding">
  <p>Choose an already reviewed mapping. The preview uses this retained analysis; preparing a proposal does not publish or approve a change.</p>
  {busy&&<p role="status">Loading reviewed mappings…</p>}
  {error&&<p role="alert">{error}</p>}
  {!busy&&!catalog.length&&!error&&<p>No reviewed calculated binding matches the available top-level property versions in this result.</p>}
  <label>Reviewed mapping<select disabled={busy||frozen} value={selected} onChange={event=>{setSelected(event.target.value);setBinding(null);setError("");}}><option value="">Choose a mapping</option>{catalog.map(row=><option key={row.version_id} value={row.version_id}>{displayName(row.display_name)}</option>)}</select></label>
  {error&&<button onClick={()=>{setError("");setBusy(true);setBinding(null);setSelected("");setRevision(value=>value+1);}}>Refresh reviewed mappings</button>}
  {candidate&&!binding&&!error&&<p role="status">Checking the exact binding and source schema…</p>}
  {binding&&spec&&<ObjectBindingAction onRequestFrozen={setFrozen} key={`${invocationId}:${binding.version_id}`} token={token} bindings={[binding]} query={output.query} count={output.objects.length} inputResult={{invocation_id:invocationId}} blockedReason={blocked} onProposal={onProposal} preview={<>
   <p>Stored source identities are preserved. {spec.identity_mode==="CANONICAL_REFERENCE"&&spec.fields.length===0?"Only the target display name is proposed to change; existing target attributes are preserved.":"Mapped values below are proposed through the existing independent review."}</p>
   <div className="saved-analysis-table"><table><thead><tr><th>Retained source object</th><th>Stored target identity</th><th>Proposed values</th></tr></thead><tbody>{output.objects.map(object=><tr key={object.version_id}>
    <th scope="row">{displayName(object.display_name)}</th><td>{String(object.attributes[spec.identity_field]??"Unavailable")}<small>{spec.identity_mode==="CANONICAL_REFERENCE"?"Existing canonical target":"Stored source key; target identity assigned by the reviewed binding"}</small></td>
    <td><p>Display name: {spec.display_property?calculated(output,object,spec.display_property)?.value??"Unavailable":String(object.attributes[spec.display_field!]??"Unavailable")}</p>
     {spec.fields.map(field=><p key={field.target_field}>{field.target_field.replaceAll("_"," ")}: {field.derived_property?calculated(output,object,field.derived_property)?.value??"Unavailable":String(object.attributes[field.source_field!]??"Not supplied")}</p>)}
     <details><summary>Exact source & calculation references</summary><pre>{JSON.stringify({source:{resource_id:object.resource_id,version_id:object.version_id},binding:{resource_id:binding.resource_id,version_id:binding.version_id},properties:properties(spec),input_result:{invocation_id:invocationId}},null,2)}</pre></details>
    </td>
   </tr>)}</tbody></table></div>
  </>}/>}
 </section>;
}
