import assert from "node:assert/strict";
import test from "node:test";
import {loadTypeScript} from "./load-typescript.mjs";
const {sourceReviewContext,activeSourceReviewContext,sourceReviewForSession,explainSourceReview}=await loadTypeScript(new URL("../app/source-review-context.ts",import.meta.url));
const id="11111111-1111-4111-8111-111111111111",other="22222222-2222-4222-8222-222222222222",hash="a".repeat(64),time="2025-01-31T00:00:00Z",row="row_"+hash;
const pin={resource_id:id,version_id:other,content_hash:hash},scope={companyId:id,invocationId:id},request={company_id:id,invocation_id:id,descriptor_sha256:hash,selected_row:row,contributor_index:0};
const contributor={reference:pin,label:"Source evidence",basis:"ORIGINAL_SOURCE",cells:[{label:"Amount",value:"9007199254740993.125",coordinate:"A1",formula:null}]};
const field={key:"units",label:"Units",kind:"decimal",role:"MEASURE",aggregation:"RETAINED_VALUE_ONLY",definition:pin,filterable:false,groupable:false,options:[]};
const fixture=()=>({descriptor:{contract:"semantic-analysis/1",title:"Source review",authority:"SOURCE_OBSERVATION_ONLY",function:pin,invocation_id:id,company:{resource_id:id},receipt_hash:hash,valid_at:time,known_at:time,recorded_at:time,current_use_authorized:false,business_effect_authorized:false,visual:"HORIZONTAL_BARS",filtering:"RETAINED_GROUP_SELECTION",grouping:"RETAINED_ROWS_WITHOUT_AGGREGATION",measure:"units",fields:[field],excluded_evidence:[contributor]},descriptor_sha256:hash,request,rows:[{key:row,label:"Selected source row",trace:pin,contributor_count:1,values:{units:{state:"VALUE",value:"9007199254740993.125",label:null,reference:null}}}],total_rows:1,sections:[{label:"all",row_keys:[row]}],selection:{row_key:row,contributor_index:0,contributor_count:1,contributor}});
const ready={ready:true,busy:false,error:false,excludedIndex:null};
test("selected analysis context retains exact row/contributor/receipt/time references without cells or amounts",()=>{
 const value=sourceReviewContext(fixture(),request,ready);
 assert.equal(value.status,"ready");assert.equal(value.rowKey,row);assert.equal(value.contributorIndex,0);assert.equal(value.receiptHash,hash);assert.equal(value.knownAt,time);assert.deepEqual(value.reference,pin);
 assert.equal(JSON.stringify(value).includes("9007199254740993"),false);assert.equal("rows" in value,false);assert.equal("cells" in value,false);
 assert.match(explainSourceReview(value),/not complete company coverage/);assert.match(explainSourceReview(value),/do not establish a financial cause/);
});
test("busy, refused, stale revision and unmatched selection cannot expose a previous ready context",()=>{
 for(const state of [{...ready,ready:false},{...ready,busy:true},{...ready,error:true}]){const value=sourceReviewContext(fixture(),request,state);assert.notEqual(value.status,"ready");assert.deepEqual(Object.keys(value).sort(),["companyId","invocationId","status"]);}
 for(const next of [{...request,descriptor_sha256:"b".repeat(64)},{...request,company_id:other},{...request,contributor_index:1}])assert.equal(sourceReviewContext(fixture(),next,ready).status,"unavailable");
 assert.equal(sourceReviewContext(null,request,ready).status,"unavailable");
 const missingReceipt=fixture();missingReceipt.descriptor.receipt_hash="missing";assert.equal(sourceReviewContext(missingReceipt,request,ready).status,"unavailable");
});
test("excluded evidence cannot support the selected included row",()=>{
 const value=sourceReviewContext(fixture(),request,{...ready,excludedIndex:0});
 assert.equal(value.status,"ready");assert.equal(value.rowKey,null);assert.equal(value.rowLabel,null);assert.equal(value.contributorIndex,null);assert.equal(value.excludedIndex,0);assert.match(explainSourceReview(value),/outside the included result/);
 assert.equal(sourceReviewContext(fixture(),request,{...ready,excludedIndex:3}).status,"unavailable");
});
test("route exit, company/invocation switches and credential changes hide prior source context",()=>{
 const value=sourceReviewContext(fixture(),request,ready);
 assert.equal(activeSourceReviewContext(value,null),null);
 for(const target of [{...scope,companyId:other},{...scope,invocationId:other}])assert.equal(activeSourceReviewContext(value,target).status,"updating");
 assert.equal(sourceReviewForSession({sessionKey:"previous",context:value},"current",scope).status,"updating");
 assert.equal(sourceReviewForSession({sessionKey:"current",context:value},"current",scope),value);
});
test("historical replies retain old immutable references and v2 retains canonical-definition limitations",()=>{
 const first=sourceReviewContext(fixture(),request,ready),snapshot=structuredClone(first),projection=fixture();
 projection.descriptor.contract="semantic-analysis/2";projection.descriptor.row_noun="objects";projection.descriptor.visual="NONE";projection.descriptor.measure=null;projection.descriptor.fields=[{...field,role:"ATTRIBUTE",aggregation:"NONE"}];projection.selection={...projection.selection,contributor:{...contributor,basis:"CANONICAL_DEFINITION"}};
 const next=sourceReviewContext(projection,request,ready);assert.equal(next.status,"ready");assert.match(explainSourceReview(next),/original source cells are not established/);assert.deepEqual(first,snapshot);
});

test("NYX scopes journal readback to exact projection identity and refuses mismatched transport evidence",()=>{
 const journalSnapshot="2026-09-08T00:00:00.123456Z",p=fixture();p.descriptor.contract="semantic-analysis/2";p.descriptor.row_noun="objects";p.descriptor.visual="NONE";p.descriptor.measure=null;p.descriptor.fields=[{...field,role:"ATTRIBUTE",aggregation:"NONE"}];p.descriptor.coverage=[{label:"Snapshot",value:journalSnapshot}];
 const value=sourceReviewContext(p,request,{...ready,journalSnapshot});
 assert.equal(value.status,"ready");assert.equal(value.journalSnapshot,journalSnapshot);
 assert.equal(activeSourceReviewContext(value,scope).status,"updating");
 assert.equal(activeSourceReviewContext(sourceReviewContext(fixture(),request,ready),{...scope,journalSnapshot}).status,"updating");
 assert.equal(activeSourceReviewContext(value,{...scope,journalSnapshot:"2026-09-08T00:00:00.123457Z"}).status,"updating");
 assert.match(explainSourceReview(value),/Accepted journals snapshot/);
 assert.equal(sourceReviewContext(p,request,{...ready,journalSnapshot:"2026-09-08T00:00:00.123457Z"}).status,"unavailable");
 assert.equal(sourceReviewContext(p,request,{...ready,busy:true,journalSnapshot}).status,"updating");
});
