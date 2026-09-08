import type {CompanyNyxContext} from "./company-nyx-context";
import type {CompanyOriginReference,CompanyOriginEntry,CompanyWorkReference,JournalReviewDomOrigin} from "./journal-review-handoff";
import type {MapSelection,MapWorkspaceState} from "./operations-model";
import {restorationInstant} from "./definition-restoration-time";
import {restoreCompanyInspectionFocus} from "./company-resource-inspection";
import {isCompanyRegulationOrigin,type CompanyRegulationOrigin} from "./company-regulation-handoff";
import {isCompanyAccountingOrigin,type CompanyAccountingOrigin,type CompanyAccountingHandoff} from "./company-accounting-handoff";
export type CompanyMapHandoff=CompanyOriginReference&{kind:"map";state:MapWorkspaceState;selection:MapSelection|null};
export type CompanyForegroundEntry=Omit<CompanyOriginEntry,"reference">&{reference:CompanyWorkReference|CompanyMapHandoff|CompanyRegulationOrigin|CompanyAccountingOrigin;mapState?:MapWorkspaceState;mapSelection?:MapSelection|null;accountingHandoff?:CompanyAccountingHandoff};
const uuid=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i,hash=/^[a-f0-9]{64}$/;
export const isCompanyMapHandoff=(value:CompanyForegroundEntry["reference"]):value is CompanyMapHandoff=>"kind" in value&&value.kind==="map";
export const isCompanyExplorationHandoff=(value:CompanyForegroundEntry["reference"]):value is CompanyMapHandoff|CompanyRegulationOrigin|CompanyAccountingOrigin=>isCompanyMapHandoff(value)||isCompanyRegulationOrigin(value)||isCompanyAccountingOrigin(value);
function stateReference(state:MapWorkspaceState):MapWorkspaceState {
 const bbox=state.bbox??"",search=state.search??"",bounds=bbox?bbox.split(",").map(Number):null;
 if(!["enterprise_assets","gas_network"].includes(state.lens)||!restorationInstant(state.validAt)||!restorationInstant(state.knownAt)||!Array.isArray(state.center)||state.center.length!==2||state.center.some(value=>!Number.isFinite(value))||Math.abs(state.center[0])>180||Math.abs(state.center[1])>90||!Number.isFinite(state.zoom)||state.zoom<0||state.zoom>24||typeof search!=="string"||search.length>200||typeof bbox!=="string"||bbox.length>200||bounds&&(bounds.length!==4||bounds.some(value=>!Number.isFinite(value))||Math.abs(bounds[0])>180||Math.abs(bounds[2])>180||Math.abs(bounds[1])>90||Math.abs(bounds[3])>90||bounds[0]>=bounds[2]||bounds[1]>=bounds[3]))throw Error("The map drill requires the displayed exact time, viewport and bounded filters.");
 return {lens:state.lens,validAt:state.validAt,knownAt:state.knownAt,center:[...state.center],zoom:state.zoom,bbox,search};
}
/** Company and map times remain separate; selections are retained in memory, never in history. */
export function companyMapHandoff(context:CompanyNyxContext|null,state:MapWorkspaceState,selection:MapSelection|null=null):CompanyMapHandoff {
 if(context?.status!=="ready"||context.company.resource_id!==context.companyId||!uuid.test(context.companyId)||!uuid.test(context.company.version_id)||!hash.test(context.company.content_hash)||!restorationInstant(context.validAt)||!restorationInstant(context.knownAt))throw Error("The original company snapshot is unavailable. No latest company or map has been substituted.");
 const map=stateReference(state),resource=selection?.resource;
 if(selection&&(!resource||!uuid.test(resource.resource_id)||!uuid.test(resource.version_id)||!hash.test(resource.content_hash)||restorationInstant(selection.validAt)!==restorationInstant(map.validAt)||restorationInstant(selection.knownAt)!==restorationInstant(map.knownAt)))throw Error("The selected asset does not match the map's exact retained times and resource reference.");
 const company=context.company;
 return {kind:"map",company:{resource_id:company.resource_id,version_id:company.version_id,content_hash:company.content_hash,display_name:company.display_name},validAt:context.validAt,knownAt:context.knownAt,state:map,selection};
}
export function restoreCompanyExplorationFocus(origin:JournalReviewDomOrigin&{focus:HTMLElement|null},main:HTMLElement|null):boolean {
 if(!origin.element.isConnected||!origin.queue.isConnected||origin.element.hidden||origin.element.inert)return false;
 main?.scrollTo({top:origin.scroll,behavior:"instant"});for(const item of origin.scrolls)if(item.element.isConnected)item.element.scrollTo({top:item.top,left:item.left,behavior:"instant"});
 return restoreCompanyInspectionFocus(origin.focus)||restoreCompanyInspectionFocus(origin.queue);
}

export function sameCompanyMapSelection(left:MapSelection|null,right:MapSelection|null):boolean {
 return Boolean(left&&right&&left.resource.resource_id===right.resource.resource_id&&left.resource.version_id===right.resource.version_id&&left.resource.content_hash===right.resource.content_hash&&restorationInstant(left.validAt)&&restorationInstant(left.validAt)===restorationInstant(right.validAt)&&restorationInstant(left.knownAt)&&restorationInstant(left.knownAt)===restorationInstant(right.knownAt));
}

// Existing map consumers retain the same focus restoration contract.
export const restoreCompanyMapFocus=restoreCompanyExplorationFocus;
