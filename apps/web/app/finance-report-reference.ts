export type FinanceReportReference={invocationId:string;companyId:string;scopeId:string;documentId:string};
const record=(value:unknown):value is Record<string,unknown>=>!!value&&typeof value==="object"&&!Array.isArray(value);
const identifier=(value:unknown):value is string=>typeof value==="string"&&value.length>0;
/** Recognize a retained financial result without interpreting or recomputing its amounts. */
export function financeReportReference(value:unknown):FinanceReportReference|null {
  if(!record(value)||value.status!=="SUCCEEDED"||!identifier(value.invocation_id)||!record(value.output))return null;
  const output=value.output,source=output.source_document;
  if(output.contract!=="function-result/1"||output.coverage!=="RETAINED_SOURCE_POSTINGS_WITH_EXPLICIT_EXCLUSIONS"||output.authority!=="GUARDED_POSTED_MOVEMENT_ANALYSIS"||output.current_use_authorized!==false||output.business_effect_authorized!==false||!record(output.posted_movements)||!record(source)||!record(source.scope)||!identifier(source.company_id)||!identifier(source.document_id)||!identifier(source.scope.resource_id))return null;
  return {invocationId:value.invocation_id,companyId:source.company_id,scopeId:source.scope.resource_id,documentId:source.document_id};
}
