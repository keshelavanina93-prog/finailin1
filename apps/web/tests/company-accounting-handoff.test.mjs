import test from "node:test";
import assert from "node:assert/strict";
import {loadTypeScript} from "./load-typescript.mjs";
const {companyAccountingHandoff,validateAccountingHandoff,accountingEntryForSession,accountingCompanySnapshot,companyAccountingOrigin,isCompanyAccountingOrigin,accountingOriginViewKey,accountingForegroundContext,accountingContinuation}=await loadTypeScript(new URL("../app/company-accounting-handoff.ts",import.meta.url));
const company={display_name:"Exact company",resource_id:"11111111-1111-4111-8111-111111111111",version_id:"22222222-2222-4222-8222-222222222222",content_hash:"a".repeat(64),object_type:"LegalEntity",authority_state:"APPROVED",evidence_class:"SOURCE_BOUND",attributes:{private:"not copied"}};
const home={contract:"g8-company-home/1",company,valid_at:"2026-09-08T04:01:58.934174+00:00",known_at:"2026-09-08T08:02:00.433237+04:00",current_use_authorized:false,business_effect_authorized:false,financial_context:{amount:"not copied"}};
const context={company,relationships:[],structural_resources:[],ledgers:[],accounting_sources:[],licence_evidence:[],disclosures:[],dimensions:[]};
const response={context,valid_at:home.valid_at,known_at:home.known_at};

test("Home accounting handoff keeps only exact company pins and microsecond cutoffs",()=>{
 const handoff=companyAccountingHandoff(home);
 assert.deepEqual(handoff,{company:{resource_id:company.resource_id,version_id:company.version_id,content_hash:company.content_hash},validAt:home.valid_at,knownAt:home.known_at,tab:"accounting"});
 assert.equal(JSON.stringify(handoff).includes("not copied"),false);
 for(const patch of [{current_use_authorized:true},{business_effect_authorized:true},{company:{...company,evidence_class:"REFERENCE_TEMPLATE"}},{company:{...company,authority_state:"PROPOSED"}},{company:{...company,object_type:"EnterpriseGroup"}},{company:{...company,content_hash:"invalid"}},{known_at:"2026-09-08T04:02:00"}])assert.throws(()=>companyAccountingHandoff({...home,...patch}));
});
test("explicit accounting snapshot refuses a newer company revision or changed microsecond",()=>{
 const handoff=companyAccountingHandoff(home);
 assert.equal(accountingCompanySnapshot(response,company.resource_id,handoff,handoff).context.company.version_id,company.version_id);
 assert.doesNotThrow(()=>accountingCompanySnapshot({...response,known_at:"2026-09-08T04:02:00.433237Z"},company.resource_id,handoff,handoff));
 for(const patch of [{version_id:"33333333-3333-4333-8333-333333333333"},{content_hash:"b".repeat(64)}])assert.throws(()=>accountingCompanySnapshot({...response,context:{...context,company:{...company,...patch}}},company.resource_id,handoff,handoff));
 assert.throws(()=>accountingCompanySnapshot({...response,known_at:"2026-09-08T04:02:00.433238Z"},company.resource_id,handoff,handoff));
 assert.throws(()=>validateAccountingHandoff(handoff,"44444444-4444-4444-8444-444444444444"));
});
test("an explicit new snapshot releases the Home pin while direct company browsing remains supported",()=>{
 const successor={...response,context:{...context,company:{...company,version_id:"33333333-3333-4333-8333-333333333333",content_hash:"b".repeat(64)}},known_at:"2026-09-09T04:02:00.433237Z"};
 const requested={validAt:successor.valid_at,knownAt:successor.known_at};
 assert.doesNotThrow(()=>accountingCompanySnapshot(successor,company.resource_id,requested,null));
 assert.doesNotThrow(()=>accountingCompanySnapshot(response,company.resource_id,null,null));
});
test("handoffs cannot cross token sessions or company selections",()=>{
 const entry={token:"session-a",entryId:"entry-a",handoff:companyAccountingHandoff(home)};
 assert.equal(accountingEntryForSession(entry,"session-a",company.resource_id),entry);
 assert.equal(accountingEntryForSession(entry,"session-b",company.resource_id),null);
 assert.equal(accountingEntryForSession(entry,"session-a","other-company"),null);
 assert.equal(accountingEntryForSession(null,"session-a",company.resource_id),null);
});

const {journalReviewEntryForSession,journalReviewOriginMatches,journalReviewHistoryMode}=await loadTypeScript(new URL("../app/journal-review-handoff.ts",import.meta.url));
const {isCompanyMapHandoff,isCompanyExplorationHandoff,restoreCompanyExplorationFocus}=await loadTypeScript(new URL("../app/company-map-handoff.ts",import.meta.url));
const homeContext=()=>({status:"ready",companyId:company.resource_id,company,validAt:home.valid_at,knownAt:home.known_at});
test("accounting foreground binds the exact Home company and time, never financial payloads",()=>{
 const reference=companyAccountingOrigin(homeContext(),companyAccountingHandoff(home));
 assert.equal(isCompanyAccountingOrigin(reference),true);assert.equal(isCompanyExplorationHandoff(reference),true);assert.equal(isCompanyMapHandoff(reference),false);
 assert.deepEqual(Object.keys(reference).sort(),["company","handoff","kind","knownAt","validAt"]);assert.equal(JSON.stringify(reference).includes("not copied"),false);
 for(const current of [null,{...homeContext(),status:"updating"},{...homeContext(),companyId:"foreign"},{...homeContext(),company:{...company,version_id:"33333333-3333-4333-8333-333333333333"}},{...homeContext(),company:{...company,content_hash:"b".repeat(64)}},{...homeContext(),knownAt:"2026-09-08T04:02:00.433238Z"}])assert.throws(()=>companyAccountingOrigin(current,companyAccountingHandoff(home)));
});
test("Home accounting shares live guarded Back/Forward and snapshot-scoped preferences",()=>{
 const reference=companyAccountingOrigin(homeContext(),companyAccountingHandoff(home)),entry={token:"session",entryId:"33333333-3333-4333-8333-333333333333",returnView:"home",reference};
 assert.equal(journalReviewEntryForSession(entry,"session",company.resource_id,"home"),entry);
 for(const args of [["other",company.resource_id,"home"],["session","foreign","home"],["session",company.resource_id,"companies"]])assert.equal(journalReviewEntryForSession(entry,...args),null);
 assert.equal(journalReviewHistoryMode({g8JournalReview:entry.entryId},entry),"review");assert.equal(journalReviewHistoryMode({g8JournalReturn:entry.entryId},entry),"return");
 assert.equal(journalReviewHistoryMode({g8JournalReview:entry.entryId},null),"refused");assert.equal(journalReviewHistoryMode({g8JournalReview:entry.entryId,g8JournalReturn:entry.entryId},entry),"refused");
 const key=accountingOriginViewKey("actor-scope",reference);assert.notEqual(key,`actor-scope:companies:${company.resource_id}`);
 assert.equal(key,accountingOriginViewKey("actor-scope",companyAccountingOrigin(homeContext(),companyAccountingHandoff(home))));
 assert.equal(key,accountingOriginViewKey("actor-scope",{...reference,knownAt:"2026-09-08T04:02:00.433237Z"}));
 assert.notEqual(key,accountingOriginViewKey("other-scope",reference));
 assert.throws(()=>accountingOriginViewKey("actor-scope",{...reference,knownAt:"2026-09-08T04:02:00.433238Z"}));
});
test("foreground NYX readback cannot overwrite Home origin or cross session/entry; changed accounting time remains explicit",()=>{
 const origin=homeContext(),reference=companyAccountingOrigin(origin,companyAccountingHandoff(home)),key='["session","entry"]';
 const changed={...origin,company:{...company,version_id:"33333333-3333-4333-8333-333333333333",content_hash:"b".repeat(64)},knownAt:"2026-09-09T04:02:00.433237Z"};
 assert.equal(accountingForegroundContext({key,context:changed},key,company.resource_id),changed);
 assert.equal(journalReviewOriginMatches(reference,origin),true);assert.equal(journalReviewOriginMatches(reference,changed),false);
 const readyDeparture=validateAccountingHandoff({company:changed.company,validAt:changed.validAt,knownAt:changed.knownAt,tab:"accounting"},company.resource_id);
 assert.equal(readyDeparture.company.version_id,changed.company.version_id);assert.equal(readyDeparture.knownAt,changed.knownAt);
 for(const value of [null,{key:'["new-session","entry"]',context:changed},{key:'["session","other-entry"]',context:changed},{key,context:{...changed,companyId:"foreign"}}])assert.deepEqual(accountingForegroundContext(value,key,company.resource_id),{status:"updating",companyId:company.resource_id});
 assert.equal(accountingForegroundContext({key,context:changed},null,company.resource_id),null);
 for(const status of ["updating","unavailable"])assert.deepEqual(accountingForegroundContext({key,context:{status,companyId:company.resource_id}},key,company.resource_id),{status,companyId:company.resource_id});
});
test("accounting return restores Home financial control, nested scroll and primary scroll without refetching Home",()=>{
 const calls=[],control={isConnected:true,closest:()=>null,getClientRects:()=>[{}],focus:value=>calls.push(["focus",value])};
 const origin={element:{isConnected:true,hidden:false,inert:false,getClientRects:()=>[]},queue:control,focus:control,scroll:990,scrolls:[{element:{isConnected:true,scrollTo:value=>calls.push(["nested",value])},top:60,left:35}]};
 assert.equal(restoreCompanyExplorationFocus(origin,{scrollTo:value=>calls.push(["main",value])}),true);
 assert.deepEqual(calls,[["main",{top:990,behavior:"instant"}],["nested",{top:60,left:35,behavior:"instant"}],["focus",{preventScroll:true}]]);
 origin.element.inert=true;assert.equal(restoreCompanyExplorationFocus(origin,null),false);
});

test("Forward can resume the validated foreground snapshot while immutable Home and preference scope remain original",()=>{
 const reference=companyAccountingOrigin(homeContext(),companyAccountingHandoff(home));
 const changed={...homeContext(),company:{...company,version_id:"33333333-3333-4333-8333-333333333333",content_hash:"b".repeat(64)},validAt:"2026-09-09T00:00:00.123456Z",knownAt:"2026-09-10T00:00:00.654321Z"};
 const next=accountingContinuation(changed,company.resource_id),entry={reference,accountingHandoff:next};
 assert.equal(entry.accountingHandoff.knownAt,changed.knownAt);assert.equal(entry.accountingHandoff.company.version_id,changed.company.version_id);
 assert.equal(entry.reference.knownAt,home.known_at);assert.equal(entry.reference.company.version_id,company.version_id);
 assert.equal(accountingOriginViewKey("scope",entry.reference),accountingOriginViewKey("scope",reference));
 for(const status of ["updating","unavailable"])assert.equal(accountingContinuation({status,companyId:company.resource_id},company.resource_id),null);
 assert.throws(()=>accountingContinuation({...changed,companyId:"foreign"},company.resource_id));
 assert.throws(()=>accountingContinuation({...changed,knownAt:"2026-09-10T00:00:00"},company.resource_id));
});
