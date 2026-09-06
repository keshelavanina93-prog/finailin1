"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Panel } from "./g8-ui";

type Definition = {resource_id:string;display_name:string;object_type:string;attributes:{schema_id?:string;left_contract_id?:string;right_contract_id?:string;definition:{source_family_field:string;source_family:string;dimensions:string[];partition_fields?:string[];row_role_field?:string;included_row_role?:string;time_field:string;aggregation:string}}};
type Schema = {resource_id:string;identity_key:string};
type Group = {dimensions:Record<string,unknown>;value:string|null;state?:string;reason?:string;components?:{numerator:string;denominator:string};inputs:{resource_id:string;version_id:string}[]};
type Result = {run_id?:string;state:string;groups?:Group[];comparisons?:{dimensions:Record<string,unknown>;state:string;difference:string|null;left:Group|null;right:Group|null}[];contract_version_id:string;authority_check?:{minimum_state:string;checked_at:string;consumption_id:string;proof_hash:string};current_use_authorized?:false};
type AuthorityConsumer = {resource_id:string;version_id:string;display_name:string};

export default function AccountingFacts({token,authorityConsumer}:{token:string;authorityConsumer?:AuthorityConsumer}) {
  const [definitions,setDefinitions]=useState<Definition[]>([]);
  const [schemas,setSchemas]=useState<Schema[]>([]);
  const [selected,setSelected]=useState("");const [error,setError]=useState("");
  const [runId,setRunId]=useState("");
  const [result,setResult]=useState<Result|null>(null);const [busy,setBusy]=useState(false);
  useEffect(()=>{
    const controller=new AbortController();
    async function get(path:string){const response=await fetch(`/api/ontology/${path}`,{headers:{Authorization:`Bearer ${token}`},cache:"no-store",signal:controller.signal});if(!response.ok)throw new Error("Accounting definitions could not be loaded");return response.json();}
    void Promise.all([get("model/definitions"),get("catalog")]).then(([d,s])=>{if(!controller.signal.aborted){setDefinitions(d);setSchemas(s);}}).catch(e=>{if(!controller.signal.aborted)setError(String(e));});
    return ()=>controller.abort();
  },[token]);
  const choice=definitions.find(d=>d.resource_id===selected);
  const spec=choice?.attributes.definition;
  async function calculate(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();if(!choice)return;setBusy(true);setError("");setResult(null);
    const form=new FormData(event.currentTarget);const date=String(form.get("date")??"");
    function query(d:Definition) {
      const type=schemas.find(s=>s.resource_id===d.attributes.schema_id)?.identity_key;
      if(!type)throw new Error("The fact schema is unavailable");
      const contract=d.attributes.definition;
      const filters=[{field:contract.source_family_field,value:contract.source_family}];
      if(contract.row_role_field&&contract.included_row_role)filters.push({field:contract.row_role_field,value:contract.included_row_role});
      if(date)filters.push({field:contract.time_field,value:date});
      return {object_type:type,filters};
    }
    try{
      const comparison=choice.object_type==="FactReconciliation";
      const guarded=!comparison&&!!authorityConsumer;
      const left=definitions.find(d=>d.resource_id===choice.attributes.left_contract_id);
      const right=definitions.find(d=>d.resource_id===choice.attributes.right_contract_id);
      if(comparison&&(!left||!right))throw new Error("Both reviewed fact contracts are required");
      const body=comparison?{left:query(left!),right:query(right!),as_of:date||null}:{query:query(choice),group_by:form.getAll("group"),as_of:date||null,...(guarded?{consumer:{resource_id:authorityConsumer!.resource_id,version_id:authorityConsumer!.version_id}}:{})};
      const response=await fetch(`/api/ontology/model/facts/${selected}/${comparison?"reconcile":guarded?"aggregate/guarded":"aggregate"}`,{method:"POST",headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},body:JSON.stringify(body)});
      const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==="string"?data.detail:JSON.stringify(data.detail));setResult(data);
    }catch(e){setError(String(e));}finally{setBusy(false);}
  }
  return <Panel title="Accounting facts & reconciliation">
    <p>Calculate from reviewed fact contracts or compare overlapping representations. Results retain source versions and do not certify financial statements.</p>
    <p>{authorityConsumer&&choice?.object_type==="FactContract"?`Authority checked for ${authorityConsumer.display_name}. The accepted consumer determines the required state and exact dependency versions.`:"Source-bound analysis. Select an ontology consumer with an authority contract to check eligibility before retaining an aggregate."}</p>
    <form onSubmit={calculate}>
      <label>Reviewed contract<select value={selected} onChange={e=>{setSelected(e.target.value);setResult(null);setError("");}}><option value="">Choose a contract</option>{definitions.filter(d=>["FactContract","FactReconciliation"].includes(d.object_type)).map(d=><option key={d.resource_id} value={d.resource_id}>{d.display_name}</option>)}</select></label>
      <label>Exact source date (required for snapshots)<input name="date" type="date"/></label>
      {choice?.object_type==="FactContract"&&<fieldset><legend>Group by</legend>{spec?.dimensions.map(d=><label key={d}><input name="group" type="checkbox" value={d}/>{d.replaceAll("_"," ")}</label>)}<p>Always separated: {[...(spec?.partition_fields??[]),"currency / unit"].join(", ")}. Without a date, a movement calculation covers all facts selected by this contract.</p></fieldset>}
      <button disabled={busy||!choice}>{busy?"Calculating…":authorityConsumer&&choice?.object_type==="FactContract"?"Check authority & calculate":"Calculate / reconcile"}</button>
    </form>
    <form onSubmit={async event=>{event.preventDefault();setBusy(true);setError("");setResult(null);try{const response=await fetch(`/api/ontology/model/fact-runs/${encodeURIComponent(runId)}`,{headers:{Authorization:`Bearer ${token}`},cache:"no-store"});const data=await response.json();if(!response.ok)throw new Error(data.detail??"Run unavailable");setResult(data);}catch(e){setError(String(e));}finally{setBusy(false);}}}><label>Retained calculation reference<input value={runId} onChange={e=>setRunId(e.target.value)} required pattern="fcr_[a-f0-9]{64}"/></label><button disabled={busy}>Open retained calculation</button></form>
    {error&&<p role="alert">{error}</p>}
    {result&&<><p>{result.state} · Contract version {result.contract_version_id}</p>{result.authority_check&&<p role="status">Input authority checked: {result.authority_check.minimum_state} · {new Date(result.authority_check.checked_at).toLocaleString()}. This retained check is historical evidence; a new use requires another check. Financial certification remains unestablished.</p>}{result.run_id&&<details><summary>Retained calculation reference</summary><code>{result.run_id}</code>{result.authority_check&&<p>Authority receipt: {result.authority_check.consumption_id}<br/>Proof: {result.authority_check.proof_hash}</p>}</details>}<div className="g8-table-scroll"><table><thead><tr><th>Coordinates</th><th>Value / difference</th><th>Evidence</th></tr></thead><tbody>
      {result.groups?.map((g,i)=><tr key={i}><td>{Object.entries(g.dimensions).map(([k,v])=>`${k}: ${String(v)}`).join(" · ")}</td><td>{g.value??g.reason??"Unavailable"}{g.components&&<small> ({g.components.numerator} / {g.components.denominator})</small>}</td><td><details><summary>{g.inputs.length} source versions</summary>{g.inputs.map(p=><p key={p.version_id}>{p.resource_id} · {p.version_id}</p>)}</details></td></tr>)}
      {result.comparisons?.map((g,i)=><tr key={i}><td>{Object.entries(g.dimensions).map(([k,v])=>`${k}: ${String(v)}`).join(" · ")}</td><td>{g.state} · {g.difference??"Unavailable"}</td><td>Left {g.left?.value??"missing"} · Right {g.right?.value??"missing"}</td></tr>)}
    </tbody></table></div></>}
  </Panel>;
}
