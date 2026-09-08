import type {CanonicalResource,CompanyConditionConnection} from "@finai/contracts";
import {restorationInstant} from "./definition-restoration-time";

export type OperatingView={version:1;companyId:string;validAt:string;knownAt:string;group:"assets"|"products"|"parties"|"contracts";search:string;workSearch:string;workFilter:"ALL"|"PREPARED"|"PENDING_REVIEW"|"PUBLISHED"|"REJECTED";page:number;workPage:number;licencePage:number;selected:{resourceId:string;versionId:string}|null};
type Snapshot={companyId:string;validAt:string;knownAt:string};
const uuid=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i;
const page=(value:unknown)=>typeof value==="number"&&Number.isInteger(value)?Math.max(0,Math.min(499,value)):0;
export function parseOperatingView(raw:string,expected:Snapshot):OperatingView|null {
 try {const value=JSON.parse(raw);if(!value||value.version!==1||!uuid.test(expected.companyId)||value.companyId!==expected.companyId||!restorationInstant(expected.validAt)||!restorationInstant(expected.knownAt)||restorationInstant(value.validAt)!==restorationInstant(expected.validAt)||restorationInstant(value.knownAt)!==restorationInstant(expected.knownAt))return null;
  const selected=value.selected&&typeof value.selected.resourceId==="string"&&uuid.test(value.selected.resourceId)&&typeof value.selected.versionId==="string"&&uuid.test(value.selected.versionId)?{resourceId:value.selected.resourceId,versionId:value.selected.versionId}:null;
  return {version:1,...expected,group:["assets","products","parties","contracts"].includes(value.group)?value.group:"assets",search:typeof value.search==="string"?value.search.slice(0,200):"",workSearch:typeof value.workSearch==="string"?value.workSearch.slice(0,200):"",workFilter:["ALL","PREPARED","PENDING_REVIEW","PUBLISHED","REJECTED"].includes(value.workFilter)?value.workFilter:"ALL",page:page(value.page),workPage:page(value.workPage),licencePage:page(value.licencePage),selected};
 }catch{return null;}
}
export function operatingViewPage(value:number,count:number,size:number):number {return Math.min(page(value),Math.max(0,Math.ceil(count/size)-1));}
/** Restored selection must remain an exact member of its displayed connection group. */
export function operatingViewSelection(selected:OperatingView["selected"],resources:CanonicalResource[],connections:CompanyConditionConnection[]):CanonicalResource|null {
 if(!selected)return null;
 const resource=resources.find(item=>item.resource_id===selected.resourceId&&item.version_id===selected.versionId);
 return resource&&connections.some(item=>item.target.resource_id===resource.resource_id&&item.target.version_id===resource.version_id&&item.target.content_hash===resource.content_hash)?resource:null;
}
