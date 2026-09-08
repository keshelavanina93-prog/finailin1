"use client";
import {useState} from "react";
import type {CompanyJournalReviews,CompanyJournalReviewItem} from "@finai/contracts";
import {assertCompanyJournalReviews,journalReviewKey,journalReviewLabels,journalReviewProposal,rankJournalReviews,type JournalReviewFilter} from "./company-journal-review-state";
import {displayName} from "./display-name";

type Props={companyId:string;value:unknown;compact?:boolean;onProposal?:(id:string)=>void;onReview?:(item:CompanyJournalReviewItem)=>void;pending?:boolean;error?:string};
export default function CompanyJournalReviewWork({companyId,value,compact,onProposal,onReview,pending,error}:Props){
 try{assertCompanyJournalReviews(value,companyId);}catch(failure){return <section aria-label="Journal review work" tabIndex={-1} data-journal-review-queue><header><h3>Journal review work</h3></header><p className="company-operating-limitation" role="status">{failure instanceof Error?failure.message:"Journal review work is unavailable."}</p></section>;}
 return <JournalReviews key={companyId} value={value} compact={compact} onProposal={onProposal} onReview={onReview} pending={pending} error={error}/>;
}
function JournalReviews({value,compact=false,onProposal,onReview,pending=false,error=""}:{value:CompanyJournalReviews;compact?:boolean;onProposal?:(id:string)=>void;onReview?:(item:CompanyJournalReviewItem)=>void;pending?:boolean;error?:string}){
 const [filter,setFilter]=useState<JournalReviewFilter>("ALL"),[query,setQuery]=useState(""),[page,setPage]=useState(0);
 const [opened,setOpened]=useState<string|null>(null);
 const size=compact?5:10,items=rankJournalReviews(value.items,filter,query),current=Math.min(page,Math.max(0,Math.ceil(items.length/size)-1));
 return <section className="company-journal-review-work" aria-label="Journal review work" tabIndex={-1} data-journal-review-queue><header><h3>Journal review work</h3><span>Observed {new Date(value.observed_at).toLocaleString()}</span></header>
  <p className="company-operating-note">Current canonical review decisions for requests explicitly linked to this company. These are separate from its historical operating snapshot. Acceptance does not establish ERP posting or a complete ledger.</p>
  {pending&&<p role="status">Refreshing current canonical review decisions at this company context...</p>}{error&&<p role="alert">{error} Previous review decisions are unavailable until refreshed.</p>}
  <div hidden={pending||Boolean(error)} inert={pending||Boolean(error)}>
  {opened&&!items.some(item=>item.proposal_id===opened)&&<p role="status">The opened review is no longer in these returned results or filters. Its current state has not been assumed. <button onClick={()=>{setFilter("ALL");setQuery("");setPage(0);}}>Show all returned reviews</button></p>}
  {value.state==="UNAVAILABLE"?<p className="company-operating-limitation" role="status">{value.reason} Other company work and operating context remain independently available.</p>:<>
   {value.items.length>0&&<div className="company-operating-toolbar"><label>Journal review state<select value={filter} onChange={event=>{setFilter(event.target.value as JournalReviewFilter);setPage(0);}}><option value="ALL">All returned reviews</option>{Object.entries(journalReviewLabels).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label><label>Find journal review<input maxLength={200} value={query} onChange={event=>{setQuery(event.target.value);setPage(0);}} placeholder="Title, source row or reason"/></label></div>}
   {items.length?<div className="company-operating-table"><table><thead><tr><th scope="col">Journal request / source row</th><th scope="col">Review state</th><th scope="col">Retained context</th><th scope="col">Next step</th></tr></thead><tbody>{items.slice(current*size,(current+1)*size).map(item=>{const proposalId=journalReviewProposal(item);return <tr key={journalReviewKey(item)}><th scope="row">{displayName(item.title)}<small>{item.coordinate} · Created {new Date(item.created_at).toLocaleString()}</small></th><td><span className="company-operating-status" data-state={item.state}>{journalReviewLabels[item.state]}</span></td><td>{item.reason}<details><summary>Advanced references</summary><p>Production request {item.request_id}</p><p>Proposal {item.proposal_id}</p><p>Source result {item.invocation_id}</p></details></td><td>{proposalId&&(onReview||onProposal)?<button data-journal-proposal={proposalId} onClick={()=>{setOpened(proposalId);if(onReview)onReview(item);else onProposal?.(proposalId);}}>Open review</button>:<span>{proposalId?"Review navigation unavailable":"Submission not recorded"}</span>}</td></tr>;})}</tbody></table></div>:<p className="company-operating-empty">{value.items.length?"No returned journal reviews match these filters.":"No journal review requests returned in this scope. This does not establish that the company has no pending accounting work."}</p>}
   {items.length>size&&<div className="company-operating-pager"><button disabled={current===0} onClick={()=>setPage(current-1)}>Previous reviews</button><span>{current*size+1}–{Math.min((current+1)*size,items.length)} of {items.length} matching returned</span><button disabled={(current+1)*size>=items.length} onClick={()=>setPage(current+1)}>Next reviews</button></div>}
   {value.truncated&&<p className="company-operating-limitation">This is a bounded review collection. Additional journal requests may exist beyond the returned {value.limit} item limit.</p>}
  </>}
  </div>
 </section>;
}
