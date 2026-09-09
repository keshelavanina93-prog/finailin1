import test from "node:test";
import assert from "node:assert/strict";
import {loadTypeScript} from "./load-typescript.mjs";
const {companyMapHandoff,isCompanyMapHandoff,restoreCompanyMapFocus,sameCompanyMapSelection}=await loadTypeScript(new URL("../app/company-map-handoff.ts",import.meta.url));
const {journalReviewEntryForSession,journalReviewOriginMatches,journalReviewHistoryMode}=await loadTypeScript(new URL("../app/journal-review-handoff.ts",import.meta.url));
const id=n=>`00000000-0000-4000-8000-${String(n).padStart(12,"0")}`;
const company={resource_id:id(1),version_id:id(2),content_hash:"a".repeat(64),display_name:"Company",attributes:{payload:"not copied"}};
const context={status:"ready",companyId:id(1),company,validAt:"2025-01-01T00:00:00.123456Z",knownAt:"2026-01-01T00:00:00.654321Z"};
const state={lens:"gas_network",validAt:"2025-06-01T00:00:00.123456Z",knownAt:"2026-06-01T00:00:00.654321Z",center:[44.8,41.7],zoom:11,bbox:"44,41,45,42",search:"selected facility",payload:"not copied"};
const selection={resource:{resource_id:id(3),version_id:id(4),content_hash:"b".repeat(64),display_name:"Linked asset",attributes:{company_id:id(9)}},validAt:state.validAt,knownAt:state.knownAt};
test("map handoff retains company and map snapshots separately, exact selected pin and reference-only viewport",()=>{
 const ref=companyMapHandoff(context,state,selection);assert.equal(isCompanyMapHandoff(ref),true);assert.equal(ref.company.version_id,id(2));assert.equal(ref.validAt,context.validAt);assert.equal(ref.state.validAt,state.validAt);assert.equal(ref.selection,selection);assert.equal(ref.state.bbox,state.bbox);assert.equal(ref.state.search,state.search);assert.equal(JSON.stringify(ref.company).includes("not copied"),false);assert.equal(JSON.stringify(ref.state).includes("not copied"),false);assert.notEqual(ref.state.center,state.center);
 assert.doesNotThrow(()=>companyMapHandoff(context,state,{...selection,knownAt:"2026-06-01T04:00:00.654321+04:00"}));
 for(const patch of [{status:"updating"},{companyId:id(9)},{knownAt:"2026-02-30T00:00:00Z"},{company:{...company,version_id:"bad"}}])assert.throws(()=>companyMapHandoff({...context,...patch},state,selection));
 for(const patch of [{knownAt:"2026-06-01T00:00:00.654322Z"},{resource:{...selection.resource,version_id:"bad"}},{resource:{...selection.resource,content_hash:"bad"}}])assert.throws(()=>companyMapHandoff(context,state,{...selection,...patch}));
});
test("handoff refuses naive/latest implicit time, invalid coordinates and unbounded filters",()=>{
 for(const patch of [{validAt:""},{knownAt:"2026-06-01T00:00:00"},{center:[Infinity,42]},{center:[181,42]},{zoom:-1},{zoom:NaN},{bbox:"45,41,44,42"},{bbox:"44,41,45,99"},{search:"x".repeat(201)},{lens:"inferred_live_network"}])assert.throws(()=>companyMapHandoff(context,{...state,...patch}));
});
test("map uses the same live session/history origin gate as journal and workflow without interpreting their IDs",()=>{
 const reference=companyMapHandoff(context,state,selection),entry={entryId:id(5),token:"session",returnView:"home",reference,mapState:state,mapSelection:selection};
 assert.equal(journalReviewEntryForSession(entry,"session",id(1),"home"),entry);assert.equal(journalReviewOriginMatches(reference,context),true);
 for(const args of [["other",id(1),"home"],["session",id(9),"home"],["session",id(1),"companies"]])assert.equal(journalReviewEntryForSession(entry,...args),null);
 assert.equal(journalReviewOriginMatches(reference,{...context,company:{...company,content_hash:"c".repeat(64)}}),false);
 assert.equal(journalReviewHistoryMode({g8JournalReview:id(5)},entry),"review");assert.equal(journalReviewHistoryMode({g8JournalReturn:id(5)},entry),"return");assert.equal(journalReviewHistoryMode({g8JournalReview:id(5)},null),"refused");assert.equal(journalReviewHistoryMode({g8JournalReview:id(5),g8JournalReturn:id(5)},entry),"refused");
 assert.equal(isCompanyMapHandoff({kind:"workflow",workflowId:"opa_"+"a".repeat(64)}),false);assert.equal(isCompanyMapHandoff({proposalId:id(9)}),false);
});
test("return restores primary/nested scroll and invoking map control without needing a queue refresh",()=>{
 const calls=[],focus={isConnected:true,closest:()=>null,getClientRects:()=>[{}],focus:value=>calls.push(["focus",value])};
 const queue={...focus,focus:value=>calls.push(["fallback",value])};
 const origin={element:{isConnected:true,hidden:false,inert:false,getClientRects:()=>[]},queue,focus,scroll:820,scrolls:[{element:{isConnected:true,scrollTo:value=>calls.push(["nested",value])},top:20,left:50}]};
 assert.equal(restoreCompanyMapFocus(origin,{scrollTo:value=>calls.push(["main",value])}),true);assert.deepEqual(calls,[["main",{top:820,behavior:"instant"}],["nested",{top:20,left:50,behavior:"instant"}],["focus",{preventScroll:true}]]);
 focus.isConnected=false;assert.equal(restoreCompanyMapFocus(origin,null),true);assert.equal(calls.at(-1)[0],"fallback");origin.element.inert=true;assert.equal(restoreCompanyMapFocus(origin,null),false);
});

test("compact map connection opening refuses a stale NYX resource pin or time",()=>{
 assert.equal(sameCompanyMapSelection(selection,selection),true);assert.equal(sameCompanyMapSelection(selection,{...selection,knownAt:"2026-06-01T04:00:00.654321+04:00"}),true);
 for(const other of [null,{...selection,resource:{...selection.resource,version_id:id(9)}},{...selection,resource:{...selection.resource,content_hash:"c".repeat(64)}},{...selection,knownAt:"2026-06-01T00:00:00.654322Z"}])assert.equal(sameCompanyMapSelection(selection,other),false);
});
