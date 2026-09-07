"use client";

import {useEffect,useState} from "react";
import type {CanonicalResource,CompanyJournalListResponse,CompanyJournalDetailResponse} from "@finai/contracts";
import "./company-journal-explorer.css";

type Props={expectedSelection:Record<string,{resource_id:string;version_id:string}>;token:string;companyId:string;ledgerId:string;bookId:string;periodId:string;currency:CanonicalResource|null;onInspect:(resource:CanonicalResource,knownAt:string)=>void;onTrace?:(resource:CanonicalResource,knownAt:string)=>void};
const text=(value:unknown)=>typeof value==="string"?value:"Not retained";
const human=(value:string)=>value.toLowerCase().replaceAll("_"," ");
const selectionFields=["legal_entity_id","ledger_id","book_id","period_id","chart_id","currency_id","calendar_id"] as const;
function sameSelection(actual:unknown,expected:Record<string,{resource_id:string;version_id:string}>):boolean{
 if(!actual||typeof actual!=="object")return false;
 const values=actual as Record<string,unknown>;
 return selectionFields.every(field=>{
  const value=values[field];const pin=expected[field];
  return Boolean(pin&&value&&typeof value==="object"&&"resource_id" in value&&"version_id" in value&&value.resource_id===pin.resource_id&&value.version_id===pin.version_id);
 });
}
export default function CompanyJournalExplorer(props:Props){
 return <JournalPage key={JSON.stringify([props.token,props.companyId,props.ledgerId,props.bookId,props.periodId,selectionFields.map(field=>[field,props.expectedSelection[field]?.resource_id,props.expectedSelection[field]?.version_id])])} {...props}/>;
}
function JournalPage({expectedSelection,token,companyId,ledgerId,bookId,periodId,currency,onInspect,onTrace}:Props){
 const [request,setRequest]=useState({offset:0,snapshot:"",revision:0});
 const [list,setList]=useState<CompanyJournalListResponse|null>(null);
 const [listError,setListError]=useState("");
 const [selected,setSelected]=useState<CanonicalResource|null>(null);
 const [detail,setDetail]=useState<CompanyJournalDetailResponse|null>(null);
 const [detailError,setDetailError]=useState("");
 const [detailRevision,setDetailRevision]=useState(0);
 useEffect(()=>{
  const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),20000);
  const params=new URLSearchParams({company_id:companyId,ledger_id:ledgerId,book_id:bookId,period_id:periodId,limit:"25",offset:String(request.offset)});
  if(request.snapshot)params.set("snapshot_at",request.snapshot);
  let disposed=false;
  void fetch(`/api/ontology/company-journals?${params}`,{headers:{Authorization:`Bearer ${token}`},cache:"no-store",signal:controller.signal}).then(async response=>{
   const data=await response.json();if(!response.ok)throw Error(typeof data.detail==="string"?data.detail:`Journal readback unavailable (${response.status}).`);
   if(data.purpose!=="CANONICAL_JOURNAL_READBACK"||data.current_use_authorized!==false||data.erp_posted!==false||request.snapshot&&data.snapshot_at!==request.snapshot)throw Error("Journal response did not preserve the readback contract and requested snapshot.");
   if(!sameSelection(data.selection,expectedSelection)||data.selection.legal_entity_id.resource_id!==companyId||data.selection.ledger_id.resource_id!==ledgerId||data.selection.book_id.resource_id!==bookId||data.selection.period_id.resource_id!==periodId)throw Error("The accounting selection has changed. Refresh company context and validate the ledger, book and period again before reading journals.");
   if(!disposed)setList(data);
  }).catch(error=>{if(!disposed)setListError(controller.signal.aborted?"Journal readback timed out. Retry or refresh the context.":String(error));}).finally(()=>clearTimeout(timer));
  return()=>{disposed=true;controller.abort();clearTimeout(timer);};
 },[token,companyId,ledgerId,bookId,periodId,request,expectedSelection]);
 useEffect(()=>{
  if(!selected||!list)return;
  const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),20000);let disposed=false;
  const params=new URLSearchParams({company_id:companyId,ledger_id:ledgerId,book_id:bookId,period_id:periodId,version_id:selected.version_id,snapshot_at:list.snapshot_at});
  void fetch(`/api/ontology/company-journals/${selected.resource_id}?${params}`,{headers:{Authorization:`Bearer ${token}`},cache:"no-store",signal:controller.signal}).then(async response=>{
   const data=await response.json();if(!response.ok)throw Error(typeof data.detail==="string"?data.detail:`Journal detail unavailable (${response.status}).`);
   if(data.purpose!=="CANONICAL_JOURNAL_READBACK"||data.current_use_authorized!==false||data.erp_posted!==false||!sameSelection(data.selection,list.selection)||data.journal?.resource_id!==selected.resource_id||data.journal?.version_id!==selected.version_id||data.snapshot_at!==list.snapshot_at)throw Error("Journal detail did not match the exact accounting selection, journal version and snapshot. Refresh company context before continuing.");
   if(!disposed)setDetail(data);
  }).catch(error=>{if(!disposed)setDetailError(controller.signal.aborted?"Journal detail timed out. Retry the selected retained version.":String(error));}).finally(()=>clearTimeout(timer));
  return()=>{disposed=true;controller.abort();clearTimeout(timer);};
 },[token,companyId,ledgerId,bookId,periodId,selected,list,detailRevision]);
 function page(offset:number,refresh=false){setList(null);setListError("");setSelected(null);setDetail(null);setDetailError("");setRequest(previous=>({offset,snapshot:refresh?"":list?.snapshot_at??previous.snapshot,revision:previous.revision+1}));}
 function choose(journal:CanonicalResource){setSelected(journal);setDetail(null);setDetailError("");setDetailRevision(value=>value+1);}
 function actions(resource:CanonicalResource){return <span className="company-journal-actions"><button onClick={()=>onInspect(resource,list!.snapshot_at)}>Inspect</button>{onTrace&&<button onClick={()=>onTrace(resource,list!.snapshot_at)}>Trace</button>}</span>;}
 const balance=detail?.integrity.state==="COMPLETE_BALANCED"?detail.integrity.balance:null;
 return <section className="company-journal-explorer" aria-label="Company journal explorer">
  <header><div><h3>Journal explorer</h3><p>Accepted journal definitions for the selected ledger, book and period. Readback does not establish ERP posting or current permission to use amounts.</p></div><button onClick={()=>page(0,true)}>Refresh journals</button></header>
  {listError&&<p role="alert">{listError}<button onClick={()=>page(request.offset)}>Retry journal page</button></p>}
  {!list&&!listError&&<p role="status">Reading retained journals…</p>}
  {list&&<><p>Snapshot: {new Date(list.snapshot_at).toLocaleString()} · {list.total} matching journal definitions.</p>
   {list.coverage.state!=="COMPLETE"&&<p role="status">Coverage unresolved: {list.coverage.unresolved_journal_count} journal definitions could not be resolved. This is not a complete accounting result.</p>}
   {!list.items.length?<p>No journal definitions were returned for this selection and snapshot. This is not a zero trial balance.</p>:<div className="company-journal-table"><table><thead><tr><th>Journal / reference</th><th>Posting date</th><th>Definition review</th><th>Evidence</th></tr></thead><tbody>{list.items.map(item=><tr key={item.journal.version_id} aria-selected={selected?.version_id===item.journal.version_id}><th scope="row"><button onClick={()=>choose(item.journal)}>{item.journal.display_name}</button><small>{text(item.journal.attributes.reference)}</small></th><td>{text(item.journal.attributes.posting_date)}</td><td>{human(item.journal.authority_state)}</td><td>{human(item.journal.evidence_class)}</td></tr>)}</tbody></table></div>}
   <footer><button disabled={request.offset===0} onClick={()=>page(Math.max(0,request.offset-list.limit))}>Previous</button><span>{list.items.length?`${list.offset+1}–${list.offset+list.items.length}`:"No rows"}</span><button disabled={list.next_offset===null} onClick={()=>list.next_offset!==null&&page(list.next_offset)}>Next</button></footer>
  </>}
  {selected&&<section aria-label="Selected retained journal"><h4>{selected.display_name}</h4>{list&&actions(selected)}
   {detailError&&<p role="alert">{detailError}<button onClick={()=>{setDetailError("");setDetailRevision(value=>value+1);}}>Retry exact journal</button></p>}
   {!detail&&!detailError&&<p role="status">Reading exact journal lines and provenance…</p>}
   {detail&&<><p><strong>{human(detail.integrity.state)}</strong> · {detail.integrity.resolved_line_count} resolved of {detail.integrity.declared_line_count} declared lines.</p>{detail.integrity.issues.map((issue,index)=><p role="status" key={index}>{issue}</p>)}
    <p>Current accounting eligibility: {human(detail.binding_eligibility.state)} · {detail.binding_eligibility.reason}{detail.binding_eligibility.checked_at&&` Checked ${new Date(detail.binding_eligibility.checked_at).toLocaleString()}.`}</p>
    <div className="company-journal-table"><table><thead><tr><th>Line / account</th><th>Debit</th><th>Credit</th><th>Source provenance</th></tr></thead><tbody>{detail.lines.map(row=>{
     const amount=row.line.attributes.amount as {amount?:string;currency_id?:string}|undefined;
     return <tr key={row.line.version_id}><th scope="row">{row.line.display_name}{actions(row.line)}<small>{row.account.display_name}</small>{actions(row.account)}</th><td>{row.line.attributes.side==="DEBIT"?text(amount?.amount):"—"}</td><td>{row.line.attributes.side==="CREDIT"?text(amount?.amount):"—"}</td><td>{row.source_record.display_name}{actions(row.source_record)}</td></tr>;
    })}</tbody>{balance&&<tfoot><tr><th>Whole journal · server balance</th><td>{balance.debit}</td><td>{balance.credit}</td><td>{currency?.resource_id===balance.currency_id?currency.display_name:"Currency reference retained below"}</td></tr></tfoot>}</table></div>
    {!balance&&<p>No whole-journal balance is displayed while its integrity is incomplete or unavailable.</p>}
    <section aria-label="Journal analytical assignments"><h4>Analytical assignments by line</h4><p>These are reviewed analytical requirements and attributions. They are separate from the journal’s mathematical debit/credit balance.</p>
     {detail.lines.map(row=><details key={row.line.version_id}><summary>{row.line.display_name} · {row.account.display_name} · {human(row.dimensions?.state??"UNESTABLISHED")}</summary>
      {!row.dimensions?<p>No analytical policy readback was returned for this line.</p>:<>
       {row.dimensions.issues.map((issue,index)=><p role="status" key={index}>{issue}</p>)}
       {row.dimensions.policy?<><p>Reviewed account policy: {row.dimensions.policy.display_name}</p>{actions(row.dimensions.policy)}<details><summary>Exact reviewed rule references</summary><pre>{JSON.stringify(row.dimensions.policy.attributes.definition,null,2)}</pre></details></>:<p>No reviewed account policy is available in this readback.</p>}
       {!row.dimensions.assignments.length&&<p>No analytical member assignments were returned for this line. Policy completeness is determined by the server.</p>}
       {row.dimensions.assignments.map((assignment,index)=><article key={`${assignment.member.version_id}:${index}`}><p><strong>{assignment.dimension.display_name}</strong> · {assignment.member.display_name}</p>{actions(assignment.member)}{actions(assignment.dimension)}
        {assignment.provenance.kind==="REVIEWED_SOURCE_ATTRIBUTION"?<><p>Source-row evidence with reviewed operator attribution to the <strong>{assignment.provenance.side.toLowerCase()}</strong> side. This is not automatic attribution to both sides.</p><p>Attribution reason: {assignment.provenance.reason}</p><details><summary>Exact source assignment evidence</summary><p>{assignment.provenance.assignment.resource_id} · {assignment.provenance.assignment.version_id}</p></details></>:<p>User-asserted analytical assignment: {assignment.provenance.reason}</p>}
       </article>)}
      </>}
     </details>)}
    </section>
    <details><summary>Exact accounting evidence references</summary><p>Snapshot: {detail.snapshot_at}</p><p>Journal: {detail.journal.resource_id} · {detail.journal.version_id}</p><p>Accounting binding: {detail.binding.display_name}</p>{actions(detail.binding)}{balance&&<p>Balance currency: {balance.currency_id}</p>}</details>
   </>}
  </section>}
 </section>;
}
