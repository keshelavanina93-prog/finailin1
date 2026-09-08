import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import ts from "typescript";
const moduleUrl=source=>`data:text/javascript;base64,${Buffer.from(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText).toString("base64")}`;
const stateUrl=moduleUrl(readFileSync(new URL("../app/semantic-analysis-state.ts",import.meta.url),"utf8"));
const {assertProjection,parseView}=await import(stateUrl);
const source=readFileSync(new URL("../app/source-review-route.ts",import.meta.url),"utf8").replace('import {assertProjection,parseView,type AnalysisView} from "./semantic-analysis-state";',`const {assertProjection,parseView}=await import(${JSON.stringify(stateUrl)});`);
const {displayedAnalysisView,sourceReviewUrl,sourceReviewTarget}=await import(moduleUrl(source));
const id="11111111-1111-4111-8111-111111111111",other="22222222-2222-4222-8222-222222222222",hash="a".repeat(64),time="2025-01-31T00:00:00Z",row="row_"+hash;
const pin={resource_id:id,version_id:id,content_hash:hash},target={companyId:id,invocationId:id};
function fixture(version){
 const field={key:"units",label:"Units",kind:"decimal",role:version===2?"ATTRIBUTE":"MEASURE",aggregation:version===2?"NONE":"RETAINED_VALUE_ONLY",definition:pin,filterable:false,groupable:false,options:[]};
 return {descriptor:{contract:`semantic-analysis/${version}`,...version===2?{row_noun:"objects"}:{},invocation_id:id,company:{resource_id:id},receipt_hash:hash,valid_at:time,known_at:time,recorded_at:time,current_use_authorized:false,business_effect_authorized:false,visual:version===2?"NONE":"HORIZONTAL_BARS",filtering:"RETAINED_GROUP_SELECTION",grouping:"RETAINED_ROWS_WITHOUT_AGGREGATION",measure:version===2?null:"units",fields:[field]},descriptor_sha256:hash,request:{company_id:id,invocation_id:id},total_rows:1,rows:[{key:row,label:"Retained group",trace:pin,contributor_count:1,values:{units:{state:"VALUE",value:"9007199254740993.125",label:null,reference:null}}}],sections:[{label:"all",row_keys:[row]}],selection:null};
}
for(const version of [1,2])test(`displayed semantic-analysis/${version} passes its exact revision through the existing route loader contract`,()=>{
 const projection=fixture(version),view=displayedAnalysisView(projection,id);
 const url=sourceReviewUrl({...target,view},new URL("https://g8.example/?analysis_view=old&context=kept"));
 assert.deepEqual(sourceReviewTarget(url.pathname),target);
 assert.equal(url.searchParams.get("context"),"kept");
 const restored=parseView(url.searchParams.get("analysis_view"),id,id);
 assert.equal(restored.request.descriptor_sha256,hash);
 assert.equal(restored.receipt_hash,hash);assert.equal(restored.valid_at,time);assert.equal(restored.known_at,time);
 assert.doesNotThrow(()=>assertProjection({...projection,request:restored.request},restored.request,restored));
 assert.equal(url.toString().includes("9007199254740993"),false);
});
test("a successor descriptor, changed receipt or changed snapshot cannot replace the displayed result",()=>{
 const projection=fixture(1),view=displayedAnalysisView(projection,id),response={...projection,request:view.request};
 for(const successor of [{...response,descriptor_sha256:"b".repeat(64)},{...response,descriptor:{...response.descriptor,receipt_hash:"b".repeat(64)}},{...response,descriptor:{...response.descriptor,known_at:"2025-02-01T00:00:00Z"}}])assert.throws(()=>assertProjection(successor,view.request,view));
});
test("malformed or foreign exact views are rejected rather than downgraded to an unpinned route",()=>{
 const view=displayedAnalysisView(fixture(1),id),current=new URL("https://g8.example/");
 for(const invalid of [null,{}, {...view,request:{...view.request,company_id:other}},{...view,request:{...view.request,invocation_id:other}},{...view,request:{...view.request,descriptor_sha256:null}}])assert.throws(()=>sourceReviewUrl({...target,view:invalid},current));
 assert.throws(()=>displayedAnalysisView(fixture(1),other));
});
test("existing direct result entries remain supported and cannot inherit another analysis view",()=>{
 const url=sourceReviewUrl(target,new URL("https://g8.example/?analysis_view=stale"));
 assert.equal(url.searchParams.has("analysis_view"),false);
 assert.deepEqual(sourceReviewTarget(url.pathname),target);
});
