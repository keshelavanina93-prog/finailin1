import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import ts from "typescript";
const helper=readFileSync(new URL("../app/definition-restoration-time.ts",import.meta.url),"utf8");
const source=readFileSync(new URL("../app/journal-disposition-state.ts",import.meta.url),"utf8").replace('import {restorationInstant} from "./definition-restoration-time";',helper);
const {assertJournalAttempt,assertJournalDispositions}=await import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText).toString("base64")}`);
const id=n=>`${String(n).padStart(8,"0")}-aaaa-4aaa-8aaa-aaaaaaaaaaaa`,pin=n=>({resource_id:id(n),version_id:id(n+100),content_hash:"a".repeat(64)});
const scope={companyId:id(1),requestId:id(2),invocationId:id(3),proposalId:id(4)},binding=pin(5);
function fixture(){
 const attempt={contract:"source-journal-production/1",receipt_hash:"b".repeat(64),source_sha256:"c".repeat(64),source_receipt_hash:"d".repeat(64),binding,request:{request_id:scope.requestId,company_id:scope.companyId,invocation_id:scope.invocationId,coordinates:["Sheet!A2"]},rows:[{coordinate:"Sheet!A2",state:"ELIGIBLE_FOR_REVIEW",blockers:[],proposal:{proposal_id:scope.proposalId,mutations:[{resource_id:id(6),object_type:"JournalEntry",attributes:{legal_entity_id:scope.companyId,accounting_binding_id:binding.resource_id}},{resource_id:id(7),object_type:"JournalLine",attributes:{journal_id:id(6)}},{resource_id:id(8),object_type:"JournalLine",attributes:{journal_id:id(6)}}]}},{coordinate:"Sheet!A3",state:"EXCLUDED",blockers:[{code:"MISSING_SOURCE_AMOUNT"}]}]};
 const outcomes={contract:"journal-production-dispositions/1",request_id:scope.requestId,company_id:scope.companyId,invocation_id:scope.invocationId,attempt_receipt_hash:attempt.receipt_hash,source_sha256:attempt.source_sha256,binding,source_exclusions:[{coordinate:"Sheet!A3",blockers:attempt.rows[1].blockers}],selection_count:1,items:[{coordinate:"Sheet!A2",state:"PUBLISHED",prepared_state:"ELIGIBLE_FOR_REVIEW",prepared_blockers:[],blockers:[],proposal_id:scope.proposalId,review:{decision:"APPROVED",submitted_by:"fixture maker",reviewed_by:"fixture checker",rationale:"Fixture only",recorded_at:"2026-09-08T12:00:00Z"},publication:{journal:pin(6),lines:[pin(7),pin(8)]}}],counts:{PUBLISHED:1},financial_totals:null,current_use_authorized:false,business_effect_authorized:false,observation_started_at:"2026-09-08T12:00:00.123456Z",observed_at:"2026-09-08T12:00:01.123456Z",consistency:"PER_ITEM_READ_OBSERVATION",receipt_hash:"e".repeat(64)};
 return {attempt,outcomes};
}
test("immutable attempt and exact publication conserve scope, coordinates and original exclusions",()=>{const {attempt,outcomes}=fixture();assertJournalAttempt(attempt,scope);assertJournalDispositions(outcomes,attempt);assert.equal(outcomes.financial_totals,null);});
test("wrong company, invocation, request, proposal and stale immutable source are refused",()=>{
 const {attempt}=fixture();for(const field of Object.keys(scope))assert.throws(()=>assertJournalAttempt(attempt,{...scope,[field]:id(99)}));
 for(const change of [{receipt_hash:"f".repeat(64)},{source_sha256:"f".repeat(64)},{source_receipt_hash:"f".repeat(64)},{binding:{...binding,version_id:id(99)}}])assert.throws(()=>assertJournalAttempt({...attempt,...change},scope,attempt));
 const changed=structuredClone(attempt);changed.rows[0].proposal.mutations[0].attributes.legal_entity_id=id(99);assert.throws(()=>assertJournalAttempt(changed,scope));
});
test("approved without exact journal and both distinct line versions never becomes published",()=>{
 const {attempt,outcomes}=fixture();for(const publication of [null,{journal:pin(99),lines:[pin(7),pin(8)]},{journal:pin(6),lines:[pin(7)]},{journal:pin(6),lines:[pin(7),pin(7)]},{journal:pin(6),lines:[pin(7),{...pin(8),content_hash:"missing"}]}])assert.throws(()=>assertJournalDispositions({...outcomes,items:[{...outcomes.items[0],publication}]},attempt));
 assertJournalDispositions({...outcomes,items:[{...outcomes.items[0],state:"UNAVAILABLE",publication:null}],counts:{UNAVAILABLE:1}},attempt);
});
test("pending, rejected, blocked, excluded, unavailable and not submitted stay distinct",()=>{
 for(const state of ["PENDING_REVIEW","REJECTED","BLOCKED","EXCLUDED","UNAVAILABLE","NOT_SUBMITTED"]){const {attempt,outcomes}=fixture();const item=outcomes.items[0];item.state=state;item.publication=null;item.review=state==="PENDING_REVIEW"?{...item.review,decision:null}:state==="REJECTED"?{...item.review,decision:"REJECTED"}:null;outcomes.counts={[state]:1};if(state==="EXCLUDED"){attempt.rows[0].state="EXCLUDED";delete attempt.rows[0].proposal;item.proposal_id=null;item.prepared_state="EXCLUDED";outcomes.source_exclusions.unshift({coordinate:item.coordinate,blockers:[]});}assertJournalDispositions(outcomes,attempt);}
});
test("outcomes cannot change original selection, exclusions, receipt or count basis",()=>{
 const {attempt,outcomes}=fixture();for(const change of [{attempt_receipt_hash:"f".repeat(64)},{source_sha256:"f".repeat(64)},{company_id:id(99)},{source_exclusions:[]},{items:[]},{selection_count:2},{counts:{PUBLISHED:2}},{financial_totals:{amount:"1.00"}},{business_effect_authorized:true},{items:[{...outcomes.items[0],coordinate:"Sheet!A9"}]}])assert.throws(()=>assertJournalDispositions({...outcomes,...change},attempt));
});
test("read interval retains microseconds and refuses an atomic snapshot claim",()=>{
 const {attempt,outcomes}=fixture();assertJournalDispositions({...outcomes,observed_at:"2026-09-08T16:00:01.123456+04:00"},attempt);
 for(const change of [{consistency:"ATOMIC_BATCH_SNAPSHOT"},{observed_at:"2026-09-08T12:00:00.123455Z"},{observation_started_at:"2026-09-08T12:00:00"}])assert.throws(()=>assertJournalDispositions({...outcomes,...change},attempt));
});
test("attempt duplicates and a missing original selected proposal refuse before outcome load",()=>{
 const {attempt}=fixture();assert.throws(()=>assertJournalAttempt({...attempt,rows:[...attempt.rows,attempt.rows[0]]},scope));assert.throws(()=>assertJournalAttempt({...attempt,request:{...attempt.request,coordinates:["Sheet!A3"]}},scope));
});
