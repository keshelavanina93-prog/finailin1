import test from "node:test";
import assert from "node:assert/strict";
import {loadTypeScript} from "./load-typescript.mjs";
const {companyResourceInspection,companyResourceInspectionMatches,assertCompanyResourceInspection,restoreCompanyInspectionFocus,cancelResourceInspectionRead}=await loadTypeScript(new URL("../app/company-resource-inspection.ts",import.meta.url));
const id=n=>`00000000-0000-4000-8000-${String(n).padStart(12,"0")}`;
const validAt="2025-01-01T00:00:00.123456Z",knownAt="2026-09-01T12:00:00.654321Z";
const company={resource_id:id(1),version_id:id(2),content_hash:"a".repeat(64),display_name:"Company",attributes:{private:"not copied"}};
const context={status:"ready",companyId:id(1),company,validAt,knownAt};
const resource={resource_id:id(3),version_id:id(4),content_hash:"b".repeat(64),attributes:{company_id:id(9),private:"not copied"}};
const reference=()=>companyResourceInspection(context,resource);
const response=()=>({purpose:"HISTORICAL_INSPECTION",selection_mode:"EXACT_VERSION",current_use_authorized:false,resource,known_at:knownAt});
test("bound resource inspection keeps canonical pins without inventing resource company membership",()=>{
 const ref=reference();assert.equal(ref.company.resource_id,id(1));assert.equal(ref.resource.resource_id,id(3));assert.equal(ref.resource.version_id,id(4));assert.equal(ref.resource.content_hash,resource.content_hash);assert.equal(JSON.stringify(ref).includes("not copied"),false);
 const historical=companyResourceInspection(context,resource,validAt);assert.equal(historical.resource.known_at,validAt);assert.equal(historical.knownAt,knownAt);
 for(const input of [{...resource,version_id:undefined},{...resource,content_hash:"bad"},{...resource,resource_id:"bad"}])assert.throws(()=>companyResourceInspection(context,input));
 assert.throws(()=>companyResourceInspection({...context,status:"updating"},resource));assert.throws(()=>companyResourceInspection(context,resource,"2026-02-30T00:00:00Z"));
});
test("pane and NYX readback refuse a new token/surface/company/version/hash or time snapshot",()=>{
 const entry={surfaceKey:"session:company:view",requestId:1,reference:reference()};
 assert.equal(companyResourceInspectionMatches(entry,entry.surfaceKey,context),true);
 assert.equal(companyResourceInspectionMatches(entry,"new-session:company:view",context),false);
 for(const patch of [{companyId:id(9)},{company:{...company,version_id:id(9)}},{company:{...company,content_hash:"c".repeat(64)}},{knownAt:"2026-09-01T12:00:00.654322Z"},{status:"updating"}])assert.equal(companyResourceInspectionMatches(entry,entry.surfaceKey,{...context,...patch}),false);
 assert.equal(companyResourceInspectionMatches(entry,entry.surfaceKey,{...context,knownAt:"2026-09-01T16:00:00.654321+04:00"}),true);
});
test("inspection must be exact historical-only authority and the selected microsecond/hash pin",()=>{
 assert.doesNotThrow(()=>assertCompanyResourceInspection(response(),reference()));
 for(const patch of [{purpose:"CURRENT_USE"},{current_use_authorized:true},{selection_mode:"LATEST_KNOWN"},{resource:{...resource,version_id:id(8)}},{resource:{...resource,content_hash:"c".repeat(64)}},{known_at:"2026-09-01T12:00:00.654322Z"},{known_at:"2026-09-01T12:00:00"}])assert.throws(()=>assertCompanyResourceInspection({...response(),...patch},reference()));
 assert.doesNotThrow(()=>assertCompanyResourceInspection({...response(),known_at:"2026-09-01T16:00:00.654321+04:00"},reference()));
});
test("close returns focus without scrolling and refuses hidden or removed invoking controls",()=>{
 const calls=[],element={isConnected:true,closest:()=>null,getClientRects:()=>[{}],focus:options=>calls.push(options)};
 assert.equal(restoreCompanyInspectionFocus(element),true);assert.deepEqual(calls,[{preventScroll:true}]);
 for(const patch of [{isConnected:false},{closest:()=>({})},{getClientRects:()=>[]}])assert.equal(restoreCompanyInspectionFocus({...element,...patch}),false);
});

test("departing a pending inspection invalidates its result and resets readback without clearing a newer request",()=>{
 const current={controller:new AbortController(),requestId:5};
 const cancelled=cancelResourceInspectionRead(current,5);
 assert.equal(current.controller.signal.aborted,true);assert.deepEqual(cancelled,{requestId:6,clearReadback:true});
 const stale={controller:new AbortController(),requestId:5};
 assert.deepEqual(cancelResourceInspectionRead(stale,7),{requestId:7,clearReadback:false});assert.equal(stale.controller.signal.aborted,true);
 // The aborted read can neither satisfy the request generation nor revive loading/selection.
 assert.equal(current.requestId===cancelled.requestId&&!current.controller.signal.aborted,false);
});
