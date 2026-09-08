import test from "node:test";
import assert from "node:assert/strict";
import {loadTypeScript} from "./load-typescript.mjs";
const {journalReviewReference,journalReviewEntryForSession,journalReviewOriginMatches,journalReviewHistoryMode,restoreJournalReviewFocus}=await loadTypeScript(new URL("../app/journal-review-handoff.ts",import.meta.url));
const id=n=>`00000000-0000-4000-8000-${String(n).padStart(12,"0")}`;
const company={resource_id:id(1),version_id:id(2),content_hash:"a".repeat(64),display_name:"Retained company",object_type:"LegalEntity",authority_state:"APPROVED",evidence_class:"SOURCE_BOUND",attributes:{amount:"must not persist"}};
const validAt="2025-01-01T00:00:00.123456Z",knownAt="2026-01-01T00:00:00.654321Z";
const item={company_id:id(1),request_id:id(3),proposal_id:id(4),invocation_id:id(5),state:"PENDING_REVIEW",basis:"EXPLICIT_JOURNAL_PRODUCTION_REQUEST",amount:"must not persist"};
const reference=()=>journalReviewReference(company,validAt,knownAt,item);
const entry=()=>({entryId:id(6),token:"session",returnView:"companies",reference:reference()});
const context=()=>({status:"ready",companyId:id(1),company,validAt,knownAt});

test("review origin contains exact canonical references, never journal or company payloads",()=>{
 const value=reference();assert.equal(value.company.version_id,id(2));assert.equal(value.proposalId,id(4));assert.equal(value.requestId,id(3));assert.equal(value.validAt,validAt);assert.equal(value.knownAt,knownAt);assert.equal(JSON.stringify(value).includes("must not persist"),false);
 for(const patch of [{company_id:id(9)},{proposal_id:"invalid"},{state:"PREPARED"},{state:"ERP_POSTED"},{basis:"INFERRED"}])assert.throws(()=>journalReviewReference(company,validAt,knownAt,{...item,...patch}));
 assert.throws(()=>journalReviewReference({...company,authority_state:"PROPOSED"},validAt,knownAt,item));
 assert.throws(()=>journalReviewReference(company,"2025-02-30T00:00:00Z",knownAt,item));
});
test("company, token, view, exact version, hash and microsecond cutoffs bind the return",()=>{
 const value=entry();assert.equal(journalReviewEntryForSession(value,"session",id(1),"companies"),value);
 for(const args of [["other",id(1),"companies"],["session",id(9),"companies"],["session",id(1),"home"]])assert.equal(journalReviewEntryForSession(value,...args),null);
 assert.equal(journalReviewOriginMatches(reference(),context()),true);
 for(const patch of [{status:"updating"},{companyId:id(9)},{company:{...company,version_id:id(9)}},{company:{...company,content_hash:"b".repeat(64)}},{knownAt:"2026-01-01T00:00:00.654322Z"}])assert.equal(journalReviewOriginMatches(reference(),{...context(),...patch}),false);
 assert.equal(journalReviewOriginMatches(reference(),{...context(),knownAt:"2026-01-01T04:00:00.654321+04:00"}),true);
});
test("Back/Forward only restores a live scoped entry; abandoned, malformed and reloaded markers refuse",()=>{
 const value=entry();assert.equal(journalReviewHistoryMode({g8JournalReview:id(6)},value),"review");assert.equal(journalReviewHistoryMode({g8JournalReturn:id(6)},value),"return");
 for(const state of [{g8JournalReview:id(7)},{g8JournalReturn:42},{g8JournalReview:null},{g8JournalReview:id(6),g8JournalReturn:id(6)}])assert.equal(journalReviewHistoryMode(state,value),"refused");
 assert.equal(journalReviewHistoryMode({g8JournalReview:id(6)},null),"refused");assert.equal(journalReviewHistoryMode({},value),null);
});
function dom(){
 const calls=[];const row={getClientRects:()=>[{}],focus:options=>calls.push(["row",options])};
 const queue={isConnected:true,querySelector:()=>row,focus:options=>calls.push(["queue",options])};
 const element={isConnected:true,hidden:false,inert:false,getClientRects:()=>[]};
 const pane={isConnected:true,scrollTo:options=>calls.push(["pane",options])};
 const main={scrollTo:options=>calls.push(["main",options])};
 return {calls,row,queue,element,main,origin:{element,queue,scroll:720,scrolls:[{element:pane,top:15,left:40}]}};
}
test("display:contents origin restores main/nested scroll and exact row after queue settlement",()=>{
 const d=dom();assert.equal(d.element.getClientRects().length,0);assert.equal(restoreJournalReviewFocus(d.origin,d.main,id(4)),true);
 assert.deepEqual(d.calls,[["main",{top:720,behavior:"instant"}],["pane",{top:15,left:40,behavior:"instant"}],["row",{preventScroll:true}]]);
});
test("filtered/removed row returns focus to queue; hidden, inert or detached origin never steals focus",()=>{
 const d=dom();d.row.getClientRects=()=>[];assert.equal(restoreJournalReviewFocus(d.origin,d.main,id(4)),true);assert.equal(d.calls.at(-1)[0],"queue");
 for(const patch of [{hidden:true},{inert:true},{isConnected:false}]){const candidate=dom();Object.assign(candidate.element,patch);assert.equal(restoreJournalReviewFocus(candidate.origin,candidate.main,id(4)),false);assert.deepEqual(candidate.calls,[]);}
 const detached=dom();detached.queue.isConnected=false;assert.equal(restoreJournalReviewFocus(detached.origin,detached.main,id(4)),false);
});
