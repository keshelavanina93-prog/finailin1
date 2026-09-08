import test from "node:test";
import assert from "node:assert/strict";
import {loadTypeScript} from "./load-typescript.mjs";
const pins=await loadTypeScript(new URL("../app/company-home-pins.ts",import.meta.url));
const id=n=>`00000000-0000-4000-8000-${String(n).padStart(12,"0")}`;
const company=id(100),at="2026-09-08T00:00:00.123456Z",later="2026-09-08T00:00:00.123457Z";
const revision=(patch={})=>({descriptorSha256:"a".repeat(64),receiptHash:"b".repeat(64),validAt:at,knownAt:at,...patch});
function fixture(t){
 const original=globalThis.localStorage,store=new Map();let writes=0;
 globalThis.localStorage={getItem:key=>store.get(key)??null,setItem:(key,value)=>{writes++;store.set(key,value);},removeItem:key=>{writes++;store.delete(key);}};
 t.after(()=>{globalThis.localStorage=original;});return {store,writes:()=>writes};
}
async function pin(n,options={}){await pins.pinHomeAnalysis("actor",{companyId:company,invocationId:id(n),revision:revision(),...options});}
async function references(){return pins.homeAnalysisReferences("actor",company);}

test("remove one exact source preserves other pins and order, including its journal snapshots",async t=>{
 fixture(t);await pin(1);await pin(2);await pin(1,{journalSnapshot:at});await pin(1,{journalSnapshot:later});
 const before=await references(),source=before.find(ref=>ref.invocationId===id(1)&&ref.journalSnapshot===undefined);
 await pins.removeHomeAnalysis("actor",company,source);
 assert.deepEqual(await references(),before.filter(ref=>ref!==source));
 const snapshot=(await references()).find(ref=>ref.journalSnapshot===at);
 await pins.removeHomeAnalysis("actor",company,snapshot);
 assert.deepEqual(await references(),before.filter(ref=>ref!==source&&ref.journalSnapshot!==at));
});

test("every exact revision change refuses a stale remove and leaves newly pinned reference intact",async t=>{
 const state=fixture(t);
 for(const patch of [{descriptorSha256:"c".repeat(64)},{receiptHash:"d".repeat(64)},{validAt:later},{knownAt:later}]){
  await pin(1);const previous=(await references())[0];
  await pin(1,{revision:revision(patch)});const current=await references(),writes=state.writes();
  await assert.rejects(()=>pins.removeHomeAnalysis("actor",company,previous),/changed/);
  assert.deepEqual(await references(),current);assert.equal(state.writes(),writes);
 }
});

test("legacy reference cannot remove a subsequently exact repin",async t=>{
 fixture(t);await pins.pinHomeAnalysis("actor",{companyId:company,invocationId:id(1)});
 const legacy=(await references())[0];await pin(1);
 await assert.rejects(()=>pins.removeHomeAnalysis("actor",company,legacy),/changed/);
 assert.equal((await references())[0].kind,"EXACT");
});

test("token and company storage isolation survive same-invocation removal",async t=>{
 fixture(t);await pin(1);
 await pins.pinHomeAnalysis("other",{companyId:company,invocationId:id(1),revision:revision()});
 await pins.pinHomeAnalysis("actor",{companyId:id(101),invocationId:id(1),revision:revision()});
 const expected=(await references())[0];
 await pins.removeHomeAnalysis("actor",company,expected);
 assert.deepEqual(await references(),[]);
 assert.equal((await pins.homeAnalysisReferences("other",company)).length,1);
 assert.equal((await pins.homeAnalysisReferences("actor",id(101))).length,1);
 await assert.rejects(()=>pins.removeHomeAnalysis("actor",company,expected),/removed/);
});

test("successful removal notifies only the matching identity and company, failures stay quiet",async t=>{
 fixture(t);const counts=[0,0,0];
 for(const [index,token,owner] of [[0,"actor",company],[1,"other",company],[2,"actor",id(101)]]){
  let ready;const first=new Promise(resolve=>{ready=resolve;});
  const stop=pins.subscribeHomeAnalysisPins(token,owner,()=>{counts[index]++;ready();},()=>assert.fail("Subscription unavailable"));t.after(stop);await first;
 }
 await pin(1);const expected=(await references())[0];assert.deepEqual(counts,[2,1,1]);
 await pins.removeHomeAnalysis("actor",company,expected);assert.deepEqual(counts,[3,1,1]);
 await assert.rejects(()=>pins.removeHomeAnalysis("actor",company,expected));assert.deepEqual(counts,[3,1,1]);
});

test("malformed reference or device storage never triggers a broad clear",async t=>{
 const state=fixture(t);await pin(1);const expected=(await references())[0];const writes=state.writes();
 for(const value of [null,{...expected,journalSnapshot:undefined},{...expected,revision:{...expected.revision,receiptHash:"bad"}},{...expected,amount:10},{kind:"LEGACY",invocationId:id(1),journalSnapshot:at}])await assert.rejects(()=>pins.removeHomeAnalysis("actor",company,value));
 assert.equal(state.writes(),writes);
 state.store.set([...state.store.keys()][0],"invalid");
 await assert.rejects(()=>pins.removeHomeAnalysis("actor",company,expected));assert.equal(state.writes(),writes);
});

test("write failure retains the exact reference and emits no removal",async t=>{
 fixture(t);await pin(1);const expected=(await references())[0];
 localStorage.removeItem=()=>{throw Error("Device unavailable");};
 await assert.rejects(()=>pins.removeHomeAnalysis("actor",company,expected),/Device unavailable/);
 assert.deepEqual(await references(),[expected]);
});

test("removal captures its exact expected revision before asynchronous identity hashing",async t=>{
 fixture(t);await pin(1);const expected=(await references())[0];
 const cryptoDescriptor=Object.getOwnPropertyDescriptor(globalThis,"crypto"),actual=crypto;
 const digest=await actual.subtle.digest("SHA-256",new TextEncoder().encode("actor"));let finish;
 Object.defineProperty(globalThis,"crypto",{configurable:true,value:{subtle:{digest:()=>new Promise(resolve=>{finish=resolve;})}}});
 t.after(()=>Object.defineProperty(globalThis,"crypto",cryptoDescriptor));
 const removing=pins.removeHomeAnalysis("actor",company,expected);
 expected.revision.receiptHash="c".repeat(64);expected.invocationId=id(2);
 finish(digest);await removing;
 Object.defineProperty(globalThis,"crypto",cryptoDescriptor);
 assert.deepEqual(await references(),[]);
});


test("full Home refuses new identities without writes or notification and allows exact repinning",async t=>{
 const state=fixture(t);let count=0,ready;
 const first=new Promise(resolve=>{ready=resolve;});
 const stop=pins.subscribeHomeAnalysisPins("actor",company,()=>{count++;ready();},()=>assert.fail("Unexpected storage error"));t.after(stop);await first;
 for(let index=1;index<=6;index++)await pin(index);
 const before=await references(),writes=state.writes(),notifications=count;
 await assert.rejects(()=>pin(7),/Home holds six analyses; remove one reference first/);
 await assert.rejects(()=>pin(1,{journalSnapshot:at}),/Home holds six analyses/);
 assert.deepEqual(await references(),before);assert.equal(state.writes(),writes);assert.equal(count,notifications);
 await pin(1,{revision:revision({receiptHash:"c".repeat(64)})});
 const repinned=await references();assert.equal(repinned.length,6);assert.equal(repinned[0].invocationId,id(1));
 assert.equal(repinned[0].revision.receiptHash,"c".repeat(64));
 assert.deepEqual(repinned.slice(1),before.filter(ref=>ref.invocationId!==id(1)));assert.equal(count,notifications+1);
});
