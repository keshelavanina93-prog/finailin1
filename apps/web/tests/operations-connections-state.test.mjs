import test from "node:test";
import assert from "node:assert/strict";
import {loadTypeScript} from "./load-typescript.mjs";
const {assertConnectionSnapshot,connectedSelection}=await loadTypeScript(new URL("../app/operations-connections-state.ts",import.meta.url));
const node=n=>({resource_id:`asset-${n}`,version_id:`version-${n}`,content_hash:String(n).repeat(64),display_name:`ქსელი / Сеть / Network ${n}`});
function fixture(){const root=node(1),target=node(2);const selection={resource:root,validAt:"2024-01-01T00:00:00.123456Z",knownAt:"2025-02-01T00:00:00.654321Z"};return {selection,data:{root_id:root.resource_id,valid_at:selection.validAt,known_at:selection.knownAt,depth:2,interpretation:"EXPLICIT_DIRECTED_CONNECTIVITY_ONLY",resources:[root,target],edges:[{source_id:root.resource_id,target_id:target.resource_id,relation:"FEEDS"}],completeness:{snapshot_bounded:false,node_bounded:false,depth_bounded:false,node_limit:250}}};}
test("historical connection drill preserves exact returned resource and microsecond cutoffs",()=>{
 const {selection,data}=fixture();assert.doesNotThrow(()=>assertConnectionSnapshot(data,selection));
 const next=connectedSelection(data,"asset-2");assert.equal(next.resource,data.resources[1]);assert.equal(next.validAt,selection.validAt);assert.equal(next.knownAt,selection.knownAt);
 assert.equal(connectedSelection(data,"outside-snapshot"),null);
});
test("successor asset versions, roots and time changes are refused before displaying connections",()=>{
 for(const field of ["valid_at","known_at"]){const {selection,data}=fixture();data[field]=data[field].replace(/\dZ$/,"9Z");assert.throws(()=>assertConnectionSnapshot(data,selection));}
 for(const field of ["version_id","content_hash"]){const {selection,data}=fixture();data.resources[0]={...data.resources[0],[field]:"successor"};assert.throws(()=>assertConnectionSnapshot(data,selection));}
 for(const patch of [{root_id:"other-company-asset"},{depth:3},{interpretation:"LIVE_NETWORK"},{valid_at:"2024-01-01"}]){const {selection,data}=fixture();assert.throws(()=>assertConnectionSnapshot({...data,...patch},selection));}
 const {selection,data}=fixture();data.valid_at="2024-01-01T04:00:00.123456+04:00";assert.doesNotThrow(()=>assertConnectionSnapshot(data,selection));
});
test("incomplete, ambiguous and unavailable endpoints cannot create drill targets",()=>{
 for(const change of [data=>data.resources.push(data.resources[0]),data=>data.resources.shift(),data=>data.edges[0].target_id="missing",data=>data.completeness.node_limit=999,data=>data.completeness.snapshot_bounded=null]){const {selection,data}=fixture();change(data);assert.throws(()=>assertConnectionSnapshot(data,selection));}
});
