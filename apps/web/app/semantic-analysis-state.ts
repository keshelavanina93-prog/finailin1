import type {AnalysisField,AnalysisPin,AnalysisProjection,AnalysisRequest,AnalysisValue} from "@finai/contracts";

const hash=/^[a-f0-9]{64}$/;
const uuid=/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const rowId=/^row_[a-f0-9]{64}$/;
const instant=(value:unknown)=>typeof value==="string"&&/(Z|[+-]\d{2}:\d{2})$/i.test(value)&&Number.isFinite(Date.parse(value));
const pin=(value:AnalysisPin)=>Boolean(value&&uuid.test(value.resource_id)&&uuid.test(value.version_id)&&hash.test(value.content_hash));
const kinds=new Set(["text","identifier","reference","integer","decimal","boolean","date","datetime"]);
// Bound visual conversion without changing the exact retained decimal label.
const decimal=/^-?(?:0|[1-9]\d{0,99})(?:\.\d{1,100})?$/;
function validValue(value:AnalysisValue,field:AnalysisField):boolean {
 if(!value||!["VALUE","NULL","MISSING"].includes(value.state)||value.label!==null&&typeof value.label!=="string"||value.reference!==null&&!pin(value.reference))return false;
 if(value.state!=="VALUE")return value.value===null;
 switch(field.kind){
  case "decimal":return typeof value.value==="string"&&decimal.test(value.value)&&Number.isFinite(Number(value.value));
  case "integer":return typeof value.value==="number"&&Number.isSafeInteger(value.value);
  case "boolean":return typeof value.value==="boolean";
  case "datetime":return instant(value.value);
  case "date":return typeof value.value==="string"&&/^\d{4}-\d{2}-\d{2}$/.test(value.value)&&Number.isFinite(Date.parse(value.value))&&new Date(value.value).toISOString().slice(0,10)===value.value;
  case "text":case "identifier":case "reference":return typeof value.value==="string";
  default:return false;
 }
}
export type AnalysisView={version:1;request:AnalysisRequest;valid_at:string;known_at:string;receipt_hash:string;columns:string[];visual:boolean;pane:"evidence"|"trace";scroll:number};
export function requestKey(request:AnalysisRequest):string {
 return JSON.stringify([request.company_id,request.invocation_id,request.descriptor_sha256??null,request.filters??[],request.group_by??null,request.selected_row??null,request.contributor_index??0]);
}
/** Response guards bind all panes to the same immutable result, never a later response. */
export function assertProjection(value:AnalysisProjection,request:AnalysisRequest,saved?:AnalysisView|null):void {
 const d=value?.descriptor;
 if(!d||d.contract!=="semantic-analysis/1"||d.invocation_id!==request.invocation_id||d.company?.resource_id!==request.company_id||!hash.test(value.descriptor_sha256)||request.descriptor_sha256&&value.descriptor_sha256!==request.descriptor_sha256||requestKey(value.request)!==requestKey(request)||d.current_use_authorized!==false||d.business_effect_authorized!==false||!instant(d.known_at)||!instant(d.valid_at)||!instant(d.recorded_at))throw Error("This response does not match the selected result, company and revision. Reopen the original analysis.");
 if(saved&&(d.valid_at!==saved.valid_at||d.known_at!==saved.known_at||d.receipt_hash!==saved.receipt_hash))throw Error("The saved view’s exact result and time references no longer match.");
 if(d.visual!=="HORIZONTAL_BARS"||d.filtering!=="RETAINED_GROUP_SELECTION"||d.grouping!=="RETAINED_ROWS_WITHOUT_AGGREGATION"||!Array.isArray(d.fields)||!d.fields.length||d.fields.length>100||!Array.isArray(value.rows)||value.rows.length>1000||!Array.isArray(value.sections)||!Number.isInteger(value.total_rows)||value.total_rows<value.rows.length||value.total_rows>1000)throw Error("This analysis descriptor requires an unsupported renderer.");
 if(d.fields.some(field=>!field||typeof field.key!=="string"||!field.key||typeof field.label!=="string"||!kinds.has(field.kind)||!["DIMENSION","MEASURE"].includes(field.role)||!["NONE","RETAINED_VALUE_ONLY"].includes(field.aggregation)||!pin(field.definition)||typeof field.filterable!=="boolean"||typeof field.groupable!=="boolean"||!Array.isArray(field.options)||field.options.length>1000||field.options.some(option=>!validValue(option,field))))throw Error("Unsupported field semantics or typed values in this analysis descriptor.");
 const measures=d.fields.filter(field=>field.role==="MEASURE");
 if(measures.length!==1||measures[0].key!==d.measure||!["decimal","integer"].includes(measures[0].kind))throw Error("This visual requires exactly one declared numeric measure. No numeric meaning is inferred from a dimension.");
 const fields=new Set(d.fields.map(field=>field.key));const rows=new Map(value.rows.map(row=>[row.key,row]));
 if(fields.size!==d.fields.length||!fields.has(d.measure)||rows.size!==value.rows.length||value.rows.some(row=>!rowId.test(row.key)||typeof row.label!=="string"||!pin(row.trace)||!Number.isInteger(row.contributor_count)||row.contributor_count<0||row.contributor_count>1000||!row.values||Object.keys(row.values).some(key=>!fields.has(key))||d.fields.some(field=>!validValue(row.values[field.key],field)))||value.sections.some(section=>typeof section.label!=="string"||!Array.isArray(section.row_keys)||section.row_keys.some(key=>!rows.has(key))))throw Error("The retained row identities, typed values or contributor counts are inconsistent.");
 const sectionKeys=value.sections.flatMap(section=>section.row_keys);
 if(sectionKeys.length!==rows.size||new Set(sectionKeys).size!==rows.size)throw Error("Sections must cover each returned row exactly once, without omitted or duplicate values.");
 if(value.selection&&(value.selection.row_key!==request.selected_row||value.selection.contributor_index!==(request.contributor_index??0)||!rows.has(value.selection.row_key)||value.selection.contributor_count!==rows.get(value.selection.row_key)?.contributor_count||!Number.isInteger(value.selection.contributor_index)||value.selection.contributor_index<0||value.selection.contributor_index>=value.selection.contributor_count||!pin(value.selection.contributor.reference)))throw Error("Contributor evidence does not match the selected retained row.");
 if(request.selected_row&&!value.selection)throw Error("The selected contributor is unavailable in this retained result.");
}
/** Allowlist local preferences so response values or credentials cannot be persisted. */
export function parseView(raw:string,companyId:string):AnalysisView|null {
 try {const v=JSON.parse(raw);const r=v.request;
  if(!uuid.test(companyId)||v.version!==1||!r||r.company_id!==companyId||!uuid.test(r.invocation_id)||!hash.test(r.descriptor_sha256)||!instant(v.valid_at)||!instant(v.known_at)||!hash.test(v.receipt_hash)||!Array.isArray(r.filters)||r.filters.length>4||r.filters.some((f:{field:string;state:string;value:unknown})=>typeof f.field!=="string"||f.field.length>128||!["VALUE","NULL","MISSING"].includes(f.state)||f.value!==null&&!["string","number","boolean"].includes(typeof f.value))||r.selected_row!=null&&!rowId.test(r.selected_row)||!Number.isInteger(r.contributor_index)||r.contributor_index<0||r.contributor_index>999||r.group_by!=null&&(typeof r.group_by!=="string"||r.group_by.length>128))return null;
  return {version:1,request:{company_id:companyId,invocation_id:r.invocation_id,descriptor_sha256:r.descriptor_sha256,filters:r.filters.map((f:{field:string;state:"VALUE"|"NULL"|"MISSING";value:string|number|boolean|null})=>({field:f.field,state:f.state,value:f.value})),group_by:r.group_by??null,selected_row:r.selected_row??null,contributor_index:r.contributor_index},valid_at:v.valid_at,known_at:v.known_at,receipt_hash:v.receipt_hash,columns:Array.isArray(v.columns)?v.columns.filter((key:unknown)=>typeof key==="string").slice(0,100):[],visual:v.visual!==false,pane:v.pane==="trace"?"trace":"evidence",scroll:typeof v.scroll==="number"&&Number.isFinite(v.scroll)?Math.max(0,v.scroll):0};
 }catch{return null;}
}
