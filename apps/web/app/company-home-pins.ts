export type HomeAnalysisPin={companyId:string;invocationId:string};
const uuid=/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const subscribers=new Map<string,Set<()=>void>>();
async function key(token:string,companyId:string){
 if(!uuid.test(companyId))throw Error("An exact company is required.");
 const digest=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(token));
 return `g8-home-pins-v1:${Array.from(new Uint8Array(digest),v=>v.toString(16).padStart(2,"0")).join("")}:${companyId}`;
}
function read(storageKey:string):string[]{
 const value:unknown=JSON.parse(localStorage.getItem(storageKey)??"[]");
 if(!Array.isArray(value)||value.length>6||value.some(id=>typeof id!=="string"||!uuid.test(id))||new Set(value).size!==value.length)throw Error("Saved Home references are invalid. Clear them and pin the retained analyses again.");
 return value;
}
export async function homeAnalysisPins(token:string,companyId:string):Promise<string[]>{return read(await key(token,companyId));}
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
 const storageKey=await key(token,companyId),previous=read(storageKey);
 const value=JSON.stringify([invocationId,...previous.filter(id=>id!==invocationId)].slice(0,6));
 if(value===JSON.stringify(previous))return;
 localStorage.setItem(storageKey,value);notify(storageKey);
}
export async function clearHomeAnalysisPins(token:string,companyId:string){const storageKey=await key(token,companyId);localStorage.removeItem(storageKey);notify(storageKey);}
