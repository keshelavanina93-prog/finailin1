"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Panel } from "./g8-ui";
import "./regulation.css";

type Rule = {resource:{resource_id:string;version_id:string;display_name:string;attributes:{definition:{provision:string;source_version:string;effective_from:string;deadline:string|null};act_id:string;evidence_id:string;licence_id:string}};assessment:{legal_state:string;applicability:string;effective_obligation:boolean;obligation:string;days_to_deadline:number|null}};
type Reference = {resource_id:string;display_name:string;object_type:string};
type Result = {rules:Rule[];next_offset:number|null};

export default function RegulationWorkspace({token, companyId, onProposal}: {token:string;companyId:string;onProposal:(id:string)=>void}) {
  const [result,setResult]=useState<Result|null>(null);
  const [error,setError]=useState(""); const [busy,setBusy]=useState(false);
  const [query,setQuery]=useState("");
  const [references,setReferences]=useState<Reference[]>([]);
  useEffect(()=>{
    const controller=new AbortController();
    async function load(kind:string):Promise<Reference[]> {
      const collected:Reference[]=[];
      for(let offset=0;offset<10000;offset+=100){
        const response=await fetch(`/api/ontology/resources?object_type=${kind}&offset=${offset}`,{headers:{Authorization:`Bearer ${token}`},signal:controller.signal,cache:"no-store"});
        if(!response.ok)throw new Error("Regulatory reference resources could not be loaded");
        const page:Reference[]=await response.json();collected.push(...page);if(page.length<100)return collected;
      }
      throw new Error("Reference list exceeds the supported selection size");
    }
    void Promise.all(["RegulatoryAct","Licence","SourceEvidence"].map(load)).then(pages=>setReferences(pages.flat())).catch(e=>{if(!controller.signal.aborted)setError(String(e));});
    return ()=>controller.abort();
  },[token]);
  async function request(path:string, body?:unknown) {
    const response=await fetch(`/api/ontology/regulation/${path}`,{method:body?"POST":"GET",headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},body:body?JSON.stringify(body):undefined,cache:"no-store"});
    const data=await response.json(); if(!response.ok) throw new Error(typeof data.detail==="string"?data.detail:JSON.stringify(data.detail));return data;
  }
  async function assess(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();setBusy(true);setError("");setResult(null);
    const form=new FormData(event.currentTarget);const params=new URLSearchParams({legal_entity_id:companyId,activity:String(form.get("activity")),at:`${form.get("at")}T00:00:00Z`});
    if(form.get("customers"))params.set("customer_count",String(form.get("customers")));
    if(form.get("known"))params.set("known_at",`${form.get("known")}T23:59:59Z`);
    setQuery(params.toString());
    try{setResult(await request(`rules?${params}`));}catch(e){setError(String(e));}finally{setBusy(false);}
  }
  async function propose(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();setBusy(true);setError("");const f=new FormData(event.currentTarget);
    const text=(key:string)=>String(f.get(key)??"");
    try{const data=await request("proposals",{name:text("name"),key:text("key"),legal_entity_id:companyId,act_id:text("act_id"),licence_id:text("licence_id"),evidence_id:text("evidence_id"),rationale:text("rationale"),definition:{legal_status:text("legal_status"),source_version:text("source_version"),source_version_complete:f.get("complete")==="on",provision:text("provision"),activity:text("rule_activity"),effective_from:text("effective_from"),effective_to:text("effective_to")||null,minimum_customers:text("minimum_customers")?Number(text("minimum_customers")):null,obligation:text("obligation"),deadline:text("deadline")||null,first_reporting_year:null}});onProposal(data.proposal.proposal_id);}catch(e){setError(String(e));}finally{setBusy(false);}
  }
  return <>
    <Panel title="Regulatory obligations">
      <p>Assess reviewed interpretations for the selected company. Activity and customer count are scenario inputs; this assessment does not certify compliance or create accounting entries.</p>
      <form onSubmit={assess} className="g8-regulation-form">
        <label>Activity<select name="activity"><option>DISTRIBUTION</option><option>TRANSMISSION</option><option>SUPPLY</option></select></label>
        <label>Customer count<input name="customers" type="number" min="0" /></label>
        <label>Legal date<input name="at" type="date" required defaultValue={new Date().toISOString().slice(0,10)}/></label>
        <label>Known by (optional)<input name="known" type="date" /></label>
        <button disabled={busy||!companyId}>Assess obligations</button>
      </form>
      {!companyId&&<p>Select a company to assess or propose rules.</p>}
      {error&&<p role="alert">{error}</p>}
      {result&&!result.rules.length&&<p>No reviewed rules for this company on this page. This is not a finding of no legal obligations.</p>}
      {result?.rules.map(({resource:r,assessment:a})=><article key={r.version_id} className="g8-regulation-rule"><h3>{r.display_name}</h3><p>{a.legal_state.replaceAll("_"," ")} · {a.applicability.replaceAll("_"," ")}</p><p>{a.obligation}</p><dl><dt>Provision</dt><dd>{r.attributes.definition.provision}</dd><dt>Source version</dt><dd>{r.attributes.definition.source_version}</dd><dt>Effective from</dt><dd>{r.attributes.definition.effective_from}</dd><dt>Deadline</dt><dd>{r.attributes.definition.deadline??"Not specified"}{a.days_to_deadline!==null?` (${a.days_to_deadline} days from assessment date)`:""}</dd><dt>Rule version</dt><dd>{r.version_id}</dd><dt>Evidence</dt><dd>{r.attributes.evidence_id}</dd><dt>Act / licence</dt><dd>{r.attributes.act_id} / {r.attributes.licence_id}</dd></dl></article>)}
      {result?.next_offset!==null&&result?.next_offset!==undefined&&<button disabled={busy} onClick={async()=>{setBusy(true);setError("");try{setResult(await request(`rules?${query}&offset=${result.next_offset}`));}catch(e){setError(String(e));}finally{setBusy(false);}}}>Next page</button>}
    </Panel>
    <Panel title="Propose a source-backed interpretation">
      <p>Select the accepted act, licence and retained source from Ontology. Submission creates a review proposal. It does not activate a rule.</p>
      <form onSubmit={propose} className="g8-regulation-form">
        {[["name","Rule name"],["key","Stable rule key"],["source_version","Exact legal source version"],["provision","Article / provision"]].map(([name,label])=><label key={name}>{label}<input name={name} required /></label>)}
        {[["act_id","Regulatory act","RegulatoryAct"],["licence_id","Licence","Licence"],["evidence_id","Retained source evidence","SourceEvidence"]].map(([name,label,kind])=><label key={name}>{label}<select name={name} required defaultValue=""><option value="">Select an accepted {label.toLowerCase()}</option>{references.filter(r=>r.object_type===kind).map(r=><option key={r.resource_id} value={r.resource_id}>{r.display_name}</option>)}</select></label>)}
        <label>Legal status<select name="legal_status"><option>DRAFT</option><option>POLICY_INTENT</option><option>ENACTED</option></select></label>
        <label>Activity<select name="rule_activity"><option>DISTRIBUTION</option><option>TRANSMISSION</option><option>SUPPLY</option></select></label>
        <label>Effective from<input name="effective_from" type="date" required/></label>
        <label>Effective until (exclusive)<input name="effective_to" type="date"/></label>
        <label>Deadline<input name="deadline" type="date"/></label>
        <label>Minimum customers, if applicable<input name="minimum_customers" type="number" min="0"/></label>
        <label><input name="complete" type="checkbox"/> Complete applicable source version has been verified</label>
        <label>Obligation<textarea name="obligation" required/></label>
        <label>Interpretation rationale<textarea name="rationale" minLength={10} required/></label>
        <button disabled={busy||!companyId}>Submit for review</button>
      </form>
    </Panel>
  </>;
}
