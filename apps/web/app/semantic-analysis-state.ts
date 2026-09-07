import type {AnalysisContributor,AnalysisField,AnalysisPin,AnalysisProjection,AnalysisRequest,AnalysisValue} from "@finai/contracts";

const hash=/^[a-f0-9]{64}$/;
const uuid=/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const rowId=/^row_[a-f0-9]{64}$/;
const instant=(value:unknown)=>typeof value==="string"&&/(Z|[+-]\d{2}:\d{2})$/i.test(value)&&Number.isFinite(Date.parse(value));
const pin=(value:AnalysisPin)=>Boolean(value&&uuid.test(value.resource_id)&&uuid.test(value.version_id)&&hash.test(value.content_hash));
const kinds=new Set(["text","identifier","reference","integer","decimal","boolean","date","datetime"]);
// Bound visual conversion without changing the exact retained decimal label.
const decimal=/^-?(?:0|[1-9]\d{0,99})(?:\.\d{1,100})?$/;
const storedDecimal=/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;
export function evidenceCaption(basis:AnalysisContributor["basis"]):string {
 return basis==="CANONICAL_DEFINITION"?"Retained canonical definition":basis==="UNAVAILABLE"?"Original source unavailable":"Original retained evidence";
}
function validContributor(value:AnalysisContributor):boolean {
 return Boolean(value&&pin(value.reference)&&[undefined,"ORIGINAL_SOURCE","CANONICAL_DEFINITION","UNAVAILABLE"].includes(value.basis)&&Array.isArray(value.cells)&&value.cells.length<=256&&value.cells.every(cell=>cell&&typeof cell.label==="string"&&(cell.value===null||typeof cell.value==="string"||typeof cell.value==="boolean"||typeof cell.value==="number"&&Number.isSafeInteger(cell.value))));
}
function validValue(value:AnalysisValue,field:AnalysisField):boolean {
 if(!value||!["VALUE","NULL","MISSING"].includes(value.state)||value.label!==null&&typeof value.label!=="string"||value.reference!==null&&!pin(value.reference))return false;
 if(value.state!=="VALUE")return value.value===null;
 switch(field.kind){
  case "decimal":return typeof value.value==="string"&&(field.role==="ATTRIBUTE"?value.value.length<=50&&storedDecimal.test(value.value):decimal.test(value.value)&&Number.isFinite(Number(value.value)));
  case "integer":return typeof value.value==="number"&&Number.isSafeInteger(value.value);
  case "boolean":return typeof value.value==="boolean";
  case "datetime":return instant(value.value);
  case "date":return typeof value.value==="string"&&/^\d{4}-\d{2}-\d{2}$/.test(value.value)&&Number.isFinite(Date.parse(value.value))&&new Date(value.value).toISOString().slice(0,10)===value.value;
  case "text":case "identifier":case "reference":return typeof value.value==="string";
  default:return false;
 }
}
export type AnalysisView={version:1;request:AnalysisRequest;valid_at:string;known_at:string;receipt_hash:string;columns:string[];visual:boolean;pane:"evidence"|"trace";scroll:number;workspace?:{grid:{widths:Record<string,number>;pinned:string[];focus:{row:string;column:string}|null;left:number};dock:"right"|"bottom";collapsed:boolean;size:number}};
export function requestKey(request:AnalysisRequest):string {
 return JSON.stringify([request.company_id,request.invocation_id,request.descriptor_sha256??null,request.filters??[],request.group_by??null,request.selected_row??null,request.contributor_index??0]);
}
/** Response guards bind all panes to the same immutable result, never a later response. */
export function assertProjection(value:AnalysisProjection,request:AnalysisRequest,saved?:AnalysisView|null):void {
 const d=value?.descriptor;
 if(!d||!["semantic-analysis/1","semantic-analysis/2"].includes(d.contract)||d.invocation_id!==request.invocation_id||d.company?.resource_id!==request.company_id||!hash.test(value.descriptor_sha256)||request.descriptor_sha256&&value.descriptor_sha256!==request.descriptor_sha256||requestKey(value.request)!==requestKey(request)||d.current_use_authorized!==false||d.business_effect_authorized!==false||!instant(d.known_at)||!instant(d.valid_at)||!instant(d.recorded_at))throw Error("This response does not match the selected result, company and revision. Reopen the original analysis.");
 if(saved&&(d.valid_at!==saved.valid_at||d.known_at!==saved.known_at||d.receipt_hash!==saved.receipt_hash))throw Error("The saved view’s exact result and time references no longer match.");
 if(d.filtering!=="RETAINED_GROUP_SELECTION"||d.grouping!=="RETAINED_ROWS_WITHOUT_AGGREGATION"||!Array.isArray(d.fields)||!d.fields.length||d.fields.length>100||!Array.isArray(value.rows)||value.rows.length>1000||!Array.isArray(value.sections)||!Number.isInteger(value.total_rows)||value.total_rows<value.rows.length||value.total_rows>1000)throw Error("This analysis descriptor requires an unsupported renderer.");
 const objectTable=d.contract==="semantic-analysis/2";
 if(d.fields.some(field=>!field||typeof field.key!=="string"||!field.key||typeof field.label!=="string"||!kinds.has(field.kind)||!(objectTable?["DIMENSION","ATTRIBUTE"]:["DIMENSION","MEASURE"]).includes(field.role)||!["NONE","RETAINED_VALUE_ONLY"].includes(field.aggregation)||!pin(field.definition)||typeof field.filterable!=="boolean"||typeof field.groupable!=="boolean"||!Array.isArray(field.options)||field.options.length>1000||field.options.some(option=>!validValue(option,field))))throw Error("Unsupported field semantics or typed values in this analysis descriptor.");
 const measures=d.fields.filter(field=>field.role==="MEASURE");
 if(objectTable){
  if(d.measure!==null||d.visual!=="NONE"||d.row_noun!=="objects"||measures.length||d.fields.some(field=>field.aggregation!=="NONE"))throw Error("Object tables must explicitly declare no measure, chart or aggregation.");
 }else if(d.visual!=="HORIZONTAL_BARS"||d.row_noun!==undefined&&d.row_noun!=="groups"||measures.length!==1||measures[0].key!==d.measure||!["decimal","integer"].includes(measures[0].kind))throw Error("This visual requires exactly one declared numeric measure. No numeric meaning is inferred from a dimension.");
 const fields=new Set(d.fields.map(field=>field.key));const rows=new Map(value.rows.map(row=>[row.key,row]));
 if(fields.size!==d.fields.length||d.measure!==null&&!fields.has(d.measure)||rows.size!==value.rows.length||value.rows.some(row=>!rowId.test(row.key)||typeof row.label!=="string"||!pin(row.trace)||!Number.isInteger(row.contributor_count)||row.contributor_count<0||row.contributor_count>1000||!row.values||Object.keys(row.values).some(key=>!fields.has(key))||d.fields.some(field=>!validValue(row.values[field.key],field)))||value.sections.some(section=>typeof section.label!=="string"||!Array.isArray(section.row_keys)||section.row_keys.some(key=>!rows.has(key))))throw Error("The retained row identities, typed values or contributor counts are inconsistent.");
 const sectionKeys=value.sections.flatMap(section=>section.row_keys);
 if(sectionKeys.length!==rows.size||new Set(sectionKeys).size!==rows.size)throw Error("Sections must cover each returned row exactly once, without omitted or duplicate values.");
 if(value.selection&&(value.selection.row_key!==request.selected_row||value.selection.contributor_index!==(request.contributor_index??0)||!rows.has(value.selection.row_key)||value.selection.contributor_count!==rows.get(value.selection.row_key)?.contributor_count||!Number.isInteger(value.selection.contributor_index)||value.selection.contributor_index<0||value.selection.contributor_index>=value.selection.contributor_count||!validContributor(value.selection.contributor)))throw Error("Contributor evidence does not match the selected retained row.");
 if(d.excluded_evidence!==undefined&&(!Array.isArray(d.excluded_evidence)||d.excluded_evidence.length>1000||d.excluded_evidence.some(item=>!validContributor(item))))throw Error("Excluded evidence has an unsupported provenance basis.");
 if(request.selected_row&&!value.selection)throw Error("The selected contributor is unavailable in this retained result.");
}
/** Allowlist local preferences so response values or credentials cannot be persisted. */
export function parseView(raw:string,companyId:string):AnalysisView|null {
 try {const v=JSON.parse(raw);const r=v.request;
  if(!uuid.test(companyId)||v.version!==1||!r||r.company_id!==companyId||!uuid.test(r.invocation_id)||!hash.test(r.descriptor_sha256)||!instant(v.valid_at)||!instant(v.known_at)||!hash.test(v.receipt_hash)||!Array.isArray(r.filters)||r.filters.length>4||r.filters.some((f:{field:string;state:string;value:unknown})=>typeof f.field!=="string"||f.field.length>128||!["VALUE","NULL","MISSING"].includes(f.state)||f.value!==null&&!["string","number","boolean"].includes(typeof f.value))||r.selected_row!=null&&!rowId.test(r.selected_row)||!Number.isInteger(r.contributor_index)||r.contributor_index<0||r.contributor_index>999||r.group_by!=null&&(typeof r.group_by!=="string"||r.group_by.length>128))return null;
  return {version:1,request:{company_id:companyId,invocation_id:r.invocation_id,descriptor_sha256:r.descriptor_sha256,filters:r.filters.map((f:{field:string;state:"VALUE"|"NULL"|"MISSING";value:string|number|boolean|null})=>({field:f.field,state:f.state,value:f.value})),group_by:r.group_by??null,selected_row:r.selected_row??null,contributor_index:r.contributor_index},valid_at:v.valid_at,known_at:v.known_at,receipt_hash:v.receipt_hash,columns:Array.isArray(v.columns)?v.columns.filter((key:unknown)=>typeof key==="string").slice(0,100):[],visual:v.visual!==false,pane:v.pane==="trace"?"trace":"evidence",workspace:parseWorkspace(v.workspace),scroll:typeof v.scroll==="number"&&Number.isFinite(v.scroll)?Math.max(0,v.scroll):0};
 }catch{return null;}
}

function parseWorkspace(value:unknown):AnalysisView["workspace"] {
 if(!value||typeof value!=="object")return undefined;
 const v=value as Record<string,unknown>,g=v.grid as Record<string,unknown>|undefined;
 if(!g||typeof g!=="object")return undefined;
 const finite=(n:unknown,min:number,max:number,fallback:number)=>typeof n==="number"&&Number.isFinite(n)?Math.max(min,Math.min(max,n)):fallback;
 const widths=Object.fromEntries(Object.entries(g.widths&&typeof g.widths==="object"?g.widths:{}).filter(([key,value])=>key.length<=128&&typeof value==="number"&&Number.isFinite(value)).slice(0,100).map(([key,value])=>[key,finite(value,88,600,160)]));
 const focus=g.focus as {row?:unknown;column?:unknown}|undefined;
 return {grid:{widths,pinned:Array.isArray(g.pinned)?g.pinned.filter((key:unknown)=>typeof key==="string"&&key.length<=128).slice(0,100):[],focus:focus&&typeof focus.row==="string"&&rowId.test(focus.row)&&typeof focus.column==="string"&&focus.column.length<=128?{row:focus.row,column:focus.column}:null,left:finite(g.left,0,100000,0)},dock:v.dock==="bottom"?"bottom":"right",collapsed:v.collapsed===true,size:finite(v.size,180,700,340)};
}

/** Keep one keyboard entry in the rendered window without changing evidence selection. */
export function worksheetTabStop(focus:{row:string;column:string}|null,rows:readonly string[],columns:readonly string[]):{row:string;column:string}|null {
 if(!rows.length||!columns.length)return null;
 return {row:focus&&rows.includes(focus.row)?focus.row:rows[0],column:focus&&columns.includes(focus.column)?focus.column:columns[0]};
}

/** A visual choice, never an aggregation or a financial result. */
export function hasUsefulMagnitude(projection:AnalysisProjection):boolean {
 const {descriptor,rows}=projection;
 if(descriptor.visual!=="HORIZONTAL_BARS"||!descriptor.measure||rows.length<2)return false;
 const values=rows.map(row=>row.values[descriptor.measure!]).filter(value=>value?.state==="VALUE").map(value=>Number(value.value)).filter(Number.isFinite);
 return new Set(values).size>1;
}
