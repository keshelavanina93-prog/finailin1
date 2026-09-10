import test from "node:test";
import assert from "node:assert/strict";
import {loadTypeScript} from "./load-typescript.mjs";
const {partitionCompanyWork}=await loadTypeScript(new URL("../app/company-work-attention.ts",import.meta.url));
const {rankJournalReviews,journalReviewProposal}=await loadTypeScript(new URL("../app/company-journal-review-state.ts",import.meta.url));
const items=["PUBLISHED","PREPARED","REJECTED","PENDING_REVIEW"].map((state,i)=>({state,company_id:"company",request_id:`request-${i}`,proposal_id:`proposal-${i}`,created_at:"2026-09-08T00:00:00Z",coordinate:`row-${i}`,title:state,reason:"Retained reason"}));

test("missing publication readback remains attention and never a successful outcome",()=>{
 const item={...items[0],state:"PUBLICATION_UNAVAILABLE"};
 assert.deepEqual(partitionCompanyWork([item]),{attention:[item],outcomes:[]});
});
test("attention contains only prepared and pending state; outcomes retain original exact objects and ordering",()=>{
 const groups=partitionCompanyWork(items);assert.deepEqual(groups.attention,[items[1],items[3]]);assert.deepEqual(groups.outcomes,[items[0],items[2]]);
 assert.equal(groups.attention[0],items[1]);assert.equal(groups.outcomes[1],items[2]);assert.equal(items[0].state,"PUBLISHED");
 assert.deepEqual(partitionCompanyWork([]),{attention:[],outcomes:[]});assert.throws(()=>partitionCompanyWork([{state:"ERP_POSTED"}]));
});
test("shared filters apply before grouping; rejected or accepted results never become primary attention",()=>{
 const groups=partitionCompanyWork(rankJournalReviews(items,"ALL",""));assert.deepEqual(groups.attention.map(row=>row.state),["PENDING_REVIEW","PREPARED"]);assert.deepEqual(groups.outcomes.map(row=>row.state),["REJECTED","PUBLISHED"]);
 for(const state of ["REJECTED","PUBLISHED"]){const filtered=partitionCompanyWork(rankJournalReviews(items,state,""));assert.equal(filtered.attention.length,0);assert.equal(filtered.outcomes.length,1);}
 const searched=partitionCompanyWork(rankJournalReviews(items,"ALL","row-3"));assert.deepEqual(searched.attention,[items[3]]);assert.deepEqual(searched.outcomes,[]);
 assert.equal(journalReviewProposal(groups.attention.find(row=>row.state==="PREPARED")),null);
});
test("a newly accepted exact review migrates to outcomes without being duplicated or relabeled pending",()=>{
 const previous=items[3],accepted={...previous,state:"PUBLISHED"};const groups=partitionCompanyWork(rankJournalReviews([accepted],"ALL",""));
 assert.deepEqual(groups.attention,[]);assert.deepEqual(groups.outcomes,[accepted]);assert.equal(groups.outcomes[0].proposal_id,previous.proposal_id);
 assert.deepEqual(partitionCompanyWork(rankJournalReviews([accepted],"PENDING_REVIEW","")),{attention:[],outcomes:[]});
});
