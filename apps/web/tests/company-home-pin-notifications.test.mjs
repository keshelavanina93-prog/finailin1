import {loadTypeScript} from "./load-typescript.mjs";
const pins=await loadTypeScript(new URL("../app/company-home-pins.ts",import.meta.url));
import test from "node:test";
import assert from "node:assert/strict";
const id=n=>`00000000-0000-4000-8000-${String(n).padStart(12,"0")}`;
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(t){
 const store=new Map();const originalStorage=globalThis.localStorage,originalWindow=globalThis.window;
 globalThis.localStorage={getItem:key=>store.get(key)??null,setItem:(key,value)=>store.set(key,value),removeItem:key=>store.delete(key)};
 class Surface extends EventTarget{
  count=0;
  addEventListener(...args){this.count++;super.addEventListener(...args);}
  removeEventListener(...args){this.count--;super.removeEventListener(...args);}
 }
 globalThis.window=new Surface();
 t.after(()=>{globalThis.localStorage=originalStorage;globalThis.window=originalWindow;});
 const events=[];
 async function subscribe(token,company){
  let count=0,ready;
  const first=new Promise(resolve=>{ready=resolve;});
  const stop=pins.subscribeHomeAnalysisPins(token,company,(...args)=>{assert.deepEqual(args,[]);count++;events.push([token,company]);ready();},()=>assert.fail("Unexpected subscription error"));
  t.after(stop);await first;
  return {stop,count:()=>count};
 }
 return {store,events,subscribe};
}
test("same-document pin and clear notify only matching hashed identity/company and no-op pin stays quiet",async t=>{
 const {store,subscribe}=fixture(t);
 const first=await subscribe("private-token-a",id(1)),other=await subscribe("private-token-b",id(1)),company=await subscribe("private-token-a",id(2));
 await pins.pinHomeAnalysis("private-token-a",{companyId:id(1),invocationId:id(10)});
 assert.deepEqual([first.count(),other.count(),company.count()],[2,1,1]);
 await pins.pinHomeAnalysis("private-token-a",{companyId:id(1),invocationId:id(10)});
 assert.equal(first.count(),2);
 assert.match([...store.keys()][0],/^g8-home-pins-v1:[a-f0-9]{64}:/);
 assert.ok([...store.keys()].every(key=>!key.includes("private-token")));
 assert.deepEqual(JSON.parse([...store.values()][0]),[id(10)]);
 await pins.clearHomeAnalysisPins("private-token-a",id(1));
 assert.deepEqual([first.count(),other.count(),company.count()],[3,1,1]);
 assert.deepEqual(await pins.homeAnalysisPins("private-token-a",id(1)),[]);
 first.stop();first.stop();
 const replacement=await subscribe("private-token-a",id(1));first.stop();
 await pins.pinHomeAnalysis("private-token-a",{companyId:id(1),invocationId:id(11)});
 assert.equal(first.count(),3);
 assert.equal(replacement.count(),2);
});
test("cross-document storage changes require localStorage and the exact key; global clear refreshes mounted scopes",async t=>{
 const {store,subscribe}=fixture(t);
 const a=await subscribe("a",id(1)),b=await subscribe("b",id(1));
 await pins.pinHomeAnalysis("a",{companyId:id(1),invocationId:id(10)});
 const ownKey=[...store.keys()][0];
 const dispatch=(key,storageArea=localStorage)=>window.dispatchEvent(Object.assign(new Event("storage"),{key,storageArea}));
 dispatch("unrelated");dispatch(ownKey,{});
 assert.deepEqual([a.count(),b.count()],[2,1]);
 dispatch(ownKey);
 assert.deepEqual([a.count(),b.count()],[3,1]);
 dispatch(null);
 assert.deepEqual([a.count(),b.count()],[4,2]);
 a.stop();b.stop();
 dispatch(ownKey);dispatch(null);
 assert.deepEqual([a.count(),b.count()],[4,2]);
});
test("unmount during key derivation registers no listeners or callbacks, including late rejection",async t=>{
 fixture(t);
 const descriptor=Object.getOwnPropertyDescriptor(globalThis,"crypto");
 const waiting=[];
 Object.defineProperty(globalThis,"crypto",{configurable:true,value:{subtle:{digest:()=>new Promise((resolve,reject)=>waiting.push({resolve,reject}))}}});
 t.after(()=>Object.defineProperty(globalThis,"crypto",descriptor));
 let changed=0,errors=0;
 const stop=pins.subscribeHomeAnalysisPins("a",id(1),()=>changed++,()=>errors++);
 stop();waiting[0].resolve(new Uint8Array(32).buffer);await tick();
 const otherStop=pins.subscribeHomeAnalysisPins("b",id(1),()=>changed++,()=>errors++);
 otherStop();waiting[1].reject(Error("Unavailable digest"));await tick();
 assert.equal(changed,0);assert.equal(errors,0);assert.equal(window.count,0);
});
test("initial refresh covers changes before subscription key is ready and pin captures intent before async digest",async t=>{
 const {store}=fixture(t);
 const descriptor=Object.getOwnPropertyDescriptor(globalThis,"crypto"),actual=crypto;
 const digest=await actual.subtle.digest("SHA-256",new TextEncoder().encode("a"));
 const waiting=[];
 Object.defineProperty(globalThis,"crypto",{configurable:true,value:{subtle:{digest:()=>new Promise(resolve=>waiting.push(resolve))}}});
 t.after(()=>Object.defineProperty(globalThis,"crypto",descriptor));
 let count=0;
 const stop=pins.subscribeHomeAnalysisPins("a",id(1),()=>count++,()=>assert.fail("Unexpected error"));t.after(stop);
 const intent={companyId:id(1),invocationId:id(10)};
 const writing=pins.pinHomeAnalysis("a",intent);
 Object.assign(intent,{companyId:id(2),invocationId:id(20)});
 waiting[1](digest);await writing;assert.equal(count,0);
 waiting[0](digest);await tick();
 assert.equal(count,1);
 assert.ok([...store.keys()][0].endsWith(id(1)));
 assert.deepEqual(JSON.parse([...store.values()][0]),[id(10)]);
});
test("failed writes emit nothing and key failure reports once without listeners",async t=>{
 const {subscribe}=fixture(t);const sub=await subscribe("a",id(1));
 localStorage.setItem=()=>{throw Error("Storage blocked");};
 await assert.rejects(()=>pins.pinHomeAnalysis("a",{companyId:id(1),invocationId:id(10)}));
 assert.equal(sub.count(),1);
 let errors=0;
 const stop=pins.subscribeHomeAnalysisPins("a","invalid",()=>assert.fail("No invalid scope"),()=>errors++);t.after(stop);
 await tick();assert.equal(errors,1);
});
