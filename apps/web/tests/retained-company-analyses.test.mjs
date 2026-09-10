import test from "node:test";
import assert from "node:assert/strict";
import {loadTypeScript} from "./load-typescript.mjs";
const {assertRetainedAnalysisPage,retainedAnalysisTarget,retainedAnalysisRequestCurrent}=await loadTypeScript(new URL("../app/retained-company-analyses-state.ts",import.meta.url));
const id=n=>`00000000-0000-4000-8000-${String(n).padStart(12,"0")}`;
const pin=n=>({resource_id:id(n),version_id:id(n+1),content_hash:"a".repeat(64)});
const valid="2025-01-01T00:00:00.123456Z",known="2026-09-01T00:00:00.654321Z",recorded="2026-09-02T00:00:00.123456Z",cutoff="2026-09-08T00:00:00.123456Z";
const item=contract=>({invocation_id:id(5),function:pin(3),company:pin(1),title:"Retained source objects",receipt_hash:"b".repeat(64),run_id:`fcr_${"c".repeat(64)}`,valid_at:valid,known_at:known,recorded_at:recorded,projection_contract:contract??"semantic-analysis/2",eligibility:"COMPANY_SUBJECT_VERIFIED_SOURCE_REVIEW_REQUIRED"});
const page=()=>({purpose:"HISTORICAL_COMPANY_ANALYSIS_DISCOVERY",company_id:id(1),observed_at:cutoff,recorded_before:cutoff,items:[item()],inspected_count:5,returned_count:1,not_listed_count:4,next_cursor:"opaque_cursor",coverage:"BOUNDED_RETAINED_INVOCATION_PAGE",adapter_scope:"OBJECT_TABLES_AND_GROUPED_OBSERVATIONS_ONLY",current_use_authorized:false,business_effect_authorized:false});
test("bounded metadata page permits skipped or empty scans with continuation, never global coverage",()=>{
 assert.doesNotThrow(()=>assertRetainedAnalysisPage(page(),id(1)));
 assert.doesNotThrow(()=>assertRetainedAnalysisPage({...page(),items:[],returned_count:0,not_listed_count:5},id(1)));
 for(const patch of [{company_id:id(9)},{inspected_count:6},{returned_count:0},{not_listed_count:3},{items:[item(),item()]},{current_use_authorized:true},{business_effect_authorized:true},{adapter_scope:"ALL_FUNCTIONS"},{next_cursor:" "},{recorded_before:"2026-09-09T00:00:00Z"}])assert.throws(()=>assertRetainedAnalysisPage({...page(),...patch},id(1)));
 for(const patch of [{company:pin(9)},{function:{...pin(3),content_hash:"bad"}},{run_id:id(8)},{recorded_at:"2026-09-08T00:00:00.123457Z"},{known_at:"2026-02-30T00:00:00Z"},{eligibility:"SOURCE_AUTHORITY_VERIFIED"}])assert.throws(()=>assertRetainedAnalysisPage({...page(),items:[{...item(),...patch}]},id(1)));
});
test("pagination keeps microsecond cutoff and refuses repeated cursor",()=>{
 assert.doesNotThrow(()=>assertRetainedAnalysisPage(page(),id(1),{recordedBefore:"2026-09-08T04:00:00.123456+04:00",cursor:"previous"}));
 assert.throws(()=>assertRetainedAnalysisPage(page(),id(1),{recordedBefore:"2026-09-08T00:00:00.123457Z",cursor:"previous"}));
 assert.throws(()=>assertRetainedAnalysisPage(page(),id(1),{recordedBefore:cutoff,cursor:"opaque_cursor"}));
});
function projection(contract="semantic-analysis/2"){
 const ref=item(contract),objects=contract.endsWith("2"),field={key:"returned",label:"Recorded observation",kind:objects?"text":"integer",role:objects?"ATTRIBUTE":"MEASURE",aggregation:objects?"NONE":"RETAINED_VALUE_ONLY",definition:pin(3),filterable:false,groupable:false,options:[]};
 return {descriptor:{contract,row_noun:objects?"objects":"groups",invocation_id:ref.invocation_id,receipt_hash:ref.receipt_hash,run_id:ref.run_id,function:ref.function,company:ref.company,title:ref.title,company_label:"Retained company",valid_at:valid,known_at:known,recorded_at:recorded,current_use_authorized:false,business_effect_authorized:false,fields:[field],filtering:"RETAINED_GROUP_SELECTION",grouping:"RETAINED_ROWS_WITHOUT_AGGREGATION",visual:objects?"NONE":"HORIZONTAL_BARS",measure:objects?null:"returned",coverage:[],context:[],unavailable_operations:[],definitions:[],grain:[],partition_keys:[],excluded_evidence:[],authority:"RETAINED_OBSERVATION"},descriptor_sha256:"d".repeat(64),request:{company_id:id(1),invocation_id:id(5)},rows:[{key:`row_${"e".repeat(64)}`,label:"private row not copied",trace:pin(3),contributor_count:0,values:{returned:{state:"VALUE",value:objects?"private row not copied":93827,label:null,reference:null}}}],total_rows:1,sections:[{label:"Retained",row_keys:[`row_${"e".repeat(64)}`]}],selection:null};
}
for(const contract of ["semantic-analysis/1","semantic-analysis/2"])test(`${contract} explicit opening pins the reproduced descriptor without copying result rows`,()=>{
 const value=projection(contract),ref=item(contract),target=retainedAnalysisTarget(value,ref,id(1));
 assert.equal(target.view.request.descriptor_sha256,value.descriptor_sha256);assert.equal(target.view.receipt_hash,ref.receipt_hash);assert.equal(target.journalSnapshot,undefined);assert.equal(JSON.stringify(target).includes("private row"),false);assert.equal(JSON.stringify(target).includes("93827"),false);
 for(const patch of [{run_id:`fcr_${"e".repeat(64)}`},{receipt_hash:"e".repeat(64)},{function:{...ref.function,version_id:id(9)}},{company:{...ref.company,content_hash:"f".repeat(64)}},{known_at:"2026-09-01T00:00:00.654322Z"},{recorded_at:"2026-09-02T00:00:00.123457Z"}])assert.throws(()=>retainedAnalysisTarget({...value,descriptor:{...value.descriptor,...patch}},ref,id(1)));
 assert.throws(()=>retainedAnalysisTarget(value,ref,id(9)));
 assert.doesNotThrow(()=>retainedAnalysisTarget({...value,descriptor:{...value.descriptor,known_at:"2026-09-01T04:00:00.654321+04:00"}},ref,id(1)));
});
test("refresh/page/token departure cancels a pending open even when a late response resolves",()=>{
 const controller=new AbortController();assert.equal(retainedAnalysisRequestCurrent(1,1,controller.signal),true);assert.equal(retainedAnalysisRequestCurrent(1,2,controller.signal),false);controller.abort();assert.equal(retainedAnalysisRequestCurrent(1,1,controller.signal),false);
});
