import assert from "node:assert/strict";
import test from "node:test";
import {loadTypeScript} from "./load-typescript.mjs";
const {displayedAnalysisView,sourceReviewUrl,sourceReviewTarget,sourceReviewRouteRefused}=await loadTypeScript(new URL("../app/source-review-route.ts",import.meta.url));
const {assertProjection,parseView}=await loadTypeScript(new URL("../app/semantic-analysis-state.ts",import.meta.url));
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

const snapshot="2026-09-08T05:06:07.123456Z";
function journal(){const p=fixture(2);p.descriptor.coverage=[{label:"Snapshot",value:snapshot}];return p;}
test("journal route and saved view have distinct exact identity from the original source",()=>{
 const projection=journal(),view=displayedAnalysisView(projection,id,snapshot),url=sourceReviewUrl({...target,journalSnapshot:snapshot,view},new URL("https://g8.example/"));
 assert.deepEqual(sourceReviewTarget(url.pathname),{...target,journalSnapshot:snapshot});
 assert.equal(parseView(url.searchParams.get("analysis_view"),id,id),null);
 assert.equal(parseView(url.searchParams.get("analysis_view"),id,id,snapshot).journalSnapshot,snapshot);
 assert.throws(()=>sourceReviewUrl({...target,view},url));
 assert.throws(()=>sourceReviewUrl({...target,journalSnapshot:snapshot,view:displayedAnalysisView(fixture(2),id)},url));
 assert.throws(()=>sourceReviewUrl({...target,journalSnapshot:"2026-09-08T05:06:07.123457Z",view},url));
 assert.equal(view.valid_at,time);assert.equal(view.known_at,time);
 assert.equal(parseView(JSON.stringify({...view,request:{...view.request,group_by:"units"}}),id,id,snapshot),null);
 assert.equal(parseView(JSON.stringify({...view,request:{...view.request,filters:[{field:"units",state:"VALUE",value:"1"}]}}),id,id,snapshot),null);
});
test("journal route accepts equivalent offsets without losing microseconds and refuses naive or invalid dates",()=>{
 const view=displayedAnalysisView(journal(),id,snapshot),url=sourceReviewUrl({...target,journalSnapshot:"2026-09-08T09:06:07.123456+04:00",view},new URL("https://g8.example/"));
 assert.equal(sourceReviewTarget(url.pathname).journalSnapshot,snapshot);
 for(const bad of ["2026-02-30T00:00:00Z","2026-09-08T05:06:07","", "2026-09-08T05:06:07.1234567Z"]){
  assert.throws(()=>sourceReviewUrl({...target,journalSnapshot:bad},url));
  assert.equal(sourceReviewTarget(`/source-review/${id}/${id}/accepted-journals/${encodeURIComponent(bad)}`),null);
 }
 assert.equal(sourceReviewTarget(`/source-review/${id}/${id}/accepted-journals/%`),null);
});
test("fixed journal transport validates response snapshot and does not confuse source cutoffs",async()=>{
 const {projectionEndpoint,assertProjectionTransport}=await loadTypeScript(new URL("../app/analysis-projection-identity.ts",import.meta.url));
 assert.equal(projectionEndpoint(),"/api/ontology/analysis/project");
 assert.equal(new URL(projectionEndpoint(snapshot),"https://g8.example").searchParams.get("snapshot_at"),snapshot);
 assert.doesNotThrow(()=>assertProjectionTransport(journal(),snapshot));
 for(const coverage of [[],[{label:"Snapshot",value:"2026-09-08T05:06:07.123457Z"}],[{label:"Snapshot",value:snapshot},{label:"Snapshot",value:snapshot}]]){
  const changed=journal();changed.descriptor.coverage=coverage;assert.throws(()=>assertProjectionTransport(changed,snapshot));
 }
 assert.throws(()=>displayedAnalysisView(fixture(1),id,snapshot));
});

test("malformed review-family URLs are refused before mounting saved business or NYX context",()=>{
 const prefix=`/source-review/${id}/${id}`;
 for(const path of ["/source-review", "/source-review/", "/source-review/not-a-company/not-a-result",`${prefix}/accepted-journals/not-a-time`,`${prefix}/accepted-journals/2026-09-08T12:00:00`,`${prefix}/accepted-journals/2026-02-30T00:00:00Z`,`${prefix}/accepted-journals/%`,`${prefix}/accepted-journals/`]){
  assert.equal(sourceReviewRouteRefused(path),true);assert.equal(sourceReviewTarget(path),null);
 }
 for(const path of ["/",prefix,`${prefix}/accepted-journals/${encodeURIComponent(snapshot)}`])assert.equal(sourceReviewRouteRefused(path),false);
});
