export type HomeAnalysisPin={companyId:string;invocationId:string};
const uuid=/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
async function key(token:string,companyId:string){
 if(!uuid.test(companyId))throw Error("An exact company is required.");
 const digest=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(token));
 return `g8-home-pins-v1:${Array.from(new Uint8Array(digest),v=>v.toString(16).padStart(2,"0")).join("")}:${companyId}`;
}
export async function homeAnalysisPins(token:string,companyId:string):Promise<string[]>{
 const value:unknown=JSON.parse(localStorage.getItem(await key(token,companyId))??"[]");
 if(!Array.isArray(value)||value.length>6||value.some(id=>typeof id!=="string"||!uuid.test(id))||new Set(value).size!==value.length)throw Error("Saved Home references are invalid. Clear them and pin the retained analyses again.");
 return value;
}
export async function pinHomeAnalysis(token:string,pin:HomeAnalysisPin){
 if(!uuid.test(pin.invocationId))throw Error("An exact retained analysis is required.");
 const previous=await homeAnalysisPins(token,pin.companyId);
 localStorage.setItem(await key(token,pin.companyId),JSON.stringify([pin.invocationId,...previous.filter(id=>id!==pin.invocationId)].slice(0,6)));
}
export async function clearHomeAnalysisPins(token:string,companyId:string){localStorage.removeItem(await key(token,companyId));}
