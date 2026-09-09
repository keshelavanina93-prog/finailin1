import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";
import {loadTypeScript} from "./load-typescript.mjs";
const {assertFinanceDiscovery,financeLinkedSelection}=await loadTypeScript(new URL("../app/finance-discovery-state.ts",import.meta.url));
// Real discover() serialization from C ba47bb1 with an isolated synthetic repository.
// This is contract evidence, never native runtime or authentic source acceptance.
const fixture=JSON.parse(await readFile(new URL("./fixtures/company-financial-results-synthetic.json",import.meta.url),"utf8"));
const wire=fixture.response,company=wire.company.resource_id;
test("actual producer serialization passes the consumer without a profile allowlist",()=>{
 assertFinanceDiscovery(wire,company);
 const changed=structuredClone(wire);changed.sources[0].scope.attributes.source_profile="another-reviewed-profile";
 assertFinanceDiscovery(changed,company);
});
test("historical results do not require today's source, capability or binding",()=>{
 assert.ok(wire.results.length);
 assertFinanceDiscovery({...wire,sources:[],capabilities:[]},company);
});
test("wrong company, malformed pins, changed snapshot and elevated authority refuse",()=>{
 assert.throws(()=>assertFinanceDiscovery(wire,wire.company.version_id));
 for(const mutate of [v=>v.current_use_authorized=true,v=>v.company.content_hash="missing",v=>v.capabilities[0].accounting_binding.version_id=v.company.version_id,v=>v.results[0].source.company_id=v.company.version_id,v=>v.results[0].receipt_hash="invalid",v=>v.results[0].business_effect_authorized=true,v=>v.results.push(v.results[0])]){
  const changed=structuredClone(wire);mutate(changed);assert.throws(()=>assertFinanceDiscovery(changed,company));
 }
 assert.throws(()=>assertFinanceDiscovery(wire,company,{valid_at:"2000-01-01T00:00:00Z",known_at:wire.known_at}));
});
test("both discovery cursors are independently retained and checked",()=>{
 assertFinanceDiscovery({...wire,next_function_cursor:company,next_invocation_cursor:wire.company.version_id},company);
 assert.throws(()=>assertFinanceDiscovery({...wire,next_invocation_cursor:"offset:50"},company));
});
test("pre-projection result history restores an exact reference without a current catalog",()=>{
 const result=wire.results[0],url=new URL("https://g8.example/");
 url.searchParams.set("finance_result",JSON.stringify({companyId:company,invocationId:result.invocation_id,receiptHash:result.receipt_hash}));
 assert.deepEqual(financeLinkedSelection(url,company,null),{invocationId:result.invocation_id,receiptHash:result.receipt_hash});
 assert.throws(()=>financeLinkedSelection(url,wire.company.version_id,null));
 url.searchParams.set("finance_analysis_view","invalid");
 assert.throws(()=>financeLinkedSelection(url,company,null));
});
test("initial Finance handoff preserves original invocation and refuses another company",()=>{
 const result=wire.results[0],initial={companyId:company,invocationId:result.invocation_id,scopeId:"retained",documentId:"retained"};
 assert.deepEqual(financeLinkedSelection(new URL("https://g8.example/"),company,initial),{invocationId:result.invocation_id});
 assert.throws(()=>financeLinkedSelection(new URL("https://g8.example/"),wire.company.version_id,initial));
});
test("saved worksheet revision and pre-projection receipt must agree",()=>{
 const r=wire.results[0],url=new URL("https://g8.example/");
 const view={version:1,request:{company_id:company,invocation_id:r.invocation_id,descriptor_sha256:"a".repeat(64),filters:[],contributor_index:0},receipt_hash:r.receipt_hash,valid_at:r.valid_at,known_at:r.known_at};
 url.searchParams.set("finance_analysis_view",JSON.stringify(view));
 url.searchParams.set("finance_result",JSON.stringify({companyId:company,invocationId:r.invocation_id,receiptHash:r.receipt_hash}));
 assert.equal(financeLinkedSelection(url,company,null).receiptHash,r.receipt_hash);
 url.searchParams.set("finance_result",JSON.stringify({companyId:company,invocationId:r.invocation_id,receiptHash:"0".repeat(64)}));
 assert.throws(()=>financeLinkedSelection(url,company,null));
});
