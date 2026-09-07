import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";
import ts from "typescript";
const source=await readFile(new URL("../app/semantic-analysis-state.ts",import.meta.url),"utf8");
const {assertProjection,parseView,requestKey}=await import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText).toString("base64")}`);
const id="11111111-1111-4111-8111-111111111111",hash="a".repeat(64),row="row_"+hash,time="2025-01-31T00:00:00Z";
const request={company_id:id,invocation_id:id,descriptor_sha256:hash,filters:[],group_by:null,selected_row:null,contributor_index:0};
const projection={descriptor:{contract:"semantic-analysis/1",invocation_id:id,company:{resource_id:id},receipt_hash:hash,valid_at:time,known_at:time,recorded_at:time,current_use_authorized:false,business_effect_authorized:false,visual:"HORIZONTAL_BARS",filtering:"RETAINED_GROUP_SELECTION",grouping:"RETAINED_ROWS_WITHOUT_AGGREGATION",measure:"units",fields:[{key:"units"}]},descriptor_sha256:hash,request,rows:[{key:row,values:{units:{state:"VALUE",value:"9007199254740993.125"}}}],sections:[{label:"all",row_keys:[row]}],selection:null};
test("projection rejects mixed company, revision, echoed query and stale contributor",()=>{
 assert.doesNotThrow(()=>assertProjection(projection,request));
 for(const change of [{descriptor_sha256:"b".repeat(64)},{request:{...request,group_by:"other"}},{selection:{row_key:row,contributor_index:0}}])assert.throws(()=>assertProjection({...projection,...change},request));
 assert.throws(()=>assertProjection({...projection,descriptor:{...projection.descriptor,company:{resource_id:"other"}}},request));
 assert.throws(()=>assertProjection({...projection,sections:[{row_keys:["row_"+"b".repeat(64)]}]},request));
});
test("saved preference strips payloads and reauthorizes exact result times",()=>{
 const view={version:1,request:{...request,token:"secret",rows:projection.rows},valid_at:time,known_at:time,receipt_hash:hash,columns:["units"],visual:true,pane:"evidence",scroll:85,token:"secret",rows:projection.rows};
 const parsed=parseView(JSON.stringify(view),id);assert.ok(parsed);assert.equal(JSON.stringify(parsed).includes("secret"),false);assert.equal(JSON.stringify(parsed).includes("9007199254740993"),false);
 assert.doesNotThrow(()=>assertProjection(projection,request,parsed));
 assert.throws(()=>assertProjection(projection,request,{...parsed,known_at:"2025-02-01T00:00:00Z"}));
 assert.equal(parseView(JSON.stringify(view),"other"),null);
 assert.equal(parseView(JSON.stringify({...view,request:{...request,descriptor_sha256:null}}),id),null);
 assert.equal(parseView("malformed",id),null);
});
test("default wire fields normalize without equating different retained filters",()=>{
 assert.equal(requestKey({company_id:id,invocation_id:id}),requestKey({...request,descriptor_sha256:null}));
 assert.notEqual(requestKey({...request,filters:[{field:"x",state:"NULL",value:null}]}),requestKey({...request,filters:[{field:"x",state:"MISSING",value:null}]}));
});
