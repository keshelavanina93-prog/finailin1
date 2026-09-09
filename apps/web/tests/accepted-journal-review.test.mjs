import test from "node:test";
import assert from "node:assert/strict";
import {loadTypeScript} from "./load-typescript.mjs";
const {acceptedJournalTarget}=await loadTypeScript(new URL("../app/accepted-journal-review.ts",import.meta.url));
const id="11111111-1111-4111-8111-111111111111",hash="a".repeat(64),time="2025-01-31T00:00:00.123456Z",snapshot="2026-09-08T08:00:00.654321Z";
function fixture(){const pin={resource_id:id,version_id:id,content_hash:hash},key="row_"+hash;return {descriptor:{contract:"semantic-analysis/2",row_noun:"objects",invocation_id:id,company:pin,receipt_hash:hash,valid_at:time,known_at:time,recorded_at:time,current_use_authorized:false,business_effect_authorized:false,visual:"NONE",filtering:"RETAINED_GROUP_SELECTION",grouping:"RETAINED_ROWS_WITHOUT_AGGREGATION",measure:null,fields:[{key:"debit",label:"Debit movement",kind:"decimal",role:"ATTRIBUTE",aggregation:"NONE",definition:pin,filterable:false,groupable:false,options:[]}],coverage:[{label:"Snapshot",value:snapshot}]},descriptor_sha256:hash,request:{company_id:id,invocation_id:id},total_rows:1,rows:[{key,label:"Accepted account",trace:pin,contributor_count:1,values:{debit:{state:"VALUE",value:"731.97",label:null,reference:null}}}],sections:[{label:"Accepted",row_keys:[key]}],selection:null};}
test("accepted journal entry carries the separate journal cutoff and exact source-result revision without amounts",()=>{
 const value=fixture(),target=acceptedJournalTarget(value,id,id,snapshot);
 assert.equal(target.journalSnapshot,snapshot);assert.equal(target.view.known_at,time);assert.equal(target.view.receipt_hash,hash);
 assert.equal(target.view.journalSnapshot,snapshot);
 assert.equal(target.view.request.descriptor_sha256,hash);assert.equal(JSON.stringify(target).includes("731.97"),false);
});
test("a different journal cutoff, company or invocation cannot open as the requested accepted result",()=>{
 const value=fixture(),other="22222222-2222-4222-8222-222222222222";
 assert.throws(()=>acceptedJournalTarget(value,other,id,snapshot));assert.throws(()=>acceptedJournalTarget(value,id,other,snapshot));
 assert.throws(()=>acceptedJournalTarget(value,id,id,"2026-09-08T08:00:00.654322Z"));
 for(const coverage of [[],[{label:"Snapshot",value:"2026-09-08"}],[...value.descriptor.coverage,...value.descriptor.coverage]])assert.throws(()=>acceptedJournalTarget({...value,descriptor:{...value.descriptor,coverage}},id,id,snapshot));
});
test("empty accepted result remains an empty retained projection, without manufacturing balances",()=>{
 const value=fixture();value.rows=[];value.total_rows=0;value.sections=[{label:"Accepted",row_keys:[]}];assert.doesNotThrow(()=>acceptedJournalTarget(value,id,id,snapshot));
 assert.throws(()=>acceptedJournalTarget({...value,descriptor:{...value.descriptor,business_effect_authorized:true}},id,id,snapshot));
});
