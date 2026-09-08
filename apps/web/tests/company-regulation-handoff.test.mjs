import test from "node:test";
import assert from "node:assert/strict";
import {loadTypeScript} from "./load-typescript.mjs";
const {companyRegulationHandoff,validateRegulationHandoff,regulationEntryForSession,regulationSnapshotKey,regulationRuleQuery,assertRegulationHandoffPage,companyRegulationOrigin,isCompanyRegulationOrigin,regulationOriginViewKey}=await loadTypeScript(new URL("../app/company-regulation-handoff.ts",import.meta.url));
const id=n=>`00000000-0000-4000-8000-${String(n).padStart(12,"0")}`;
const company={resource_id:id(1),version_id:id(2),content_hash:"a".repeat(64),object_type:"LegalEntity",authority_state:"APPROVED",evidence_class:"SOURCE_BOUND",display_name:"Company snapshot",attributes:{private:"not copied"}};
const validAt="2025-01-01T00:00:00.123456Z",knownAt="2025-02-01T00:00:00.654321Z";
const handoff=()=>companyRegulationHandoff(company,validAt,knownAt);
function fixture(){const expected=handoff();return {expected,inspection:{resource:company,known_at:knownAt},page:{company:{resource_id:company.resource_id,version_id:company.version_id,display_name:company.display_name},at:validAt,known_at:knownAt,context_basis:"INCOMPLETE_CONTEXT",activity:null,accounting_effects_created:false,next_offset:100,rules:[{resource:{resource_id:id(3),version_id:id(4),content_hash:"b".repeat(64),display_name:"Retained interpretation",object_type:"RegulatoryRule",authority_state:"APPROVED",evidence_class:"SOURCE_BOUND",attributes:{legal_entity_id:company.resource_id,definition:{provision:"Retained wording",effective_from:"2026-01-01"}}},dependencies:{},assessment:{legal_state:"FUTURE_EFFECTIVE",applicability:"CONTEXT_REQUIRED",effective_obligation:false,obligation:"Retained wording",days_to_deadline:null,blocking_reasons:["FUTURE_EFFECTIVE","CONTEXT_REQUIRED"]}}]}};}

test("Company 360 handoff copies exact company and aware cutoffs only",()=>{
 const result=handoff();
 assert.deepEqual(result,{company:{resource_id:id(1),version_id:id(2),content_hash:"a".repeat(64)},validAt,knownAt});
 assert.equal(JSON.stringify(result).includes("not copied"),false);
 for(const invalid of [{...company,authority_state:"PROPOSED"},{...company,evidence_class:"REFERENCE_TEMPLATE"},{...company,object_type:"EnterpriseGroup"}])assert.throws(()=>companyRegulationHandoff(invalid,validAt,knownAt));
 for(const invalid of ["2025-02-30T00:00:00Z","2025-01-01T00:00:00","2025-01-01T00:00:00.1234567Z"])assert.throws(()=>companyRegulationHandoff(company,invalid,knownAt));
 assert.throws(()=>validateRegulationHandoff(handoff(),id(9)));
});
test("entry scope and snapshot keys separate ordinary regulation, companies, identities and microsecond snapshots",()=>{
 const entry={token:"active",entryId:id(5),handoff:handoff()};
 assert.equal(regulationEntryForSession(entry,"active",id(1)),entry);
 assert.equal(regulationEntryForSession(entry,"other",id(1)),null);assert.equal(regulationEntryForSession(entry,"active",id(9)),null);
 assert.notEqual(regulationSnapshotKey(),regulationSnapshotKey(entry.handoff));
 assert.notEqual(regulationSnapshotKey(entry.handoff),regulationSnapshotKey({...entry.handoff,knownAt:"2025-02-01T00:00:00.654322Z"}));
 assert.equal(regulationSnapshotKey(entry.handoff),regulationSnapshotKey({...entry.handoff,knownAt:"2025-02-01T04:00:00.654321+04:00"}));
});
test("every rule page retains both cutoffs and never adds assumed activity or customer context",()=>{
 for(const offset of [0,100,100000]){const query=new URLSearchParams(regulationRuleQuery(id(1),offset,handoff()));assert.equal(query.get("at"),validAt);assert.equal(query.get("known_at"),knownAt);assert.equal(query.get("offset"),String(offset));assert.equal(query.get("legal_entity_id"),id(1));assert.equal(query.has("activity"),false);assert.equal(query.has("customer_count"),false);}
 const ordinary=new URLSearchParams(regulationRuleQuery(id(1),0));assert.equal(ordinary.has("at"),false);assert.equal(ordinary.has("known_at"),false);
 for(const offset of [-100,1,100001,NaN])assert.throws(()=>regulationRuleQuery(id(1),offset,handoff()));
});
test("company content and rules are jointly verified at the exact returned time",()=>{
 const {page,inspection,expected}=fixture();assert.doesNotThrow(()=>assertRegulationHandoffPage(page,inspection,expected,0));
 for(const patch of [{content_hash:"c".repeat(64)},{version_id:id(9)},{resource_id:id(9)},{authority_state:"PROPOSED"}])assert.throws(()=>assertRegulationHandoffPage(page,{...inspection,resource:{...company,...patch}},expected,0));
 assert.throws(()=>assertRegulationHandoffPage(page,{...inspection,known_at:"2025-02-01T00:00:00.654322Z"},expected,0));
 for(const patch of [{known_at:"2025-02-01T00:00:00.654322Z"},{at:"2025-01-01T00:00:00.123457Z"},{company:{...page.company,version_id:id(9)}},{next_offset:200},{activity:"SUPPLY"},{accounting_effects_created:true}])assert.throws(()=>assertRegulationHandoffPage({...page,...patch},inspection,expected,0));
 assert.doesNotThrow(()=>assertRegulationHandoffPage({...page,known_at:"2025-02-01T04:00:00.654321+04:00"},inspection,expected,0));
});
test("foreign or unaccepted rules and asserted applicability refuse the whole historical page",()=>{
 for(const patch of [{authority_state:"PROPOSED"},{attributes:{legal_entity_id:id(9),definition:{}}}]){const {page,inspection,expected}=fixture();Object.assign(page.rules[0].resource,patch);assert.throws(()=>assertRegulationHandoffPage(page,inspection,expected,0));}
 const {page,inspection,expected}=fixture();page.rules[0].assessment.effective_obligation=true;assert.throws(()=>assertRegulationHandoffPage(page,inspection,expected,0));
});

const {journalReviewEntryForSession,journalReviewOriginMatches,journalReviewHistoryMode}=await loadTypeScript(new URL("../app/journal-review-handoff.ts",import.meta.url));
const {isCompanyMapHandoff,isCompanyExplorationHandoff,restoreCompanyExplorationFocus}=await loadTypeScript(new URL("../app/company-map-handoff.ts",import.meta.url));
const originContext=()=>({status:"ready",companyId:company.resource_id,company,validAt,knownAt});
test("regulation foreground requires the displayed company pin and exact time without inventing a rule or scenario",()=>{
 const reference=companyRegulationOrigin(originContext(),handoff());
 assert.equal(isCompanyRegulationOrigin(reference),true);assert.equal(isCompanyExplorationHandoff(reference),true);assert.equal(isCompanyMapHandoff(reference),false);
 assert.deepEqual(Object.keys(reference).sort(),["company","handoff","kind","knownAt","validAt"]);
 assert.equal(JSON.stringify(reference).includes("not copied"),false);
 assert.equal(journalReviewOriginMatches(reference,originContext()),true);
 for(const context of [null,{...originContext(),status:"updating"},{...originContext(),companyId:id(9)},{...originContext(),company:{...company,version_id:id(9)}},{...originContext(),company:{...company,content_hash:"b".repeat(64)}},{...originContext(),knownAt:"2025-02-01T00:00:00.654322Z"}])assert.throws(()=>companyRegulationOrigin(context,handoff()));
 assert.doesNotThrow(()=>companyRegulationOrigin({...originContext(),knownAt:"2025-02-01T04:00:00.654321+04:00"},handoff()));
});
test("regulation reuses guarded live Back/Forward and a stable snapshot preference key separate from ordinary Regulation",()=>{
 const reference=companyRegulationOrigin(originContext(),handoff()),entry={entryId:id(5),token:"active",returnView:"companies",reference};
 assert.equal(journalReviewEntryForSession(entry,"active",id(1),"companies"),entry);
 for(const args of [["other",id(1),"companies"],["active",id(9),"companies"],["active",id(1),"home"]])assert.equal(journalReviewEntryForSession(entry,...args),null);
 assert.equal(journalReviewHistoryMode({g8JournalReview:id(5)},entry),"review");assert.equal(journalReviewHistoryMode({g8JournalReturn:id(5)},entry),"return");
 for(const state of [{g8JournalReview:id(9)},{g8JournalReview:id(5),g8JournalReturn:id(5)}])assert.equal(journalReviewHistoryMode(state,entry),"refused");
 assert.equal(journalReviewHistoryMode({g8JournalReview:id(5)},null),"refused");
 const key=regulationOriginViewKey("actor-scope",reference);
 assert.notEqual(key,`actor-scope:regulation:${id(1)}`);
 assert.equal(key,regulationOriginViewKey("actor-scope",companyRegulationOrigin(originContext(),handoff())));
 assert.equal(key,regulationOriginViewKey("actor-scope",companyRegulationOrigin(originContext(),{...handoff(),knownAt:"2025-02-01T04:00:00.654321+04:00"})));
 assert.notEqual(key,regulationOriginViewKey("other-actor-scope",reference));
 assert.throws(()=>regulationOriginViewKey("actor-scope",{...reference,knownAt:"2025-02-01T00:00:00.654322Z"}));
 assert.throws(()=>regulationOriginViewKey("actor-scope",{...reference,company:{...reference.company,version_id:id(9)}}));
});
test("regulation returns directly to mounted company focus/scroll without waiting for a work queue",()=>{
 const calls=[],focus={isConnected:true,closest:()=>null,getClientRects:()=>[{}],focus:value=>calls.push(["focus",value])};
 const origin={element:{isConnected:true,hidden:false,inert:false,getClientRects:()=>[]},queue:focus,focus,scroll:730,scrolls:[{element:{isConnected:true,scrollTo:value=>calls.push(["nested",value])},top:90,left:20}]};
 assert.equal(restoreCompanyExplorationFocus(origin,{scrollTo:value=>calls.push(["main",value])}),true);
 assert.deepEqual(calls,[["main",{top:730,behavior:"instant"}],["nested",{top:90,left:20,behavior:"instant"}],["focus",{preventScroll:true}]]);
 origin.element.hidden=true;assert.equal(restoreCompanyExplorationFocus(origin,null),false);
});
