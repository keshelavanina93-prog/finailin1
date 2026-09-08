import assert from "node:assert/strict";
import test from "node:test";
import {loadTypeScript} from "./load-typescript.mjs";
const {assertProjection,evidenceCaption,formatAnalysisDecimal,hasUsefulMagnitude,parseView,requestKey,worksheetTabStop,worksheetRowMatches}=await loadTypeScript(new URL("../app/semantic-analysis-state.ts",import.meta.url));
const id="11111111-1111-4111-8111-111111111111",hash="a".repeat(64),row="row_"+hash,time="2025-01-31T00:00:00Z";
const pin={resource_id:id,version_id:id,content_hash:hash};
const field={key:"units",label:"Units",kind:"decimal",role:"MEASURE",aggregation:"RETAINED_VALUE_ONLY",definition:pin,filterable:false,groupable:false,options:[]};
const request={company_id:id,invocation_id:id,descriptor_sha256:hash,filters:[],group_by:null,selected_row:null,contributor_index:0};
const projection={descriptor:{contract:"semantic-analysis/1",invocation_id:id,company:{resource_id:id},receipt_hash:hash,valid_at:time,known_at:time,recorded_at:time,current_use_authorized:false,business_effect_authorized:false,visual:"HORIZONTAL_BARS",filtering:"RETAINED_GROUP_SELECTION",grouping:"RETAINED_ROWS_WITHOUT_AGGREGATION",measure:"units",fields:[field]},descriptor_sha256:hash,request,total_rows:1,rows:[{key:row,label:"Retained group",trace:pin,contributor_count:1,values:{units:{state:"VALUE",value:"9007199254740993.125",label:null,reference:null}}}],sections:[{label:"all",row_keys:[row]}],selection:null};

test("optional evidence cell references preserve old cells and validate exact pins in both contracts",()=>{
 for(const contract of ["semantic-analysis/1","semantic-analysis/2"]){
  const p=structuredClone(projection);p.request.selected_row=row;
  if(contract==="semantic-analysis/2"){Object.assign(p.descriptor,{contract,measure:null,visual:"NONE",row_noun:"objects"});Object.assign(p.descriptor.fields[0],{role:"ATTRIBUTE",aggregation:"NONE"});}
  const cell={label:"Retained definition",value:"Exact reference",coordinate:null,formula:null};
  const contributor={basis:"CANONICAL_DEFINITION",label:"Accepted journal",reference:pin,cells:[cell]};
  p.selection={row_key:row,contributor_index:0,contributor_count:1,contributor};
  const original=JSON.stringify(p);
  assert.doesNotThrow(()=>assertProjection(p,p.request));assert.equal(JSON.stringify(p),original);
  for(const reference of [null,pin]){cell.reference=reference;assert.doesNotThrow(()=>assertProjection(p,p.request));}
  for(const reference of [{},[],false,"reference",{...pin,content_hash:"invalid"},{...pin,resource_id:"invalid"},{...pin,version_id:null}]){
   cell.reference=reference;assert.throws(()=>assertProjection(p,p.request));
   const excluded={...p,request,selection:null,descriptor:{...p.descriptor,excluded_evidence:[contributor]}};
   assert.throws(()=>assertProjection(excluded,request));
  }
 }
});
test("Find searches only returned row labels and visible recorded field values without numeric conversion",()=>{
 const original=JSON.stringify(projection),retained=projection.rows[0];
 for(const query of [" retained GROUP ","9007199254740993.125","Units:",""])assert.equal(worksheetRowMatches(retained,[field],query),true);
 for(const query of ["9007199254740992",hash,"not present"])assert.equal(worksheetRowMatches(retained,[field],query),false);
 assert.equal(worksheetRowMatches(retained,[],"9007199254740993.125"),false);
 assert.equal(worksheetRowMatches(retained,[],"retained group"),true);
 assert.equal(JSON.stringify(projection),original);
});
test("Find preserves recorded null, missing, boolean, label and exponential text semantics",()=>{
 for(const [value,query] of [[{state:"NULL",value:null,label:null},"Recorded null"],[{state:"MISSING",value:null,label:null},"Not recorded"],[{state:"VALUE",value:false,label:null},"false"],[{state:"VALUE",value:"1E+900",label:"Recorded magnitude"},"1E+900"],[{state:"VALUE",value:"code",label:"Localized name"},"localized name"]])assert.equal(worksheetRowMatches({...projection.rows[0],values:{units:value}},[field],query),true);
 assert.equal(worksheetRowMatches({...projection.rows[0],values:{units:{state:"NULL",value:null}}},[field],"0"),false);
});
test("Find keeps canonical row order and evidence selection while keyboard focus falls back to visible matches",()=>{
 const first=projection.rows[0],second={...first,key:"row_"+"b".repeat(64),label:"Other retained row"};
 const rows=[second,first],matched=rows.filter(value=>worksheetRowMatches(value,[field],"other"));
 assert.deepEqual(matched,[second]);assert.deepEqual(rows,[second,first]);
 assert.deepEqual(worksheetTabStop({row:first.key,column:"units"},matched.map(value=>value.key),["$row","units"]),{row:second.key,column:"units"});
 assert.equal(worksheetTabStop({row:first.key,column:"units"},[],["$row","units"]),null);
});
test("saved Find is bounded, backwards compatible and separate from the exact server request",()=>{
 const input={version:1,request,valid_at:time,known_at:time,receipt_hash:hash,columns:["units"],workspace:{grid:{widths:{units:180},pinned:["units"],focus:{row,column:"units"},left:20},dock:"right",collapsed:true,size:340}};
 const old=parseView(JSON.stringify(input),id);assert.equal(old.workspace.grid.search,"");
 const searched=parseView(JSON.stringify({...input,workspace:{...input.workspace,grid:{...input.workspace.grid,search:"retained group",rows:projection.rows}}}),id);
 assert.equal(searched.workspace.grid.search,"retained group");assert.deepEqual(searched.request,old.request);assert.equal(searched.receipt_hash,old.receipt_hash);assert.deepEqual(searched.workspace.grid.pinned,["units"]);assert.equal(JSON.stringify(searched).includes("9007199254740993"),false);
 assert.doesNotThrow(()=>assertProjection(projection,searched.request,searched));
 for(const search of [42,{rows:projection.rows},null])assert.equal(parseView(JSON.stringify({...input,workspace:{...input.workspace,grid:{search}}}),id).workspace.grid.search,"");
 assert.equal(parseView(JSON.stringify({...input,workspace:{...input.workspace,grid:{search:"x".repeat(300)}}}),id).workspace.grid.search.length,200);
});
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

test("workspace preferences allowlist layout without persisting result values or credentials",()=>{
 const input={version:1,request,valid_at:time,known_at:time,receipt_hash:hash,columns:["units"],workspace:{grid:{widths:{units:900,other:-4},pinned:["units",4],focus:{row,column:"units"},left:180,token:"secret",rows:projection.rows},dock:"bottom",collapsed:true,size:999}};
 const view=parseView(JSON.stringify(input),id);
 assert.deepEqual(view.workspace,{grid:{widths:{units:600,other:88},pinned:["units"],focus:{row,column:"units"},left:180,search:""},dock:"bottom",collapsed:true,size:700});
 assert.ok(!JSON.stringify(view).includes("secret"));assert.ok(!JSON.stringify(view).includes("9007199254740993"));
 assert.equal(parseView(JSON.stringify({...input,request:{...request,company_id:"wrong"}}),id),null);
});
test("visual usefulness suppresses no measure, single row and equivalent equal magnitudes",()=>{
 assert.equal(hasUsefulMagnitude(projection),false);
 const second=structuredClone(projection.rows[0]);second.key="row_"+"b".repeat(64);
 const many={...projection,rows:[projection.rows[0],second]};assert.equal(hasUsefulMagnitude(many),false);
 second.values.units.value="2";assert.equal(hasUsefulMagnitude(many),true);
 assert.equal(hasUsefulMagnitude({...many,descriptor:{...many.descriptor,measure:null,visual:"NONE"}}),false);
 assert.equal(hasUsefulMagnitude({...many,rows:[{...second,values:{units:{state:"VALUE",value:"1.0"}}},{...second,values:{units:{state:"VALUE",value:"1.00"}}}]}),false);
});

test("worksheet retains a keyboard entry after filtering, hiding columns or scrolling",()=>{
 const focus={row:"retained",column:"amount"};
 assert.deepEqual(worksheetTabStop(focus,["first","retained"],["$row","amount"]),focus);
 assert.deepEqual(worksheetTabStop(focus,["filtered"],["$row","amount"]),{row:"filtered",column:"amount"});
 assert.deepEqual(worksheetTabStop(focus,["retained"],["$row"]),{row:"retained",column:"$row"});
 assert.deepEqual(worksheetTabStop(focus,["window-row"],["$row","amount"]),{row:"window-row",column:"amount"});
 assert.deepEqual(worksheetTabStop(null,["first"],["$row","amount"]),{row:"first",column:"$row"});
 assert.equal(worksheetTabStop(focus,[],["$row"]),null);
 assert.equal(worksheetTabStop(focus,["retained"],[]),null);
 assert.deepEqual(focus,{row:"retained",column:"amount"});
});

const presentedField={...objectTable.descriptor.fields[0],unit:"GEL",unit_reference:pin,presentation:{format:"FIXED_DECIMAL",fraction_digits:2,currency:pin}};
test("declared decimal display preserves large exact strings, signs and tiny residues",()=>{
 for(const [exact,expected] of [["900719925474099312345.125","900,719,925,474,099,312,345.13"],["-58988.955","-58,988.96"],["0.0000000000006576","≈0.00"],["-0.0000000000006576","≈-0.00"],["0","0.00"],["-0.00","-0.00"],["1E+900","1E+900"],["1E-900","1E-900"]]){
  assert.equal(formatAnalysisDecimal(exact,presentedField),expected);
  assert.equal(formatAnalysisDecimal(exact,field),exact);
 }
 assert.equal(formatAnalysisDecimal("12.5",{...presentedField,presentation:{...presentedField.presentation,fraction_digits:0}}),"13");
 assert.equal(formatAnalysisDecimal("12.1234567",{...presentedField,presentation:{...presentedField.presentation,fraction_digits:6}}),"12.123457");
});
test("presentation is optional and cannot override currency, type or authority semantics",()=>{
 const candidate={...objectTable,descriptor:{...objectTable.descriptor,fields:[presentedField]}};
 const retained=JSON.stringify(candidate);
 assert.doesNotThrow(()=>assertProjection(candidate,request));
 assert.equal(JSON.stringify(candidate),retained);
 assert.equal(candidate.descriptor.measure,null);assert.equal(candidate.descriptor.visual,"NONE");
 for(const patch of [{presentation:null},{presentation:{...presentedField.presentation,format:"PERCENT"}},{presentation:{...presentedField.presentation,fraction_digits:7}},{presentation:{...presentedField.presentation,fraction_digits:true}},{presentation:{...presentedField.presentation,fraction_digits:1.5}},{presentation:{...presentedField.presentation,currency:{...pin,version_id:"22222222-2222-4222-8222-222222222222"}}},{presentation:{...presentedField.presentation,currency:{...pin,content_hash:"b".repeat(64)}}},{presentation:{...presentedField.presentation,scale:100}},{unit:null},{unit:" "},{unit_reference:null},{kind:"integer"},{role:"DIMENSION"}]){
  const invalid={...presentedField,...patch};
  assert.throws(()=>assertProjection({...candidate,descriptor:{...candidate.descriptor,fields:[invalid]}},request));
  assert.throws(()=>formatAnalysisDecimal("12.345",invalid));
 }
 assert.throws(()=>assertProjection({...candidate,descriptor:{...candidate.descriptor,visual:"HORIZONTAL_BARS",measure:"units"}},request));
 assert.doesNotThrow(()=>assertProjection({...projection,descriptor:{...projection.descriptor,fields:[{...presentedField,role:"MEASURE",aggregation:"RETAINED_VALUE_ONLY"}]}},request));
});

test("source-review route refuses a saved result for a different invocation in the same company",()=>{
 const view={version:1,request,valid_at:time,known_at:time,receipt_hash:hash,columns:["units"],visual:false,pane:"evidence",scroll:0};
 assert.ok(parseView(JSON.stringify(view),id,id));
 assert.equal(parseView(JSON.stringify(view),id,"22222222-2222-4222-8222-222222222222"),null);
});
