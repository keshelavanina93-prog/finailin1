import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";
import ts from "typescript";
const source=await readFile(new URL("../app/semantic-analysis-state.ts",import.meta.url),"utf8");
const {assertProjection,evidenceCaption,parseView,requestKey}=await import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText).toString("base64")}`);
const id="11111111-1111-4111-8111-111111111111",hash="a".repeat(64),row="row_"+hash,time="2025-01-31T00:00:00Z";
const pin={resource_id:id,version_id:id,content_hash:hash};
const field={key:"units",label:"Units",kind:"decimal",role:"MEASURE",aggregation:"RETAINED_VALUE_ONLY",definition:pin,filterable:false,groupable:false,options:[]};
const request={company_id:id,invocation_id:id,descriptor_sha256:hash,filters:[],group_by:null,selected_row:null,contributor_index:0};
const projection={descriptor:{contract:"semantic-analysis/1",invocation_id:id,company:{resource_id:id},receipt_hash:hash,valid_at:time,known_at:time,recorded_at:time,current_use_authorized:false,business_effect_authorized:false,visual:"HORIZONTAL_BARS",filtering:"RETAINED_GROUP_SELECTION",grouping:"RETAINED_ROWS_WITHOUT_AGGREGATION",measure:"units",fields:[field]},descriptor_sha256:hash,request,total_rows:1,rows:[{key:row,label:"Retained group",trace:pin,contributor_count:1,values:{units:{state:"VALUE",value:"9007199254740993.125",label:null,reference:null}}}],sections:[{label:"all",row_keys:[row]}],selection:null};
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
test("disclosed QA regression: a text dimension cannot become the bar measure",()=>{
 const dimension={...field,key:"source_header",label:"Source header",kind:"text",role:"DIMENSION"};
 assert.throws(()=>assertProjection({...projection,descriptor:{...projection.descriptor,measure:"source_header",fields:[dimension,field]}},request));
 assert.throws(()=>assertProjection({...projection,descriptor:{...projection.descriptor,fields:[{...field,kind:"string"}]},rows:[{...projection.rows[0],values:{units:{state:"VALUE",value:"not numeric",label:null,reference:null}}}]},request));
});
test("numeric values must retain their declared type and bounded finite scale",()=>{
 for(const value of [true,1,"not numeric","Infinity","1e400","9".repeat(101),"0."+"0".repeat(101)+"1"]){
  assert.throws(()=>assertProjection({...projection,rows:[{...projection.rows[0],values:{units:{state:"VALUE",value,label:null,reference:null}}}]},request));
 }
 const integer={...projection,descriptor:{...projection.descriptor,fields:[{...field,kind:"integer"}]}};
 for(const value of ["1",true,1.5,Number.MAX_SAFE_INTEGER+1])assert.throws(()=>assertProjection({...integer,rows:[{...projection.rows[0],values:{units:{state:"VALUE",value,label:null,reference:null}}}]},request));
 assert.doesNotThrow(()=>assertProjection({...integer,rows:[{...projection.rows[0],values:{units:{state:"VALUE",value:3,label:null,reference:null}}}]},request));
});
test("sections cannot repeat or omit retained rows and evidence counts stay bounded",()=>{
 for(const sections of [[],[{label:"repeat",row_keys:[row,row]}]])assert.throws(()=>assertProjection({...projection,sections},request));
 for(const contributor_count of [-1,1.5,1001])assert.throws(()=>assertProjection({...projection,rows:[{...projection.rows[0],contributor_count}]},request));
});
const objectTable={...projection,descriptor:{...projection.descriptor,contract:"semantic-analysis/2",row_noun:"objects",measure:null,visual:"NONE",fields:[{...field,role:"ATTRIBUTE",aggregation:"NONE"}]}};
test("v2 explicitly permits table-only attributes without promoting stored numbers",()=>{
 const original=JSON.stringify(objectTable);
 assert.doesNotThrow(()=>assertProjection(objectTable,request));
 assert.equal(JSON.stringify(objectTable),original);
 assert.equal(objectTable.rows[0].values.units.value,"9007199254740993.125");
 const exponential={...objectTable,rows:[{...objectTable.rows[0],values:{units:{state:"VALUE",value:"1E+900",label:null,reference:null}}}]};
 assert.doesNotThrow(()=>assertProjection(exponential,request));
 assert.equal(exponential.rows[0].values.units.value,"1E+900");
 for(const patch of [{visual:"HORIZONTAL_BARS"},{measure:"units"},{row_noun:"groups"},{fields:[field]},{fields:[{...field,role:"ATTRIBUTE"}]}])assert.throws(()=>assertProjection({...objectTable,descriptor:{...objectTable.descriptor,...patch}},request));
 assert.throws(()=>assertProjection({...objectTable,descriptor:{...objectTable.descriptor,contract:"semantic-analysis/1"}},request));
});
test("evidence basis remains explicit and unsupported bases are refused",()=>{
 const selectedRequest={...request,selected_row:row};
 const contributor={label:"Retained definition",reference:pin,cells:[{label:"Stored attribute",value:"9007199254740993.125",coordinate:null,formula:null}]};
 for(const basis of [undefined,"ORIGINAL_SOURCE","CANONICAL_DEFINITION","UNAVAILABLE"]){
  const selected={...objectTable,request:selectedRequest,selection:{row_key:row,contributor_index:0,contributor_count:1,contributor:{...contributor,basis}}};
  assert.doesNotThrow(()=>assertProjection(selected,selectedRequest));
 }
 assert.equal(evidenceCaption(undefined),"Original retained evidence");
 assert.equal(evidenceCaption("CANONICAL_DEFINITION"),"Retained canonical definition");
 assert.equal(evidenceCaption("UNAVAILABLE"),"Original source unavailable");
 assert.throws(()=>assertProjection({...objectTable,request:selectedRequest,selection:{row_key:row,contributor_index:0,contributor_count:1,contributor:{...contributor,basis:"INFERRED"}}},selectedRequest));
});
