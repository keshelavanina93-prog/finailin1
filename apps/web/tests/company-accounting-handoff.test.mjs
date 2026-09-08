import test from "node:test";
import assert from "node:assert/strict";
import {loadTypeScript} from "./load-typescript.mjs";
const {companyAccountingHandoff,validateAccountingHandoff,accountingEntryForSession,accountingCompanySnapshot}=await loadTypeScript(new URL("../app/company-accounting-handoff.ts",import.meta.url));
const company={resource_id:"11111111-1111-4111-8111-111111111111",version_id:"22222222-2222-4222-8222-222222222222",content_hash:"a".repeat(64),object_type:"LegalEntity",authority_state:"APPROVED",evidence_class:"SOURCE_BOUND",attributes:{private:"not copied"}};
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
