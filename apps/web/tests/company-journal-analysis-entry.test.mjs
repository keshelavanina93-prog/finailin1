import test from "node:test";
import assert from "node:assert/strict";
import {loadTypeScript} from "./load-typescript.mjs";
const {companyJournalAnalysisEntries,journalAnalysisEntryTarget}=await loadTypeScript(new URL("../app/company-journal-analysis-entry-state.ts",import.meta.url));
const id=n=>`00000000-0000-4000-8000-${String(n).padStart(12,"0")}`;
const at="2026-09-08T00:00:00.123456Z",company=id(100);
const item=(n=1,state="PUBLISHED",invocation=id(200))=>({request_id:id(n),proposal_id:id(n+30),company_id:company,invocation_id:invocation,coordinate:`Base!S${n}`,title:"ქართული accepted journal",state,created_at:at,reason:"Retained canonical decision",basis:"EXPLICIT_JOURNAL_PRODUCTION_REQUEST"});
const collection=(items=[item()])=>({state:"AVAILABLE",reason:null,observed_at:at,authority:"CURRENT_CANONICAL_JOURNAL_REVIEW",items,truncated:false,limit:25});

test("published source is discoverable without Home pins or financial values",()=>{
 const entries=companyJournalAnalysisEntries(collection(),company);
 assert.deepEqual(entries.sources,[{invocationId:id(200),title:"ქართული accepted journal",acceptedReviews:1}]);
 assert.deepEqual(journalAnalysisEntryTarget(entries,id(200),at),{companyId:company,invocationId:id(200)});
 assert.equal(Object.hasOwn(entries,"amount"),false);assert.equal(Object.hasOwn(entries,"journalSnapshot"),false);
});

test("multiple accepted coordinates collapse to one source action without counting them as journal totals",()=>{
 const data=collection([item(1),{...item(2),request_id:id(1)},item(3,"PUBLISHED",id(201))]);
 const before=structuredClone(data),entries=companyJournalAnalysisEntries(data,company);
 assert.equal(entries.sources.length,2);assert.equal(entries.sources[0].acceptedReviews,2);
 assert.deepEqual(data,before);
});

test("prepared, rejected and pending reviews do not establish an accepted-source entry",()=>{
 const entries=companyJournalAnalysisEntries(collection([item(1,"PREPARED"),item(2,"PENDING_REVIEW"),item(3,"REJECTED")]),company);
 assert.deepEqual(entries.sources,[]);assert.throws(()=>journalAnalysisEntryTarget(entries,id(200),at));
});

test("unavailable and bounded empty collections stay distinct",()=>{
 const empty=companyJournalAnalysisEntries(collection([]),company);
 const unavailable=companyJournalAnalysisEntries({...collection([]),state:"UNAVAILABLE",reason:"Receipt unavailable"},company);
 assert.equal(empty.state,"AVAILABLE");assert.equal(unavailable.state,"UNAVAILABLE");assert.equal(unavailable.reason,"Receipt unavailable");
 assert.throws(()=>journalAnalysisEntryTarget(unavailable,id(200),at));
 const bounded=companyJournalAnalysisEntries({...collection(),truncated:true},company);assert.equal(bounded.truncated,true);
});

test("foreign company, malformed reference, collection authority and duplicate proposal refuse",()=>{
 const data=collection();
 for(const value of [null,{}, {...data,authority:"POSTING_ALLOWED"},{...data,items:[{...item(),company_id:id(101)}]}, {...data,items:[{...item(),invocation_id:"source-name"}]},{...data,items:[item(),{...item(2),proposal_id:item().proposal_id}]}])assert.throws(()=>companyJournalAnalysisEntries(value,company));
 assert.throws(()=>companyJournalAnalysisEntries(collection([]),"company-name"));
});

test("one production request cannot claim multiple retained source invocations",()=>{
 assert.throws(()=>companyJournalAnalysisEntries(collection([item(1),{...item(2,"PUBLISHED",id(201)),request_id:id(1)}]),company));
});

test("observed-time change or withdrawn source invalidates a previously selected entry",()=>{
 const entries=companyJournalAnalysisEntries({...collection(),observed_at:"2026-09-08T00:00:00.123457Z"},company);
 assert.throws(()=>journalAnalysisEntryTarget(entries,id(200),at));
 const withdrawn=companyJournalAnalysisEntries(collection([item(1,"REJECTED")]),company);
 assert.throws(()=>journalAnalysisEntryTarget(withdrawn,id(200),at));
 assert.throws(()=>journalAnalysisEntryTarget(entries,id(999),entries.observedAt));
});

test("discovery remains within the descriptor's25-item bound",()=>{
 assert.equal(companyJournalAnalysisEntries(collection(Array.from({length:25},(_,n)=>item(n+1,"PUBLISHED",id(200+n)))),company).sources.length,25);
 assert.throws(()=>companyJournalAnalysisEntries(collection(Array.from({length:26},(_,n)=>item(n+1))),company));
});
