import type {AnalysisField,AnalysisProjection,AnalysisValue,ReportComposition,ReportSectionReference,ReportPreview,RetainedReportSnapshot,RetainedReport,RetainedReportPage,ReportVersionReference,ReportArtifactMetadata,SaveRetainedReport} from "@finai/contracts";
import {assertProjection,formatAnalysisDecimal} from "./semantic-analysis-state";
import {metricCanonical,metricPin} from "./metric-observation-state";
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
 const canonical=(value:ReportComposition)=>{const refs=reportCompositionReferences(value);return {...refs,valid_at:restorationInstant(refs.valid_at),known_at:restorationInstant(refs.known_at)};};
 return metricCanonical(canonical(a))===metricCanonical(canonical(b));
}

const refused=()=>Error("The report does not match the selected company, composition or exact retained version.");
function validReportReference(value:ReportVersionReference):boolean{return Boolean(value&&uuid.test(value.report_id)&&uuid.test(value.proposal_id)&&hash.test(value.content_hash));}
export function assertReportSnapshot(value:RetainedReportSnapshot,companyId:string,composition?:ReportComposition):void {
 if(!value||value.contract!=="retained-report-snapshot/1"||!metricPin(value.company)||value.company.resource_id!==companyId||value.composition?.company_id!==companyId||typeof value.company_label!=="string"||value.current_use_authorized!==false||value.business_effect_authorized!==false)throw refused();
 const canonical=reportCompositionReferences(value.composition);
 if(composition&&!sameReportComposition(canonical,composition)||!Array.isArray(value.sections)||value.sections.length!==canonical.sections.length)throw refused();
 value.sections.forEach((section,index)=>{
  const reference=canonical.sections[index],p=section.projection;
  if(metricCanonical(section.reference)!==metricCanonical(reference)||section.current_use_authorized!==false||section.business_effect_authorized!==false||!p||p.descriptor.receipt_hash!==reference.receipt_hash||p.descriptor_sha256!==reference.descriptor_sha256||!section.contributors||Array.isArray(section.contributors)||!Array.isArray(section.authority_observation?.roots)||!section.authority_observation.roots.every(metricPin)||!Array.isArray(section.authority_observation.upstream))throw refused();
  assertProjection(p,{...p.request,company_id:companyId,invocation_id:reference.invocation_id,descriptor_sha256:reference.descriptor_sha256,filters:reference.filters,group_by:reference.group_by});
  if(reference.columns.some(key=>!p.descriptor.fields.some(field=>field.key===key))||Object.keys(section.contributors).length!==p.rows.length||Object.keys(section.contributors).some(key=>!p.rows.some(row=>row.key===key)))throw refused();
  for(const row of p.rows){const contributors=section.contributors[row.key];if(!Array.isArray(contributors)||contributors.length!==row.contributor_count)throw refused();contributors.forEach((contributor,contributor_index)=>{const request={...p.request,selected_row:row.key,contributor_index};assertProjection({...p,request,selection:{row_key:row.key,contributor_index,contributor_count:contributors.length,contributor}},request);});}
 });
}
export function assertReportPreview(value:ReportPreview,composition:ReportComposition):void {
 if(!value||value.contract!=="retained-report-preview/1"||!hash.test(value.snapshot_sha256))throw refused();
 assertReportSnapshot(value.snapshot,composition.company_id,composition);
}
export function freezeReportSave(composition:ReportComposition,preview:ReportPreview,reportId:string,previousProposalId:string|null,requestId:string):SaveRetainedReport {
 assertReportPreview(preview,composition);
 if(!uuid.test(reportId)||!uuid.test(requestId)||previousProposalId!==null&&!uuid.test(previousProposalId))throw refused();
 return {request_id:requestId,report_id:reportId,previous_proposal_id:previousProposalId,expected_preview_sha256:preview.snapshot_sha256,composition:reportCompositionReferences(composition)};
}
export function assertRetainedReport(value:RetainedReport,companyId:string,expected?:ReportVersionReference,save?:SaveRetainedReport,preview?:ReportPreview):void {
 if(!value||value.contract!=="retained-report/1"||!validReportReference(value.reference)||value.company_id!==companyId||!restorationInstant(value.created_at)||typeof value.title!=="string"||typeof value.created_by!=="string"||!["DRAFT","APPROVED","REJECTED"].includes(value.review_state)||value.current_use_authorized!==false||value.business_effect_authorized!==false||expected&&metricCanonical(value.reference)!==metricCanonical(expected)||save&&(value.reference.report_id!==save.report_id||value.previous_proposal_id!==save.previous_proposal_id))throw refused();
 assertReportSnapshot(value.snapshot,companyId,save?.composition);
 if(preview&&metricCanonical(value.snapshot)!==metricCanonical(preview.snapshot))throw refused();
 for(const format of ["xlsx","html"] as const){const artifact=value.exports?.[format];if(!artifact||!Number.isSafeInteger(artifact.size_bytes)||artifact.size_bytes<1||artifact.size_bytes>16000000||!hash.test(artifact.sha256)||typeof artifact.filename!=="string"||!artifact.filename||/[\r\n/\\]/.test(artifact.filename)||artifact.media_type.split(";")[0]!== (format==="xlsx"?"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":"text/html"))throw refused();}
}
export function assertReportPage(value:RetainedReportPage,companyId:string):void {
 if(!value||value.contract!=="retained-report-list/1"||value.company_id!==companyId||!Array.isArray(value.items)||new Set(value.items.map(item=>item.reference?.proposal_id)).size!==value.items.length)throw refused();
 for(const item of value.items)if(item.company_id!==companyId||!validReportReference(item.reference)||!restorationInstant(item.created_at)||typeof item.title!=="string"||!["DRAFT","APPROVED","REJECTED"].includes(item.review_state)||item.current_use_authorized!==false||item.business_effect_authorized!==false)throw refused();
 if(value.next_cursor!==null&&(!value.next_cursor||!restorationInstant(value.next_cursor.created_at)||!uuid.test(value.next_cursor.proposal_id)))throw refused();
}
export async function verifyReportDownload(bytes:ArrayBuffer,headers:Headers,artifact:ReportArtifactMetadata,reference:ReportVersionReference):Promise<void>{
 if(headers.get("x-report-content-hash")!==reference.content_hash||headers.get("x-report-proposal-id")!==reference.proposal_id||headers.get("x-content-sha256")!==artifact.sha256||headers.get("content-type")?.split(";")[0]!==artifact.media_type.split(";")[0]||Number(headers.get("content-length"))!==artifact.size_bytes||bytes.byteLength!==artifact.size_bytes)throw Error("Report download identity or length changed. No file was released.");
 const digest=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",bytes)),byte=>byte.toString(16).padStart(2,"0")).join("");
 if(digest!==artifact.sha256)throw Error("Report download integrity check failed. No file was released.");
}
async function reportResponse<T>(response:Response,parse:(value:unknown)=>T):Promise<T>{
 const value=await response.json().catch(()=>null);
 if(!response.ok)throw Error(typeof (value as {detail?:unknown})?.detail==="string"?String((value as {detail:string}).detail):`Retained report request failed (${response.status}).`);
 return parse(value);
}
export async function previewRetainedReport(token:string,composition:ReportComposition):Promise<ReportPreview>{
 const response=await fetch("/api/ontology/retained-reports/preview",{method:"POST",headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},body:JSON.stringify(reportCompositionReferences(composition)),cache:"no-store"});
 return reportResponse(response,value=>{const preview=value as ReportPreview;assertReportPreview(preview,composition);return preview;});
}
export async function saveRetainedReport(token:string,composition:ReportComposition,preview:ReportPreview,previousProposalId:string|null=null):Promise<RetainedReport>{
 const request=freezeReportSave(composition,preview,crypto.randomUUID(),previousProposalId,crypto.randomUUID());
 const response=await fetch("/api/ontology/retained-reports",{method:"POST",headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},body:JSON.stringify(request),cache:"no-store"});
 return reportResponse(response,value=>{const report=value as RetainedReport;assertRetainedReport(report,composition.company_id,undefined,request,preview);return report;});
}
export async function listRetainedReports(token:string,companyId:string,cursor?:{created_at:string;proposal_id:string}):Promise<RetainedReportPage>{
 const query=new URLSearchParams({company_id:companyId});if(cursor){query.set("cursor_created_at",cursor.created_at);query.set("cursor_proposal_id",cursor.proposal_id);}
 const response=await fetch(`/api/ontology/retained-reports?${query}`,{headers:{Authorization:`Bearer ${token}`},cache:"no-store"});
 return reportResponse(response,value=>{const page=value as RetainedReportPage;assertReportPage(page,companyId);return page;});
}
export async function reopenRetainedReport(token:string,companyId:string,proposalId:string):Promise<RetainedReport>{
 if(!uuid.test(companyId)||!uuid.test(proposalId))throw refused();
 const response=await fetch(`/api/ontology/retained-reports/${encodeURIComponent(proposalId)}?company_id=${encodeURIComponent(companyId)}`,{headers:{Authorization:`Bearer ${token}`},cache:"no-store"});
 return reportResponse(response,value=>{const report=value as RetainedReport;assertRetainedReport(report,companyId);return report;});
}
export async function downloadRetainedReport(token:string,companyId:string,report:RetainedReport,format:"xlsx"|"html"):Promise<void>{
 const artifact=report.exports[format];
 const response=await fetch(`/api/ontology/retained-reports/${encodeURIComponent(report.reference.proposal_id)}/exports/${format}?company_id=${encodeURIComponent(companyId)}`,{headers:{Authorization:`Bearer ${token}`},cache:"no-store"});
 if(!response.ok)throw Error(`Retained ${format.toUpperCase()} export unavailable (${response.status}).`);
 const bytes=await response.arrayBuffer();await verifyReportDownload(bytes,response.headers,artifact,report.reference);
 const url=URL.createObjectURL(new Blob([bytes],{type:artifact.media_type}));const anchor=document.createElement("a");anchor.href=url;anchor.download=artifact.filename;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
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
