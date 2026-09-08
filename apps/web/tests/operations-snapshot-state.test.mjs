import test from "node:test";
import assert from "node:assert/strict";
import {loadTypeScript} from "./load-typescript.mjs";
const {assertMapSnapshot}=await loadTypeScript(new URL("../app/operations-snapshot-state.ts",import.meta.url));
function fixture(){const scope={companyId:"company-a",lens:"enterprise_assets",validAt:"2024-01-01T00:00:00.123456Z",knownAt:"2025-02-01T00:00:00.654321Z"};return {scope,data:{type:"FeatureCollection",company_id:scope.companyId,lens:scope.lens,valid_at:scope.validAt,known_at:scope.knownAt,features:[],unmapped:[],counts:{assets:0,mapped_in_bounds:0,outside_bounds:0,unmapped:0},completeness:{snapshot_bounded:false,features_truncated:false,unmapped_truncated:false,scan_limit:5000,limit:500}}};}
test("company map validates its exact scope and microsecond snapshot even when empty",()=>{
 const {scope,data}=fixture();assert.doesNotThrow(()=>assertMapSnapshot(data,scope));
 data.valid_at="2024-01-01T04:00:00.123456+04:00";assert.doesNotThrow(()=>assertMapSnapshot(data,scope));
 for(const patch of [{company_id:"company-b"},{company_id:null},{company_id:undefined},{lens:"gas_network"},{valid_at:"2024-01-01T00:00:00.123457Z"},{known_at:"2025-02-01T00:00:00.654322Z"}])assert.throws(()=>assertMapSnapshot({...data,...patch},scope));
});
test("authorized-wide current geography requires explicit null company and aware returned time",()=>{
 const {data}=fixture();data.company_id=null;const scope={lens:data.lens,validAt:"",knownAt:""};assert.doesNotThrow(()=>assertMapSnapshot(data,scope));
 assert.throws(()=>assertMapSnapshot({...data,known_at:"2025-02-01"},scope));
});
test("map refuses ambiguous references or unsupported count and coverage before rendering",()=>{
 for(const mutate of [d=>d.counts.unmapped=1,d=>d.counts.assets=-1,d=>d.completeness.limit=1000,d=>d.completeness.snapshot_bounded=null,d=>{d.unmapped=[{resource:{resource_id:"a",version_id:"v",content_hash:"h",authority_state:"PROPOSED"}}];d.counts.unmapped=1;}]){const {data,scope}=fixture();mutate(data);assert.throws(()=>assertMapSnapshot(data,scope));}
 const {data,scope}=fixture();const resource={resource_id:"a",version_id:"v",content_hash:"h",authority_state:"APPROVED"};data.unmapped=[{resource,reason:"No accepted geometry"}];data.counts.unmapped=1;data.counts.assets=1;assert.doesNotThrow(()=>assertMapSnapshot(data,scope));
 data.unmapped.push({resource});data.counts.unmapped=2;assert.throws(()=>assertMapSnapshot(data,scope));
});
