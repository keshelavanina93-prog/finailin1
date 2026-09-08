import type {CanonicalResource,CompanyConditionConnection} from "@finai/contracts";
import {restorationInstant} from "./definition-restoration-time";

export type OperatingView={version:2;companyId:string;validAt:string;knownAt:string;group:{key:string;versionId:string;contentHash:string;definitionPins:Array<{resource_id:string;version_id:string;content_hash:string}>}|null;groupUnavailable:boolean;search:string;workSearch:string;workFilter:"ALL"|"PREPARED"|"PENDING_REVIEW"|"PUBLISHED"|"REJECTED";page:number;workPage:number;licencePage:number;selected:{resourceId:string;versionId:string;contentHash:string}|null};
type Snapshot={companyId:string;validAt:string;knownAt:string};
const uuid=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i;
const page=(value:unknown)=>typeof value==="number"&&Number.isInteger(value)?Math.max(0,Math.min(499,value)):0;
export function parseOperatingView(raw:string,expected:Snapshot):OperatingView|null {
 try {const value=JSON.parse(raw);if(!value||![1,2].includes(value.version)||!uuid.test(expected.companyId)||value.companyId!==expected.companyId||!restorationInstant(expected.validAt)||!restorationInstant(expected.knownAt)||restorationInstant(value.validAt)!==restorationInstant(expected.validAt)||restorationInstant(value.knownAt)!==restorationInstant(expected.knownAt))return null;
  const selected=value.version===2&&value.selected&&typeof value.selected.resourceId==="string"&&uuid.test(value.selected.resourceId)&&typeof value.selected.versionId==="string"&&uuid.test(value.selected.versionId)&&typeof value.selected.contentHash==="string"&&/^[a-f0-9]{64}$/.test(value.selected.contentHash)?{resourceId:value.selected.resourceId,versionId:value.selected.versionId,contentHash:value.selected.contentHash}:null;
  const pins=value.group?.definitionPins;
  const validPins=Array.isArray(pins)&&pins.length<=5000&&pins.every(pin=>pin&&typeof pin.resource_id==="string"&&uuid.test(pin.resource_id)&&typeof pin.version_id==="string"&&uuid.test(pin.version_id)&&typeof pin.content_hash==="string"&&/^[a-f0-9]{64}$/.test(pin.content_hash))&&new Set(pins.map(pin=>pin.resource_id)).size===pins.length;
  const group=validPins&&value.version===2&&value.group&&typeof value.group.key==="string"&&uuid.test(value.group.key)&&typeof value.group.versionId==="string"&&uuid.test(value.group.versionId)&&typeof value.group.contentHash==="string"&&/^[a-f0-9]{64}$/.test(value.group.contentHash)?{key:value.group.key,versionId:value.group.versionId,contentHash:value.group.contentHash,definitionPins:pins.map(pin=>({resource_id:pin.resource_id,version_id:pin.version_id,content_hash:pin.content_hash}))}:null;
  return {version:2,...expected,group,groupUnavailable:value.version===1||value.groupUnavailable===true||Boolean(value.group&&!group),search:typeof value.search==="string"?value.search.slice(0,200):"",workSearch:typeof value.workSearch==="string"?value.workSearch.slice(0,200):"",workFilter:["ALL","PREPARED","PENDING_REVIEW","PUBLISHED","REJECTED"].includes(value.workFilter)?value.workFilter:"ALL",page:page(value.page),workPage:page(value.workPage),licencePage:page(value.licencePage),selected};
 }catch{return null;}
}
export function operatingViewPage(value:number,count:number,size:number):number {return Math.min(page(value),Math.max(0,Math.ceil(count/size)-1));}
/** Restored selection must remain an exact member of its displayed connection group. */
export function operatingViewSelection(selected:OperatingView["selected"],resources:CanonicalResource[],connections:CompanyConditionConnection[]):CanonicalResource|null {
 if(!selected)return null;
 const resource=resources.find(item=>item.resource_id===selected.resourceId&&item.version_id===selected.versionId&&item.content_hash===selected.contentHash);
 return resource&&connections.some(item=>item.target.resource_id===resource.resource_id&&item.target.version_id===resource.version_id&&item.target.content_hash===resource.content_hash)?resource:null;
}

/** Unknown keys and revised dependencies refuse restoration; labels never identify a group. */
export function matchesOperatingGroup(saved:OperatingView["group"],group:{key:string;definition:CanonicalResource;definition_pins:Array<{resource_id:string;version_id:string;content_hash:string}>}):boolean {
 return Boolean(saved&&saved.key===group.key&&saved.versionId===group.definition.version_id&&saved.contentHash===group.definition.content_hash&&saved.definitionPins.length===group.definition_pins.length&&saved.definitionPins.every(pin=>group.definition_pins.some(actual=>actual.resource_id===pin.resource_id&&actual.version_id===pin.version_id&&actual.content_hash===pin.content_hash)));
}
