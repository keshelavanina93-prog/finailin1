"use client";
import {useId,useState} from "react";
import AcceptedJournalReviewAction from "./accepted-journal-review-action";
import {companyJournalAnalysisEntries,journalAnalysisEntryTarget,type JournalAnalysisEntries} from "./company-journal-analysis-entry-state";
import {displayName} from "./display-name";
import "./company-journal-analysis-entry.css";

type Props={token:string;companyId:string;value:unknown;pending?:boolean};
export default function CompanyJournalAnalysisEntry({token,companyId,value,pending=false}:Props){
 if(pending)return <section aria-label="Accepted journal sources"><p role="status">Refreshing accepted journal source references…</p></section>;
 let entries:JournalAnalysisEntries;
 try{entries=companyJournalAnalysisEntries(value,companyId);}catch(failure){return <section aria-label="Accepted journal sources"><p role="status">{failure instanceof Error?failure.message:"Accepted journal source discovery is unavailable."}</p></section>;}
 return <JournalSources key={JSON.stringify([token,companyId,entries])} token={token} entries={entries}/>;
}
function JournalSources({token,entries}:{token:string;entries:JournalAnalysisEntries}){
 const id=useId(),[selected,setSelected]=useState("");
 const source=entries.sources.length===1?entries.sources[0]:entries.sources.find(item=>item.invocationId===selected);
 const target=source?journalAnalysisEntryTarget(entries,source.invocationId,entries.observedAt):null;
 return <section className="home-journal-discovery" aria-label="Accepted journal sources">
  <header><h3>Accepted journal sources</h3><small>Reviews observed {new Date(entries.observedAt).toLocaleString()}</small></header>
  <p>Open accepted journal movements from a reviewed source. Review movements and trace their retained source evidence.</p>
  {entries.state==="UNAVAILABLE"?<p role="status">{entries.reason}</p>:entries.sources.length===0?<p>No published journal sources were returned in this review collection. Other accepted journals may exist outside it.</p>:<>
   {entries.sources.length>1&&<label htmlFor={id}>Accepted review request / linked source<select id={id} value={selected} onChange={event=>setSelected(event.target.value)}><option value="">Choose a returned source</option>{entries.sources.map(item=><option key={item.invocationId} value={item.invocationId}>Review: {displayName(item.title)||"Title not retained"} · {item.acceptedReviews} accepted {item.acceptedReviews===1?"review":"reviews"}</option>)}</select></label>}
   {source&&<p>Retained review title: {displayName(source.title)||"Title not retained"} · {source.acceptedReviews} accepted {source.acceptedReviews===1?"review":"reviews"} in this collection.</p>}
   {target&&<AcceptedJournalReviewAction key={target.invocationId} token={token} companyId={target.companyId} invocationId={target.invocationId}/>}
  </>}
  <small>This opens a new fixed journal snapshot, independent of the company’s displayed historical snapshot and the source result’s own time. Partial source coverage does not establish a complete ledger or financial statement.</small>
  {entries.truncated&&<p role="status">Discovery is limited to the returned review collection; additional sources may exist.</p>}
 </section>;
}
