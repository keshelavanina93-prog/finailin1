import type {AnalysisProjection,AnalysisRequest} from "@finai/contracts";

const hash=/^[a-f0-9]{64}$/;
const uuid=/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const rowId=/^row_[a-f0-9]{64}$/;
const instant=(value:unknown)=>typeof value==="string"&&/(Z|[+-]\d{2}:\d{2})$/i.test(value)&&Number.isFinite(Date.parse(value));
export type AnalysisView={version:1;request:AnalysisRequest;valid_at:string;known_at:string;receipt_hash:string;columns:string[];visual:boolean;pane:"evidence"|"trace";scroll:number};
export function requestKey(request:AnalysisRequest):string {
 return JSON.stringify([request.company_id,request.invocation_id,request.descriptor_sha256??null,request.filters??[],request.group_by??null,request.selected_row??null,request.contributor_index??0]);
}
/** Response guards bind all panes to the same immutable result, never a later response. */
export function assertProjection(value:AnalysisProjection,request:AnalysisRequest,saved?:AnalysisView|null):void {
 const d=value?.descriptor;
 if(!d||d.contract!=="semantic-analysis/1"||d.invocation_id!==request.invocation_id||d.company?.resource_id!==request.company_id||!hash.test(value.descriptor_sha256)||request.descriptor_sha256&&value.descriptor_sha256!==request.descriptor_sha256||requestKey(value.request)!==requestKey(request)||d.current_use_authorized!==false||d.business_effect_authorized!==false||!instant(d.known_at)||!instant(d.valid_at)||!instant(d.recorded_at))throw Error("This response does not match the selected result, company and revision. Reopen the original analysis.");
 if(saved&&(d.valid_at!==saved.valid_at||d.known_at!==saved.known_at||d.receipt_hash!==saved.receipt_hash))throw Error("The saved view’s exact result and time references no longer match.");
 if(d.visual!=="HORIZONTAL_BARS"||d.filtering!=="RETAINED_GROUP_SELECTION"||d.grouping!=="RETAINED_ROWS_WITHOUT_AGGREGATION"||!Array.isArray(d.fields)||!d.fields.length||!Array.isArray(value.rows)||value.rows.length>1000||!Array.isArray(value.sections))throw Error("This analysis descriptor requires an unsupported renderer.");
 const fields=new Set(d.fields.map(field=>field.key));const rows=new Map(value.rows.map(row=>[row.key,row]));
 if(fields.size!==d.fields.length||!fields.has(d.measure)||rows.size!==value.rows.length||value.rows.some(row=>!rowId.test(row.key)||d.fields.some(field=>!row.values[field.key]))||value.sections.some(section=>section.row_keys.some(key=>!rows.has(key))))throw Error("The retained row and field identities are inconsistent.");
 if(value.selection&&(value.selection.row_key!==request.selected_row||value.selection.contributor_index!==(request.contributor_index??0)||!rows.has(value.selection.row_key)))throw Error("Contributor evidence does not match the selected retained row.");
 if(request.selected_row&&!value.selection)throw Error("The selected contributor is unavailable in this retained result.");
}
/** Allowlist local preferences so response values or credentials cannot be persisted. */
export function parseView(raw:string,companyId:string):AnalysisView|null {
 try {const v=JSON.parse(raw);const r=v.request;
  if(!uuid.test(companyId)||v.version!==1||!r||r.company_id!==companyId||!uuid.test(r.invocation_id)||!hash.test(r.descriptor_sha256)||!instant(v.valid_at)||!instant(v.known_at)||!hash.test(v.receipt_hash)||!Array.isArray(r.filters)||r.filters.length>4||r.filters.some((f:{field:string;state:string;value:unknown})=>typeof f.field!=="string"||f.field.length>128||!["VALUE","NULL","MISSING"].includes(f.state)||f.value!==null&&!["string","number","boolean"].includes(typeof f.value))||r.selected_row!=null&&!rowId.test(r.selected_row)||!Number.isInteger(r.contributor_index)||r.contributor_index<0||r.contributor_index>999||r.group_by!=null&&(typeof r.group_by!=="string"||r.group_by.length>128))return null;
  return {version:1,request:{company_id:companyId,invocation_id:r.invocation_id,descriptor_sha256:r.descriptor_sha256,filters:r.filters.map((f:{field:string;state:"VALUE"|"NULL"|"MISSING";value:string|number|boolean|null})=>({field:f.field,state:f.state,value:f.value})),group_by:r.group_by??null,selected_row:r.selected_row??null,contributor_index:r.contributor_index},valid_at:v.valid_at,known_at:v.known_at,receipt_hash:v.receipt_hash,columns:Array.isArray(v.columns)?v.columns.filter((key:unknown)=>typeof key==="string").slice(0,100):[],visual:v.visual!==false,pane:v.pane==="trace"?"trace":"evidence",scroll:typeof v.scroll==="number"&&Number.isFinite(v.scroll)?Math.max(0,v.scroll):0};
 }catch{return null;}
}
