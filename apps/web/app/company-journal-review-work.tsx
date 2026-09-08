"use client";
import {useState} from "react";
import type {CompanyJournalReviews} from "@finai/contracts";
import {assertCompanyJournalReviews,journalReviewKey,journalReviewLabels,journalReviewProposal,rankJournalReviews,type JournalReviewFilter} from "./company-journal-review-state";
import {displayName} from "./display-name";

type Props={companyId:string;value:unknown;compact?:boolean;onProposal?:(id:string)=>void};
export default function CompanyJournalReviewWork({companyId,value,compact,onProposal}:Props){
 try{assertCompanyJournalReviews(value,companyId);}catch(failure){return <section aria-label="Journal review work"><header><h3>Journal review work</h3></header><p className="company-operating-limitation" role="status">{failure instanceof Error?failure.message:"Journal review work is unavailable."}</p></section>;}
 return <JournalReviews key={companyId} value={value} compact={compact} onProposal={onProposal}/>;
}
function JournalReviews({value,compact=false,onProposal}:{value:CompanyJournalReviews;compact?:boolean;onProposal?:(id:string)=>void}){
 const [filter,setFilter]=useState<JournalReviewFilter>("ALL"),[query,setQuery]=useState(""),[page,setPage]=useState(0);
 const size=compact?5:10,items=rankJournalReviews(value.items,filter,query),current=Math.min(page,Math.max(0,Math.ceil(items.length/size)-1));
 return <section className="company-journal-review-work" aria-label="Journal review work"><header><h3>Journal review work</h3><span>Observed {new Date(value.observed_at).toLocaleString()}</span></header>
  <p className="company-operating-note">Current canonical review decisions for requests explicitly linked to this company. These are separate from its historical operating snapshot. Acceptance does not establish ERP posting or a complete ledger.</p>
  {value.state==="UNAVAILABLE"?<p className="company-operating-limitation" role="status">{value.reason} Other company work and operating context remain independently available.</p>:<>
   {value.items.length>0&&<div className="company-operating-toolbar"><label>Journal review state<select value={filter} onChange={event=>{setFilter(event.target.value as JournalReviewFilter);setPage(0);}}><option value="ALL">All returned reviews</option>{Object.entries(journalReviewLabels).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label><label>Find journal review<input maxLength={200} value={query} onChange={event=>{setQuery(event.target.value);setPage(0);}} placeholder="Title, source row or reason"/></label></div>}
   {items.length?<div className="company-operating-table"><table><thead><tr><th scope="col">Journal request / source row</th><th scope="col">Review state</th><th scope="col">Retained context</th><th scope="col">Next step</th></tr></thead><tbody>{items.slice(current*size,(current+1)*size).map(item=>{const proposalId=journalReviewProposal(item);return <tr key={journalReviewKey(item)}><th scope="row">{displayName(item.title)}<small>{item.coordinate} · Created {new Date(item.created_at).toLocaleString()}</small></th><td><span className="company-operating-status" data-state={item.state}>{journalReviewLabels[item.state]}</span></td><td>{item.reason}<details><summary>Advanced references</summary><p>Production request {item.request_id}</p><p>Proposal {item.proposal_id}</p><p>Source result {item.invocation_id}</p></details></td><td>{proposalId&&onProposal?<button onClick={()=>onProposal(proposalId)}>Open review</button>:<span>{proposalId?"Review navigation unavailable":"Submission not recorded"}</span>}</td></tr>;})}</tbody></table></div>:<p className="company-operating-empty">{value.items.length?"No returned journal reviews match these filters.":"No journal review requests returned in this scope. This does not establish that the company has no pending accounting work."}</p>}
   {items.length>size&&<div className="company-operating-pager"><button disabled={current===0} onClick={()=>setPage(current-1)}>Previous reviews</button><span>{current*size+1}–{Math.min((current+1)*size,items.length)} of {items.length} matching returned</span><button disabled={(current+1)*size>=items.length} onClick={()=>setPage(current+1)}>Next reviews</button></div>}
   {value.truncated&&<p className="company-operating-limitation">This is a bounded review collection. Additional journal requests may exist beyond the returned {value.limit} item limit.</p>}
  </>}
 </section>;
}
