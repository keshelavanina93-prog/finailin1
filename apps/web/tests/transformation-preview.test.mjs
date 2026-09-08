import assert from "node:assert/strict";
import test from "node:test";
import {loadTypeScript} from "./load-typescript.mjs";
const {assertTransformationPreview}=await loadTypeScript(new URL("../app/transformation-preview.ts",import.meta.url));
const request={request_id:"run",transformation:{resource_id:"definition",version_id:"revision"},valid_at:"2025-01-01T00:00:00.123456Z",known_at:"2026-09-08T00:00:00.654321Z"};
function preview(){return {contract:"transformation-preview/1",request,plan_hash:"a".repeat(64),coverage:"PLAN_METADATA_ONLY",transformed_rows_available:false,current_use_authorized:false,business_effect_authorized:false,exact_scope:{},compiled_plan:{contract:"transformation-plan/1",request,plan_hash:"a".repeat(64),nodes:[{node_id:"source",depends_on:[]}],outputs:[{output_id:"result",node_id:"source"}],resource_budget:{max_returned_rows:50,max_derived_evaluations:100,max_published_result_bytes:1000},current_use_authorized:false,business_effect_authorized:false}};}
test("preview retains exact request and refuses revision, microsecond, hash and authority changes",()=>{
 assert.doesNotThrow(()=>assertTransformationPreview(preview(),request));
 for(const mutate of [p=>p.request.request_id="another",p=>p.request.transformation.version_id="latest",p=>p.request.known_at="2026-09-08T00:00:00.654322Z",p=>p.plan_hash="b".repeat(64),p=>p.current_use_authorized=true,p=>p.compiled_plan.business_effect_authorized=true,p=>p.transformed_rows_available=true,p=>p.compiled_plan.outputs[0].node_id="absent",p=>p.compiled_plan.resource_budget.max_returned_rows=-1]){
  const value=structuredClone(preview());mutate(value);assert.throws(()=>assertTransformationPreview(value,request));
 }
});
