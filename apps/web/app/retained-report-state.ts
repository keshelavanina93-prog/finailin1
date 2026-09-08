import type {AnalysisField,AnalysisProjection,AnalysisValue,ReportComposition,ReportSectionReference} from "@finai/contracts";
import {assertProjection,formatAnalysisDecimal} from "./semantic-analysis-state";
import {metricCanonical} from "./metric-observation-state";
import {homeAnalysisRowTarget} from "./home-analysis-row";
import {restorationInstant} from "./definition-restoration-time";

const uuid=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i;
const hash=/^[a-f0-9]{64}$/;
/** Drafts carry exact references and presentation choices, never copied result values. */
export function reportSectionFromProjection(projection:AnalysisProjection,companyId:string,sectionId:string):ReportSectionReference {
 assertProjection(projection,{...projection.request,company_id:companyId});
 if(!uuid.test(sectionId))throw Error("The report section requires an exact identity.");
 return {section_id:sectionId,title:projection.descriptor.title,invocation_id:projection.descriptor.invocation_id,receipt_hash:projection.descriptor.receipt_hash,descriptor_sha256:projection.descriptor_sha256,columns:projection.descriptor.fields.slice(0,32).map(field=>field.key),filters:(projection.request.filters??[]).map(filter=>({...filter})),group_by:projection.request.group_by??null};
}
export function reportCompositionReferences(value:ReportComposition):ReportComposition {
 if(!uuid.test(value.company_id)||!restorationInstant(value.valid_at)||!restorationInstant(value.known_at)||typeof value.title!=="string"||!value.title.trim()||typeof value.commentary!=="string"||value.sections.length<1||value.sections.length>8||new Set(value.sections.map(section=>section.section_id)).size!==value.sections.length)throw Error("Choose one to eight distinct report sections and an exact company snapshot.");
 return {company_id:value.company_id,valid_at:value.valid_at,known_at:value.known_at,title:value.title,commentary:value.commentary,sections:value.sections.map(section=>{
  if(!uuid.test(section.section_id)||!uuid.test(section.invocation_id)||!hash.test(section.receipt_hash)||!hash.test(section.descriptor_sha256)||typeof section.title!=="string"||section.columns.length<1||section.columns.length>32||section.columns.some(key=>typeof key!=="string"||!key)||new Set(section.columns).size!==section.columns.length||section.filters.length>4||section.filters.some(filter=>typeof filter.field!=="string"||!["VALUE","NULL","MISSING"].includes(filter.state)||filter.value!==null&&!["string","number","boolean"].includes(typeof filter.value)))throw Error("Each section requires exact result references, one to 32 distinct columns and at most four filters.");
  return {section_id:section.section_id,title:section.title,invocation_id:section.invocation_id,receipt_hash:section.receipt_hash,descriptor_sha256:section.descriptor_sha256,columns:[...section.columns],filters:section.filters.map(filter=>({field:filter.field,state:filter.state,value:filter.value})),group_by:section.group_by??null};
 })};
}
export function sameReportComposition(a:ReportComposition,b:ReportComposition):boolean {
 return metricCanonical(reportCompositionReferences(a))===metricCanonical(reportCompositionReferences(b));
}
export function reportCellLabel(value:AnalysisValue,field:AnalysisField):string {
 if(value.state!=="VALUE")return value.state==="NULL"?"Recorded null":"Not recorded";
 if(value.label!==null)return value.label;
 if(value.value==="")return "Empty text";
 return field.presentation&&typeof value.value==="string"?formatAnalysisDecimal(value.value,field):String(value.value);
}
/** The existing source-review route rechecks the selected retained contributor. */
export function reportEvidenceTarget(projection:AnalysisProjection,companyId:string,rowKey:string){
 const d=projection.descriptor;
 return homeAnalysisRowTarget(projection,{kind:"EXACT",invocationId:d.invocation_id,revision:{descriptorSha256:projection.descriptor_sha256,receiptHash:d.receipt_hash,validAt:d.valid_at,knownAt:d.known_at}},companyId,rowKey);
}
