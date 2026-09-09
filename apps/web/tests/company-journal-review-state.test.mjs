import test from "node:test";
import assert from "node:assert/strict";
import {loadTypeScript} from "./load-typescript.mjs";
const {assertCompanyJournalReviews,rankJournalReviews,journalReviewProposal}=await loadTypeScript(new URL("../app/company-journal-review-state.ts",import.meta.url));
const id=n=>`00000000-0000-4000-8000-${String(n).padStart(12,"0")}`;
const at="2026-09-08T00:00:00.123456Z";
const item=(state="PENDING_REVIEW",n=1)=>({request_id:id(n),proposal_id:id(n+10),company_id:id(100),invocation_id:id(200),coordinate:`Base!S${n}`,title:"Retained journal request",state,created_at:at,reason:"Retained canonical decision",basis:"EXPLICIT_JOURNAL_PRODUCTION_REQUEST"});
const collection=()=>({state:"AVAILABLE",reason:null,observed_at:at,authority:"CURRENT_CANONICAL_JOURNAL_REVIEW",items:[item()],truncated:false,limit:25});
test("valid current review references preserve real proposal navigation; preparation grants no submitted review",()=>{
 const data=collection();assert.doesNotThrow(()=>assertCompanyJournalReviews(data,id(100)));
 for(const state of ["PENDING_REVIEW","PUBLISHED","REJECTED"])assert.equal(journalReviewProposal(item(state)),id(11));
 assert.equal(journalReviewProposal(item("PREPARED")),null);assert.equal(Object.hasOwn(data.items[0],"workflow_id"),false);
});
test("missing or refused collection remains unavailable, never an empty successful queue",()=>{
 for(const value of [undefined,null,{}, {...collection(),state:"UNAVAILABLE",reason:null},{...collection(),state:"UNAVAILABLE",reason:"Storage unavailable"}])assert.throws(()=>assertCompanyJournalReviews(value,id(100)));
 assert.doesNotThrow(()=>assertCompanyJournalReviews({...collection(),state:"UNAVAILABLE",reason:"Storage unavailable",items:[]},id(100)));
 assert.doesNotThrow(()=>assertCompanyJournalReviews({...collection(),items:[]},id(100)));
});
test("foreign company, malformed references, duplicate items or unsupported authority refuse before display",()=>{
 for(const patch of [{company_id:id(101)},{request_id:"not-a-request"},{proposal_id:"not-a-proposal"},{invocation_id:"not-a-result"},{basis:"DERIVED_COMPANY_NAME"},{state:"ERP_POSTED"},{created_at:"2026-09-08"},{coordinate:""}])assert.throws(()=>assertCompanyJournalReviews({...collection(),items:[{...item(),...patch}]},id(100)));
 for(const patch of [{items:[item(),item()]},{limit:26},{observed_at:"2026-09-08T00:00:00"},{authority:"ACCOUNTING_POSTING"},{truncated:"false"}])assert.throws(()=>assertCompanyJournalReviews({...collection(),...patch},id(100)));
});
test("review priority and text filtering preserve source objects without financial ranking",()=>{
 const items=[item("PUBLISHED",1),item("REJECTED",2),item("PREPARED",3),item("PENDING_REVIEW",4)];
 assert.deepEqual(rankJournalReviews(items,"ALL","").map(row=>row.state),["PENDING_REVIEW","PREPARED","REJECTED","PUBLISHED"]);
 assert.equal(items[0].state,"PUBLISHED");
 assert.deepEqual(rankJournalReviews(items,"ALL","Base!S2"),[items[1]]);
 assert.deepEqual(rankJournalReviews(items,"PREPARED",""),[items[2]]);
});
test("the canonical coordinate limit remains readable without accepting oversized references",()=>{
 assert.doesNotThrow(()=>assertCompanyJournalReviews({...collection(),items:[{...item(),coordinate:"x".repeat(512)}]},id(100)));
 assert.throws(()=>assertCompanyJournalReviews({...collection(),items:[{...item(),coordinate:"x".repeat(513)}]},id(100)));
});
