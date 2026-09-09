import test from "node:test";
import assert from "node:assert/strict";
import {loadTypeScript} from "./load-typescript.mjs";
const pins=await loadTypeScript(new URL("../app/company-home-pins.ts",import.meta.url));
const {parseHomeAnalysisReferences,homeAnalysisRequest,assertHomeRevision}=await loadTypeScript(new URL("../app/company-home-revision.ts",import.meta.url));
const id=n=>`00000000-0000-4000-8000-${String(n).padStart(12,"0")}`;
const revision=()=>({descriptorSha256:"a".repeat(64),receiptHash:"b".repeat(64),validAt:"2025-01-01T00:00:00.123456Z",knownAt:"2026-09-08T01:02:03.654321Z"});
function storage(t){
 const store=new Map(),original=globalThis.localStorage;
 globalThis.localStorage={getItem:key=>store.get(key)??null,setItem:(key,value)=>store.set(key,value),removeItem:key=>store.delete(key)};
 t.after(()=>{globalThis.localStorage=original;});return store;
}
test("new exact pins retain only revision metadata, preserve legacy references and keep the old ID API",async t=>{
 const store=storage(t);
 await pins.pinHomeAnalysis("private-token",{companyId:id(1),invocationId:id(2)});
 const candidate={companyId:id(1),invocationId:id(3),revision:revision(),rows:[{amount:"must not store"}],token:"must not store"};
 await pins.pinHomeAnalysis("private-token",candidate);
 assert.deepEqual(await pins.homeAnalysisPins("private-token",id(1)),[id(3),id(2)]);
 assert.deepEqual(await pins.homeAnalysisReferences("private-token",id(1)),[
  {kind:"EXACT",invocationId:id(3),revision:revision()}, {kind:"LEGACY",invocationId:id(2)},
 ]);
 const [key,value]=[...store.entries()][0];
 assert.match(key,/^g8-home-pins-v1:[a-f0-9]{64}:/);
 assert.ok(!key.includes("private-token")&&!value.includes("must not store"));
 assert.deepEqual(JSON.parse(value),[{invocationId:id(3),revision:revision()},id(2)]);
 assert.deepEqual(await pins.homeAnalysisReferences("other-token",id(1)),[]);
 assert.deepEqual(await pins.homeAnalysisReferences("private-token",id(99)),[]);
});
test("repinning an exact reference upgrades its revision while legacy calls cannot erase it",async t=>{
 storage(t);
 await pins.pinHomeAnalysis("a",{companyId:id(1),invocationId:id(2),revision:revision()});
 await pins.pinHomeAnalysis("a",{companyId:id(1),invocationId:id(2)});
 assert.equal((await pins.homeAnalysisReferences("a",id(1)))[0].kind,"EXACT");
 const updated={...revision(),descriptorSha256:"c".repeat(64),knownAt:"2026-09-08T01:02:03.654322Z"};
 await pins.pinHomeAnalysis("a",{companyId:id(1),invocationId:id(2),revision:updated});
 assert.deepEqual(await pins.homeAnalysisReferences("a",id(1)),[{kind:"EXACT",invocationId:id(2),revision:updated}]);
});
test("malformed exact references never downgrade to legacy, including partial metadata and mixed duplicate identities",async t=>{
 const store=storage(t);
 await pins.pinHomeAnalysis("a",{companyId:id(1),invocationId:id(2)});
 const key=[...store.keys()][0];
 const malformed=[{invocationId:id(2)}, {invocationId:id(2),revision:null},
  {invocationId:id(2),revision:{...revision(),extra:"row"}},
  {invocationId:id(2),revision:{...revision(),descriptorSha256:"invalid"}},
  {invocationId:id(2),revision:{...revision(),receiptHash:null}},
  {invocationId:id(2),revision:{...revision(),validAt:"2025-01-01T00:00:00"}},
  {invocationId:id(2),revision:{...revision(),knownAt:"2026-02-30T00:00:00Z"}}];
 for(const value of malformed){
  store.set(key,JSON.stringify([value]));
  await assert.rejects(()=>pins.homeAnalysisReferences("a",id(1)),/invalid/);
  await assert.rejects(()=>pins.homeAnalysisPins("a",id(1)),/invalid/);
  await assert.rejects(()=>pins.pinHomeAnalysis("a",{companyId:id(1),invocationId:id(4),revision:revision()}),/invalid/);
 }
 assert.throws(()=>parseHomeAnalysisReferences([id(2),{invocationId:id(2),revision:revision()}]),/invalid/);
 await pins.clearHomeAnalysisPins("a",id(1));
 assert.deepEqual(await pins.homeAnalysisReferences("a",id(1)),[]);
});
test("exact Home requests pin descriptor and reject receipt or microsecond time drift; legacy remains explicitly classified",()=>{
 const exact=parseHomeAnalysisReferences([{invocationId:id(2),revision:revision()}])[0];
 assert.deepEqual(homeAnalysisRequest(exact,id(1)),{company_id:id(1),invocation_id:id(2),descriptor_sha256:"a".repeat(64)});
 const projection={descriptor_sha256:"a".repeat(64),descriptor:{receipt_hash:"b".repeat(64),valid_at:revision().validAt,known_at:revision().knownAt}};
 assert.doesNotThrow(()=>assertHomeRevision(projection,exact));
 for(const changed of [
  {...projection,descriptor_sha256:"c".repeat(64)},
  {...projection,descriptor:{...projection.descriptor,receipt_hash:"c".repeat(64)}},
  {...projection,descriptor:{...projection.descriptor,valid_at:"2025-01-01T00:00:00.123457Z"}},
  {...projection,descriptor:{...projection.descriptor,known_at:"2026-09-08T01:02:03.654322Z"}},
 ])assert.throws(()=>assertHomeRevision(changed,exact),/pinned analysis revision/);
 const legacy=parseHomeAnalysisReferences([id(2)])[0];
 assert.equal(legacy.kind,"LEGACY");
 assert.deepEqual(homeAnalysisRequest(legacy,id(1)),{company_id:id(1),invocation_id:id(2)});
});
test("revision intent is cloned before key derivation; invalid new metadata fails before storage mutation",async t=>{
 const store=storage(t),original=Object.getOwnPropertyDescriptor(globalThis,"crypto"),actual=crypto;
 const digest=await actual.subtle.digest("SHA-256",new TextEncoder().encode("a"));
 let finish;
 Object.defineProperty(globalThis,"crypto",{configurable:true,value:{subtle:{digest:()=>new Promise(resolve=>{finish=resolve;})}}});
 t.after(()=>Object.defineProperty(globalThis,"crypto",original));
 const requested=revision(),pending=pins.pinHomeAnalysis("a",{companyId:id(1),invocationId:id(2),revision:requested});
 requested.descriptorSha256="c".repeat(64);requested.knownAt="2027-01-01T00:00:00Z";
 finish(digest);await pending;
 assert.deepEqual(JSON.parse([...store.values()][0])[0].revision,revision());
 const before=[...store.entries()];
 await assert.rejects(()=>pins.pinHomeAnalysis("a",{companyId:id(1),invocationId:id(2),revision:null}),/invalid/);
 assert.deepEqual([...store.entries()],before);
});

test("original and journal snapshots coexist without identity collapse or legacy journal substitution",async t=>{
 const store=storage(t),journalSnapshot="2026-09-08T01:02:03.123456Z",base={companyId:id(1),invocationId:id(2),revision:revision()};
 await pins.pinHomeAnalysis("a",base);
 await pins.pinHomeAnalysis("a",{...base,journalSnapshot});
 await pins.pinHomeAnalysis("a",{...base,journalSnapshot:"2026-09-08T05:02:03.123456+04:00"});
 const refs=await pins.homeAnalysisReferences("a",id(1));
 assert.equal(refs.length,2);assert.equal(refs[0].journalSnapshot,journalSnapshot);assert.equal(refs[1].journalSnapshot,undefined);
 assert.deepEqual(await pins.homeAnalysisPins("a",id(1)),[id(2)]);
 const before=JSON.stringify([...store]);
 await assert.rejects(()=>pins.pinHomeAnalysis("a",{companyId:id(1),invocationId:id(2),journalSnapshot}));
 await assert.rejects(()=>pins.pinHomeAnalysis("a",{...base,journalSnapshot:"2026-02-30T00:00:00Z"}));
 assert.equal(JSON.stringify([...store]),before);
 const p={descriptor_sha256:base.revision.descriptorSha256,descriptor:{contract:"semantic-analysis/2",receipt_hash:base.revision.receiptHash,valid_at:base.revision.validAt,known_at:base.revision.knownAt,coverage:[{label:"Snapshot",value:journalSnapshot}]}};
 assert.doesNotThrow(()=>assertHomeRevision(p,refs[0]));
 p.descriptor.coverage[0].value="2026-09-08T01:02:03.123457Z";
 assert.throws(()=>assertHomeRevision(p,refs[0]));
 assert.throws(()=>parseHomeAnalysisReferences([{invocationId:id(2),revision:revision(),journalSnapshot:"2026-02-30T00:00:00Z"}]));
});

test("financial placement selects journal transport references before fetch; source and legacy stay supporting references",async()=>{
 const {homeReferencesForGroup}=await loadTypeScript(new URL("../app/company-home-revision.ts",import.meta.url));
 const refs=parseHomeAnalysisReferences([id(1),{invocationId:id(2),revision:revision()},{invocationId:id(2),revision:revision(),journalSnapshot:"2026-09-08T00:00:00Z"}]);
 assert.deepEqual(homeReferencesForGroup(refs),refs);
 assert.deepEqual(homeReferencesForGroup(refs,"sources"),refs.slice(0,2));
 assert.deepEqual(homeReferencesForGroup(refs,"journals"),refs.slice(2));
});
