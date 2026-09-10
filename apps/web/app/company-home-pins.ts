import {journalSnapshot,projectionIdentity} from "./analysis-projection-identity";
import {encodedHomeReferences,homeRevision,parseHomeAnalysisReferences,type HomeAnalysisRevision,type HomeAnalysisReference} from "./company-home-revision";
export type HomeAnalysisPin={companyId:string;invocationId:string;journalSnapshot?:string;revision?:HomeAnalysisRevision};
const uuid=/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const subscribers=new Map<string,Set<()=>void>>();
async function key(token:string,companyId:string){
 if(!uuid.test(companyId))throw Error("An exact company is required.");
 const digest=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(token));
 return `g8-home-pins-v1:${Array.from(new Uint8Array(digest),v=>v.toString(16).padStart(2,"0")).join("")}:${companyId}`;
}
function read(storageKey:string):HomeAnalysisReference[]{
 const stored=localStorage.getItem(storageKey)??"[]";
 if(stored.length>10000)throw Error("Saved Home references exceed the supported metadata bound.");
 return parseHomeAnalysisReferences(JSON.parse(stored));
}
export async function homeAnalysisReferences(token:string,companyId:string):Promise<HomeAnalysisReference[]>{return read(await key(token,companyId));}
export async function homeAnalysisPins(token:string,companyId:string):Promise<string[]>{return (await homeAnalysisReferences(token,companyId)).filter(ref=>ref.journalSnapshot===undefined).map(ref=>ref.invocationId);}
function notify(storageKey:string){for(const callback of subscribers.get(storageKey)??[])callback();}

/** A subscription owns only its hashed identity/company key, never retained analysis values. */
export function subscribeHomeAnalysisPins(token:string,companyId:string,onChange:()=>void,onError:()=>void):()=>void{
 let disposed=false,release=()=>{};
 void key(token,companyId).then(storageKey=>{
  if(disposed)return;
  const callbacks=subscribers.get(storageKey)??new Set<()=>void>();
  callbacks.add(onChange);subscribers.set(storageKey,callbacks);
  const changed=(event:StorageEvent)=>{
   if(!disposed&&event.storageArea===localStorage&&(event.key===storageKey||event.key===null))onChange();
  };
  if(typeof window!=="undefined")window.addEventListener("storage",changed);
  release=()=>{callbacks.delete(onChange);if(!callbacks.size)subscribers.delete(storageKey);if(typeof window!=="undefined")window.removeEventListener("storage",changed);};
  // The initial read starts after registration, covering writes during asynchronous key derivation.
  onChange();
 }).catch(()=>{if(!disposed)onError();});
 return ()=>{if(disposed)return;disposed=true;release();};
}
export async function pinHomeAnalysis(token:string,pin:HomeAnalysisPin){
 const {companyId,invocationId}=pin;
 if(!uuid.test(invocationId))throw Error("An exact retained analysis is required.");
 const revision="revision" in pin?homeRevision(pin.revision):null;
 const snapshot="journalSnapshot" in pin?journalSnapshot(pin.journalSnapshot):undefined;
 if(snapshot!==undefined&&!revision)throw Error("Accepted journal Home references require an exact revision.");
 const identity=projectionIdentity(invocationId,snapshot);
 const storageKey=await key(token,companyId),previous=read(storageKey);
 const reference:HomeAnalysisReference=revision?{kind:"EXACT",invocationId,revision,...(snapshot===undefined?{}:{journalSnapshot:snapshot})}:
  previous.find(ref=>projectionIdentity(ref.invocationId,ref.journalSnapshot)===identity)??{kind:"LEGACY",invocationId};
 if(previous.length>=6&&!previous.some(ref=>projectionIdentity(ref.invocationId,ref.journalSnapshot)===identity))throw Error("Home holds six analyses; remove one reference first.");
 const value=encodedHomeReferences([reference,...previous.filter(ref=>projectionIdentity(ref.invocationId,ref.journalSnapshot)!==identity)]);
 if(value===encodedHomeReferences(previous))return;
 localStorage.setItem(storageKey,value);notify(storageKey);
}
export async function clearHomeAnalysisPins(token:string,companyId:string){const storageKey=await key(token,companyId);localStorage.removeItem(storageKey);notify(storageKey);}

/** Remove only the reference the operator saw; a later repin must be reviewed again. */
export async function removeHomeAnalysis(token:string,companyId:string,expected:HomeAnalysisReference):Promise<void>{
 if(!expected||!["LEGACY","EXACT"].includes(expected.kind)||expected.kind==="LEGACY"&&Object.keys(expected).some(field=>!["kind","invocationId"].includes(field))||expected.kind==="EXACT"&&Object.keys(expected).some(field=>!["kind","invocationId","revision","journalSnapshot"].includes(field)))throw Error("The selected Home reference is invalid. Refresh Home before removing it.");
 if("journalSnapshot" in expected)journalSnapshot(expected.journalSnapshot);
 const normalized=parseHomeAnalysisReferences(JSON.parse(encodedHomeReferences([expected])))[0];
 const identity=projectionIdentity(normalized.invocationId,normalized.journalSnapshot);
 const storageKey=await key(token,companyId),previous=read(storageKey);
 const index=previous.findIndex(reference=>projectionIdentity(reference.invocationId,reference.journalSnapshot)===identity);
 if(index<0||encodedHomeReferences([previous[index]])!==encodedHomeReferences([normalized]))throw Error("This Home reference changed or was already removed. Refresh the saved references before removing it.");
 const next=previous.filter((_,position)=>position!==index);
 if(next.length)localStorage.setItem(storageKey,encodedHomeReferences(next));
 else localStorage.removeItem(storageKey);
 notify(storageKey);
}
