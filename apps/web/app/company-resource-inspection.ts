import type {CanonicalResource,OperatorInspection} from "@finai/contracts";
import type {CompanyNyxContext} from "./company-nyx-context";
import {journalReviewOriginMatches} from "./journal-review-handoff";
import {restorationInstant} from "./definition-restoration-time";
export type CompanyResourceInspection={company:Pick<CanonicalResource,"resource_id"|"version_id"|"content_hash"|"display_name">;validAt:string;knownAt:string;resource:{resource_id:string;version_id:string;content_hash?:string;known_at:string}};
export type CompanyResourceInspectionEntry={surfaceKey:string;requestId:number;reference:CompanyResourceInspection|null};
const uuid=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i,hash=/^[a-f0-9]{64}$/;
export function companyResourceInspection(context:CompanyNyxContext|null,resource:{resource_id:string;version_id?:string;content_hash?:string},knownAt?:string):CompanyResourceInspection {
 if(context?.status!=="ready"||!uuid.test(context.companyId)||context.company.resource_id!==context.companyId||!uuid.test(context.company.version_id)||!hash.test(context.company.content_hash)||!restorationInstant(context.validAt)||!restorationInstant(context.knownAt)||!uuid.test(resource.resource_id)||!resource.version_id||!uuid.test(resource.version_id)||(resource.content_hash!==undefined&&!hash.test(resource.content_hash))||!restorationInstant(knownAt??context.knownAt))throw Error("The selected resource needs an exact version and a resolved company snapshot. No current resource has been substituted.");
 const company=context.company;
 return {company:{resource_id:company.resource_id,version_id:company.version_id,content_hash:company.content_hash,display_name:company.display_name},validAt:context.validAt,knownAt:context.knownAt,resource:{resource_id:resource.resource_id,version_id:resource.version_id,...resource.content_hash?{content_hash:resource.content_hash}:{},known_at:knownAt??context.knownAt}};
}
export function companyResourceInspectionMatches(entry:CompanyResourceInspectionEntry|null,surfaceKey:string,context:CompanyNyxContext|null):boolean {
 return Boolean(entry?.surfaceKey===surfaceKey&&entry.reference&&journalReviewOriginMatches(entry.reference,context));
}
export function assertCompanyResourceInspection(value:OperatorInspection,reference:CompanyResourceInspection):void {
 const pin=reference.resource;
 if(value.purpose!=="HISTORICAL_INSPECTION"||value.current_use_authorized!==false||value.selection_mode!=="EXACT_VERSION"||value.resource?.resource_id!==pin.resource_id||value.resource.version_id!==pin.version_id||(pin.content_hash&&value.resource.content_hash!==pin.content_hash)||!restorationInstant(value.known_at)||restorationInstant(value.known_at)!==restorationInstant(pin.known_at))throw Error("Resource inspection did not match the exact version, evidence hash, knowledge cutoff and historical-only authority.");
}
/** Focus return never changes route scroll or revives a hidden/removed control. */
export function restoreCompanyInspectionFocus(element:HTMLElement|null):boolean {
 if(!element?.isConnected||element.closest("[hidden],[inert]")||!element.getClientRects().length)return false;
 element.focus({preventScroll:true});return true;
}

export type ResourceInspectionRead={controller:AbortController;requestId:number};
/** Cancellation cannot clear a newer work/evidence request sharing the detail slot. */
export function cancelResourceInspectionRead(read:ResourceInspectionRead,activeRequest:number):{requestId:number;clearReadback:boolean} {
 read.controller.abort();
 return read.requestId===activeRequest?{requestId:activeRequest+1,clearReadback:true}:{requestId:activeRequest,clearReadback:false};
}
