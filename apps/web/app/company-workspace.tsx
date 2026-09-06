"use client";

import {useEffect, useState} from "react";
import type {CanonicalResource} from "@finai/contracts";
import {Panel, Badge} from "./g8-ui";
import {displayName} from "./display-name";

type Node = CanonicalResource;
export type CompanyIndex = {source_companies:Node[];workspaces:{configuration:Node;company:Node;enterprise:Node;domain_pack:Node}[];reported_groups?:{reporter:Node;reporting_year:number;members:{company:Node;binding:Node;reported_percent:string|null;former_indicator:string}[]}[]};
export type Context = {company:Node;accounting_state:string;
 relationships:{kind:string;record:Node;source:Node;target:Node}[];
 structural_resources:Node[]; dimensions:Node[];
 ledgers:{ledger:Node;calendar_id:Node|null;chart_id:Node|null;currency_id:Node|null;books:Node[];periods:Node[];ready:boolean}[];
 disclosures:{binding:Node;reporter:Node;party:Node;observation:Node}[];
 accounting_sources:{scope:Node;bindings:Node[]}[];
 licence_evidence:{binding:Node;notice:Node|null;licence:Node|null}[];
};

export default function CompanyWorkspace({token,index,companyId,onSelect,onInspect}:{token:string;index:CompanyIndex|null;companyId:string;onSelect:(node:Node)=>void;onInspect:(node:Node)=>void}) {
 const [context,setContext]=useState<Context|null>(null);
 const [error,setError]=useState(""); const [busy,setBusy]=useState(!!companyId);
 const [selection,setSelection]=useState<Record<string,{resource_id:string;version_id:string}>|null>(null);
 const [ledgerId,setLedgerId]=useState(""); const [bookId,setBookId]=useState(""); const [periodId,setPeriodId]=useState("");
 useEffect(()=>{
  const controller=new AbortController();
  if(!companyId)return ()=>controller.abort();
  void fetch(`/api/ontology/company-context?company_id=${encodeURIComponent(companyId)}`,{headers:{Authorization:`Bearer ${token}`},signal:controller.signal,cache:"no-store"})
   .then(async r=>{const data=await r.json();if(!r.ok)throw Error(data.detail??"Company context unavailable");if(!controller.signal.aborted)setContext(data.context);})
   .catch(e=>{if(!controller.signal.aborted)setError(String(e));}).finally(()=>{if(!controller.signal.aborted)setBusy(false);});
  return ()=>controller.abort();
 },[token,companyId]);
 useEffect(()=>{
  const controller=new AbortController();
  if(!companyId||!ledgerId||!bookId||!periodId)return ()=>controller.abort();
  const params=new URLSearchParams({company_id:companyId,ledger_id:ledgerId,book_id:bookId,period_id:periodId});
  void fetch(`/api/ontology/company-context?${params}`,{headers:{Authorization:`Bearer ${token}`},signal:controller.signal,cache:"no-store"})
   .then(async response=>{const data=await response.json();if(!response.ok)throw Error(data.detail??"Accounting context rejected");if(!controller.signal.aborted)setSelection(data.accounting_selection);})
   .catch(e=>{if(!controller.signal.aborted)setError(String(e));});
  return ()=>controller.abort();
 },[token,companyId,ledgerId,bookId,periodId]);
 const ledger=context?.ledgers.find(l=>l.ledger.resource_id===ledgerId);
 const groups=[...new Map(index?.workspaces.map(w=>[w.enterprise.resource_id,w.enterprise])??[]).values()];
 return <>
  <Panel title="Company workspaces and reported structure">
   {groups.map(group=><section key={group.resource_id}><h3>{displayName(group.display_name)}</h3><p>Configured enterprise workspace · corporate ownership is shown separately below.</p>
    {index?.workspaces.filter(w=>w.enterprise.resource_id===group.resource_id).map(w=><button key={w.configuration.resource_id} className="g8-panel-action" aria-pressed={companyId===w.company.resource_id} onClick={()=>onSelect(w.company)}>{displayName(w.configuration.display_name)}<small>{displayName(w.domain_pack.display_name)}</small></button>)}
   </section>)}
   {!groups.length&&<p>No company workspaces have been configured.</p>}
   <h3>Reported subsidiary groups</h3>
   <p>These are dated filing relationships. They do not establish current direct ownership, current licence status or consolidation scope.</p>
   {index?.reported_groups?.map(group=><section key={`${group.reporter.resource_id}:${group.reporting_year}`} aria-label={`${displayName(group.reporter.display_name)} reported group`}>
    <h4><button onClick={()=>onSelect(group.reporter)}>{displayName(group.reporter.display_name)}</button> · {group.reporting_year} filing</h4>
    <ul>{group.members.map(member=><li key={member.binding.resource_id}>
     <button onClick={()=>onSelect(member.company)}>{displayName(member.company.display_name)}</button>
     {member.company.attributes.registration_code?` · ID ${String(member.company.attributes.registration_code)}`:""}
     {member.reported_percent!==null?` · reported ${member.reported_percent}%`:" · participation not stated"}
     {member.former_indicator?" · former-party marker in source":""}
     <button onClick={()=>onInspect(member.binding)}>Filing evidence</button>
    </li>)}</ul>
   </section>)}
   <details><summary>Other company contexts with accounting sources</summary><p>Source-bound companies remain separate until their enterprise or operating relationships are established.</p>{index?.source_companies.filter(c=>!index.workspaces.some(w=>w.company.resource_id===c.resource_id)).map(c=><button className="g8-panel-action" key={c.resource_id} onClick={()=>onSelect(c)}>{displayName(c.display_name)}</button>)}</details>
  </Panel>
  {busy&&<p role="status">Resolving company relationships and accounting context…</p>}{error&&<p role="alert">{error}</p>}
  {context&&<>
   <Panel title={displayName(context.company.display_name)} aside={<Badge>Canonical company context</Badge>}>
    <p>Company ID: {context.company.resource_id}</p>
    <h3>Legal, operating and consolidation relationships</h3>
    {context.relationships.length?<table><thead><tr><th>From</th><th>Relationship</th><th>To</th><th>Evidence</th></tr></thead><tbody>{context.relationships.map(r=><tr key={r.record.resource_id}><td>{displayName(r.source.display_name)}</td><td>{r.kind.replaceAll("_"," ")}</td><td>{displayName(r.target.display_name)}</td><td><button onClick={()=>onInspect(r.record)}>Inspect version</button></td></tr>)}</tbody></table>:<p>No effective structural relationships are accepted for this company. Historical disclosures below do not create current ownership or consolidation membership.</p>}
    <h3>Accounting context</h3>
    {!context.ledgers.length?<p>No accepted ledger is configured for this company. Accounting values and books cannot be inferred from the company name.</p>:<>
     <label>Company ledger<select value={ledgerId} onChange={e=>{setSelection(null);setLedgerId(e.target.value);setBookId("");setPeriodId("");}}><option value="">Select ledger</option>{context.ledgers.map(l=><option key={l.ledger.resource_id} value={l.ledger.resource_id}>{displayName(l.ledger.display_name)}</option>)}</select></label>
     {ledger&&<><p>Chart: {ledger.chart_id?.display_name??"Unresolved"} · Calendar: {ledger.calendar_id?.display_name??"Unresolved"} · Currency: {ledger.currency_id?.display_name??"Unresolved"}</p>
      <label>Accounting book<select value={bookId} onChange={e=>{setSelection(null);setBookId(e.target.value);}}><option value="">Select book</option>{ledger.books.map(b=><option key={b.resource_id} value={b.resource_id}>{displayName(b.display_name)}</option>)}</select></label>
      <label>Fiscal period<select value={periodId} onChange={e=>{setSelection(null);setPeriodId(e.target.value);}}><option value="">Select period</option>{ledger.periods.map(p=><option key={p.resource_id} value={p.resource_id}>{displayName(p.display_name)}</option>)}</select></label>
      <button onClick={()=>onInspect(ledger.ledger)}>Inspect ledger dependencies</button>
     </>}
    </>}
    {selection&&<details><summary>Validated accounting context · exact canonical versions</summary><dl>{Object.entries(selection).map(([field,pin])=><div key={field}><dt>{field}</dt><dd>{pin.resource_id} · {pin.version_id}</dd></div>)}</dl></details>}
    <h3>Company analytical dimensions</h3>
    {context.dimensions.length?context.dimensions.map(d=><p key={d.resource_id}><button onClick={()=>onInspect(d)}>{displayName(d.display_name)}</button> · {String(d.attributes.source_header)}</p>):<p>No source analytical dimension model is bound to this company.</p>}
    <h3>Company-bound source accounting</h3>
    {context.accounting_sources.length?context.accounting_sources.map(s=><section key={s.scope.resource_id}><button className="g8-link" onClick={()=>onInspect(s.scope)}>{displayName(s.scope.display_name)}</button><p>{String(s.scope.attributes.worksheet)} · {String(s.scope.attributes.observed_from)} to {String(s.scope.attributes.observed_through)}</p>{s.bindings.length?s.bindings.map(b=><p key={b.resource_id}>{String(b.attributes.source_use).replaceAll("_"," ")} <button onClick={()=>onInspect(b)}>Inspect accounting binding</button></p>):<p>Accounting use awaits configuration.</p>}</section>):<p>No source accounting scope is bound to this company.</p>}
   </Panel>
   <Panel title="Reported company relationships">
    <p>These dated source statements remain separate from effective legal structure. Select a related company to resolve its own context.</p>
    {context.disclosures.map(d=>{const o=d.observation.attributes.observation as {reported_role:string;reported_percent:string|null;former_indicator:string};return <div key={d.binding.resource_id}><strong>{String(d.binding.attributes.reporting_year)}</strong> · {displayName(d.reporter.display_name)} reported <button className="g8-link" onClick={()=>onSelect(d.party)}>{displayName(d.party.display_name)}</button> as {o.reported_role.toLowerCase()} · {o.reported_percent===null?"share not stated":`${o.reported_percent}%`}{o.former_indicator?` · former-party marker: ${o.former_indicator}`:""} <button onClick={()=>onInspect(d.binding)}>Source evidence</button></div>;})}
    {!context.disclosures.length&&<p>No reviewed corporate disclosure bindings.</p>}
   </Panel>
   <Panel title="Licence evidence">
    {context.licence_evidence.map(l=><p key={l.binding.resource_id}>{l.licence?.display_name??"Licence dependency requires review"} · historical issuance evidence <button onClick={()=>onInspect(l.binding)}>Inspect licence binding</button></p>)}
    {!context.licence_evidence.length&&<p>No licence notice is bound to this company.</p>}
   </Panel>
  </>}
 </>;
}
