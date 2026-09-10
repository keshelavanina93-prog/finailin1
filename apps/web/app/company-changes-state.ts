import type {CanonicalResource,CompanyChangesDescriptor,CompanyChangesRequest} from "@finai/contracts";
import {restorationInstant} from "./definition-restoration-time";

const uuid=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i;
const resource=(node:CanonicalResource|null)=>Boolean(node&&uuid.test(node.resource_id)&&uuid.test(node.version_id)&&/^[a-f0-9]{64}$/.test(node.content_hash)&&node.authority_state==="APPROVED"&&node.evidence_class!=="REFERENCE_TEMPLATE"&&typeof node.display_name==="string");
export function priorKnowledge(knownAt:string,days:number):string {
 const exact=restorationInstant(knownAt);
 if(!exact||![1,7,30].includes(days))throw Error("Choose a supported knowledge comparison interval.");
 const earlier=new Date(Date.parse(exact)-days*86400000).toISOString();
 return `${earlier.slice(0,19)}${exact.slice(19)}`;
}
export function assertCompanyChanges(value:CompanyChangesDescriptor,request:CompanyChangesRequest):void {
 const current=restorationInstant(request.known_at),before=restorationInstant(request.compare_known_at);
 if(!current||!before||before>=current||!restorationInstant(request.valid_at))throw Error("Comparison requires an earlier, timezone-aware knowledge cutoff.");
 if(!value||value.contract!=="g8-company-changes/1"||!resource(value.company)||value.company.resource_id!==request.company_id||value.company.object_type!=="LegalEntity"||value.authority!=="RETAINED_COMPANY_CONTEXT_COMPARISON"||value.coverage!=="EXPLICIT_COMPANY_CONTEXT"||value.current_use_authorized!==false||value.business_effect_authorized!==false||restorationInstant(value.valid_at)!==restorationInstant(request.valid_at)||restorationInstant(value.known_at)!==current||restorationInstant(value.compare_known_at)!==before)throw Error("Company comparison did not preserve the selected company and exact cutoffs.");
 if(!Array.isArray(value.changes)||value.changes.length>5000||new Set(value.changes.map(item=>item.resource_id)).size!==value.changes.length||value.changes.some(item=>{
  if(!uuid.test(item.resource_id)||!["ADDED_TO_CONTEXT","REMOVED_FROM_CONTEXT","CHANGED_VERSION"].includes(item.kind)||!Array.isArray(item.changed_fields)||item.changed_fields.some(field=>typeof field!=="string"||!field.startsWith("/")))return true;
  if(item.before!==null&&(!resource(item.before)||item.before.resource_id!==item.resource_id)||item.after!==null&&(!resource(item.after)||item.after.resource_id!==item.resource_id))return true;
  if(item.kind==="ADDED_TO_CONTEXT")return item.before!==null||item.after===null||item.changed_fields.length!==0;
  if(item.kind==="REMOVED_FROM_CONTEXT")return item.before===null||item.after!==null||item.changed_fields.length!==0;
  return item.before===null||item.after===null||item.before.object_type!==item.after.object_type||item.before.version_id===item.after.version_id;
 }))throw Error("Company comparison contains inconsistent retained versions or change kinds.");
 if(!Array.isArray(value.limitations)||!value.limitations.length||value.limitations.some(item=>typeof item!=="string"||!item.trim()))throw Error("Company comparison coverage limitations are unavailable.");
}
