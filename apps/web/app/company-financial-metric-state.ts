import type {AnalysisProjection,FinancialMetricRequest,FinancialMetricResult} from "@finai/contracts";
import {restorationInstant} from "./definition-restoration-time";

const uuid=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i,hash=/^[a-f0-9]{64}$/;
const keys=["debit_movement","credit_movement","net_movement"] as const;
const pin=(v:{resource_id:string;version_id:string;content_hash?:string}|null|undefined,hashed=false)=>Boolean(v&&uuid.test(v.resource_id)&&uuid.test(v.version_id)&&(!hashed||hash.test(v.content_hash??"")));
/** Cross-check the metric view against its independently guarded journal projection. No arithmetic. */
export function assertHomeFinancialMetrics(value:FinancialMetricResult,request:FinancialMetricRequest,projection:AnalysisProjection):void{
 const fail=()=>{throw Error("Financial movements do not match the exact company, source, journal snapshot and evidence.");};
 if(!value||value.contract!=="company-financial-metrics/1"||value.company_id!==request.company_id||value.invocation_id!==request.invocation_id||restorationInstant(value.snapshot_at)!==restorationInstant(request.snapshot_at)||value.reconciliation_receipt_hash!==projection.descriptor.receipt_hash||request.expected_reconciliation_sha256&&value.reconciliation_receipt_hash!==request.expected_reconciliation_sha256||request.expected_result_sha256&&value.result_sha256!==request.expected_result_sha256||value.current_use_authorized!==false||value.business_effect_authorized!==false||value.aggregation!=="SERVER_OWNED_VALUES_DO_NOT_SUM_HIERARCHY"||value.hierarchy_basis!=="COMPANY_AND_EXACT_LOCAL_ACCOUNT")fail();
 if(![value.source_sha256,value.source_receipt_hash,value.reconciliation_receipt_hash,value.implementation_sha256,value.result_sha256].every(v=>hash.test(v))||!pin(value.binding,true)||!pin(value.source_function,true)||value.source_function.resource_id!==projection.descriptor.function.resource_id||value.source_function.version_id!==projection.descriptor.function.version_id||value.source_function.content_hash!==projection.descriptor.function.content_hash)fail();
 const selectionKeys=["legal_entity_id","ledger_id","book_id","period_id","chart_id","currency_id","calendar_id"];
 if(!value.selection||Object.keys(value.selection).length!==selectionKeys.length||selectionKeys.some(k=>!pin(value.selection[k as keyof typeof value.selection]))||value.selection.legal_entity_id.resource_id!==request.company_id||value.selection.legal_entity_id.version_id!==projection.descriptor.company.version_id)fail();
 if(value.display_context!==undefined){
  if(!value.display_context||typeof value.display_context!=="object"||Array.isArray(value.display_context)||Object.keys(value.display_context).some(k=>!["ledger_id","book_id","period_id"].includes(k)))fail();
  for(const key of ["ledger_id","book_id","period_id"] as const){const entry=value.display_context[key],selected=value.selection[key];if(entry!==undefined&&(!entry||!pin(entry.reference)||entry.reference.resource_id!==selected.resource_id||entry.reference.version_id!==selected.version_id||entry.label!==null&&(typeof entry.label!=="string"||!entry.label.trim())))fail();}
 }
 if(!Array.isArray(value.definitions)||value.definitions.length!==3||new Set(value.definitions.map(d=>d.code)).size!==3||value.definitions.some(d=>!keys.includes(d.code)||d.definition_authority!=="CODE_DEFINED_NOT_PUBLISHED"||d.function_reference!=="finance.accepted-journal-movements/v1"||!pin(d.unit)||d.unit.resource_id!==value.selection.currency_id.resource_id||d.unit.version_id!==value.selection.currency_id.version_id))fail();
 if(!Array.isArray(value.nodes)||value.nodes.length<1||value.nodes.length>5001||new Set(value.nodes.map(n=>n.key)).size!==value.nodes.length||!Array.isArray(value.journals)||value.journals.length>5000)fail();
 const accountRows=value.nodes.slice(1).map(n=>n.analysis_row_key),accountSubjects=value.nodes.slice(1).map(n=>n.subject?.resource_id);
 if(new Set(accountRows).size!==accountRows.length||new Set(accountSubjects).size!==accountSubjects.length)fail();
 const root=value.nodes[0],company=projection.descriptor.company;
 if(root.kind!=="COMPANY_MOVEMENTS"||root.parent_key!==null||root.analysis_row_key!==null||root.subject.resource_id!==company.resource_id||root.subject.version_id!==company.version_id||root.subject.content_hash!==company.content_hash)fail();
 const journals=new Map(value.journals.map(j=>[j.journal.resource_id,j]));
 if(journals.size!==value.journals.length||value.journals.some(j=>!pin(j.journal)||!Array.isArray(j.lines)||j.lines.length!==2||j.lines.some(l=>!pin(l))||j.lines[0].resource_id===j.lines[1].resource_id||typeof j.source_coordinate!=="string"))fail();
 for(const node of value.nodes){
  if(!pin(node.subject,true)||!Array.isArray(node.source_coordinates)||!Array.isArray(node.journal_keys)||new Set(node.journal_keys).size!==node.journal_keys.length||node.journal_keys.some(k=>!journals.has(k))||node.source_coordinates.some(c=>!node.journal_keys.some(k=>journals.get(k)?.source_coordinate===c))||!node.metrics||Object.keys(node.metrics).length!==3)fail();
  for(const key of keys){const metric=node.metrics[key];if(!metric||(metric.state==="VALUE"?typeof metric.value!=="string"||!/^[-]?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(metric.value):metric.state!=="UNAVAILABLE"||metric.value!==null))fail();}
  if(node!==root){const row=projection.rows.find(r=>r.key===node.analysis_row_key);if(node.kind!=="ACCOUNT_MOVEMENTS"||node.parent_key!==root.key||!row||row.trace.resource_id!==node.subject.resource_id||row.trace.version_id!==node.subject.version_id||row.trace.content_hash!==node.subject.content_hash||keys.some(k=>node.metrics[k].state!=="VALUE"||node.metrics[k].value!==row.values[k]?.value))fail();}
 }
 if(!value.coverage||value.coverage.ledger_completeness!=="UNESTABLISHED"||!["UNAVAILABLE","PARTIAL","RECONCILED"].includes(value.coverage.state)||[value.coverage.source_rows,value.coverage.literal_source_rows,value.coverage.accepted_journals,value.coverage.unmatched_source_rows,value.coverage.excluded_source_rows,value.coverage.rejected_journals].some(n=>!Number.isSafeInteger(n)||n<0)||value.coverage.accepted_journals!==value.journals.length||value.coverage.state==="UNAVAILABLE"&&value.nodes.some(n=>keys.some(k=>n.metrics[k].state!=="UNAVAILABLE")))fail();
}
