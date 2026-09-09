import assert from "node:assert/strict";
import test from "node:test";
import {loadTypeScript} from "./load-typescript.mjs";
const {homeAnalysisRowTarget}=await loadTypeScript(new URL("../app/home-analysis-row.ts",import.meta.url));
const {sourceReviewUrl,sourceReviewTarget}=await loadTypeScript(new URL("../app/source-review-route.ts",import.meta.url));
const {parseView,assertProjection}=await loadTypeScript(new URL("../app/semantic-analysis-state.ts",import.meta.url));
const id="11111111-1111-4111-8111-111111111111",other="22222222-2222-4222-8222-222222222222",hash="a".repeat(64),rowKey="row_"+hash;
const sourceTime="2025-01-31T00:00:00.123456Z",journalTime="2026-09-08T12:00:00.654321Z",pin={resource_id:id,version_id:other,content_hash:hash};
function fixture(kind="journals"){
 const object=kind!=="counts";
 const fields=(object?[["code","identifier","ATTRIBUTE"],["account","reference","DIMENSION"],["debit","decimal","ATTRIBUTE"],["credit","decimal","ATTRIBUTE"],["net","decimal","ATTRIBUTE"]]:[["category","text","DIMENSION"],["count","integer","MEASURE"]]).map(([key,kind,role])=>({key,label:key,kind,role,aggregation:role==="MEASURE"?"RETAINED_VALUE_ONLY":"NONE",definition:pin,filterable:false,groupable:false,options:[]}));
 const values=Object.fromEntries(fields.map(field=>[field.key,{state:"VALUE",value:field.kind==="decimal"?"987654321.12345":field.kind==="integer"?7:field.kind==="reference"?id:field.kind==="identifier"?"0012.01":"Retained Georgian label",label:null,reference:field.kind==="reference"?pin:null}]));
 const reference={kind:"EXACT",invocationId:id,revision:{descriptorSha256:hash,receiptHash:hash,validAt:sourceTime,knownAt:sourceTime},...(kind==="journals"?{journalSnapshot:journalTime}:{})};
 const projection={descriptor:{contract:`semantic-analysis/${object?2:1}`,...object?{row_noun:"objects"}:{},invocation_id:id,company:pin,receipt_hash:hash,valid_at:sourceTime,known_at:sourceTime,recorded_at:sourceTime,current_use_authorized:false,business_effect_authorized:false,visual:object?"NONE":"HORIZONTAL_BARS",measure:object?null:"count",filtering:"RETAINED_GROUP_SELECTION",grouping:"RETAINED_ROWS_WITHOUT_AGGREGATION",fields,coverage:kind==="journals"?[{label:"Snapshot",value:journalTime}]:[]},descriptor_sha256:hash,request:{company_id:id,invocation_id:id,descriptor_sha256:hash},total_rows:1,rows:[{key:rowKey,label:"Retained account or group",trace:pin,contributor_count:2,values}],sections:[{label:"All",row_keys:[rowKey]}],selection:null};
 return {projection,reference};
}
for(const kind of ["journals","objects","counts"])test(`${kind} Home row opens exact selected evidence without copying amounts`,()=>{
 const {projection,reference}=fixture(kind),before=structuredClone(projection),target=homeAnalysisRowTarget(projection,reference,id,rowKey,1);
 assert.equal(target.view.request.selected_row,rowKey);assert.equal(target.view.request.contributor_index,1);
 assert.equal(target.view.request.descriptor_sha256,hash);assert.equal(target.view.receipt_hash,hash);
 assert.equal(target.view.valid_at,sourceTime);assert.equal(target.view.known_at,sourceTime);
 assert.equal(target.journalSnapshot,reference.journalSnapshot);assert.equal(target.view.pane,"evidence");assert.equal(target.view.workspace.collapsed,false);
 assert.deepEqual(target.view.workspace.grid.focus,{row:rowKey,column:projection.descriptor.fields[0].key});
 assert.deepEqual(target.view.columns,projection.descriptor.fields.map(field=>field.key));
 const url=sourceReviewUrl(target,new URL("https://g8.example/"));
 assert.equal(sourceReviewTarget(url.pathname).journalSnapshot,reference.journalSnapshot);
 assert.equal(parseView(url.searchParams.get("analysis_view"),id,id,reference.journalSnapshot).request.selected_row,rowKey);
 assert.equal(url.toString().includes("987654321"),false);assert.deepEqual(projection,before);
 const response={...projection,request:target.view.request,selection:{row_key:rowKey,contributor_index:1,contributor_count:2,contributor:{reference:pin,label:"Exact retained contributor",basis:"ORIGINAL_SOURCE",cells:[]}}};
 assert.doesNotThrow(()=>assertProjection(response,target.view.request,target.view));
});
test("unlisted row, foreign scope, changed revision and illegal contributor indices are refused",()=>{
 const {projection,reference}=fixture();
 assert.throws(()=>homeAnalysisRowTarget(projection,reference,id,"row_"+"b".repeat(64)));
 assert.throws(()=>homeAnalysisRowTarget(projection,reference,other,rowKey));
 assert.throws(()=>homeAnalysisRowTarget(projection,{...reference,invocationId:other},id,rowKey));
 for(const contributor of [-1,0.5,2,NaN,Infinity])assert.throws(()=>homeAnalysisRowTarget(projection,reference,id,rowKey,contributor));
 for(const patch of [{descriptorSha256:"b".repeat(64)},{receiptHash:"b".repeat(64)},{knownAt:"2025-01-31T00:00:00.123457Z"}])assert.throws(()=>homeAnalysisRowTarget(projection,{...reference,revision:{...reference.revision,...patch}},id,rowKey));
 assert.throws(()=>homeAnalysisRowTarget(projection,{...reference,journalSnapshot:"2026-09-08T12:00:00.654322Z"},id,rowKey));
});
test("zero-contributor rows have no invented evidence drill",()=>{
 const {projection,reference}=fixture();projection.rows[0].contributor_count=0;
 assert.equal(homeAnalysisRowTarget(projection,reference,id,rowKey),null);
});
test("legacy source pins still open the currently displayed exact revision",()=>{
 const {projection}=fixture("counts");delete projection.request.descriptor_sha256;
 const target=homeAnalysisRowTarget(projection,{kind:"LEGACY",invocationId:id},id,rowKey);
 assert.equal(target.view.request.descriptor_sha256,hash);assert.equal(target.view.receipt_hash,hash);assert.equal(target.journalSnapshot,undefined);
});
