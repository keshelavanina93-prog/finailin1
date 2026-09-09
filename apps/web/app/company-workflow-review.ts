import type {ActionItem,WorkRun} from "./action-model";
import type {CompanyWorkflowReference} from "./journal-review-handoff";
/** Queue membership is the operation's explicit company attribution; detail has no company field. */
export function companyWorkflowQueueItem(items:ActionItem[],reference:CompanyWorkflowReference):ActionItem {
 const matches=items.filter(item=>item.workflow_id===reference.workflowId);
 const item=matches[0];
 if(matches.length!==1||item.company_id!==reference.company.resource_id||!["EXPLICIT_INVOCATION","EXPLICIT_RETAINED_EXCEPTION"].includes(item.company_binding)||item.family!=="ontology")throw Error("The selected workflow is unavailable in this company's current explicitly bound queue. No other work has been substituted.");
 return item;
}
export function assertCompanyWorkflowRun(run:WorkRun&{prepared_proposal_id?:string},reference:CompanyWorkflowReference):void {
 const decision=run.proposal?.decision;
 const investigation=run.definition?.kind==="SOURCE_EXCEPTION_INVESTIGATION";
 const consistent=run.state==="PREPARED"?run.proposal===null:run.state==="PENDING_REVIEW"?Boolean(run.proposal)&&decision===null:run.state==="PUBLISHED"?decision==="APPROVED":run.state==="REJECTED"?decision==="REJECTED":run.state==="PUBLICATION_UNAVAILABLE"?investigation&&decision==="APPROVED"&&run.publication===null:false;
 if(run.definition?.version!=="ontology-action/1"||!consistent||!["PREPARED","PENDING_REVIEW","PUBLISHED","REJECTED","PUBLICATION_UNAVAILABLE"].includes(run.state??"")||(run.state!=="PREPARED"&&!run.proposal)||run.operation_id!==reference.workflowId||run.prepared_proposal_id!==reference.proposalId||(run.proposal&&run.proposal.proposal.proposal_id!==reference.proposalId))throw Error("The operation or retained proposal does not match the selected company work reference.");
 if(investigation){
  if(run.definition.company_id!==reference.company.resource_id)throw Error("The investigation belongs to a different company.");
  if(run.definition.operation==="RESOLVE"){
   const d=run.definition,matched=d.matched_exception_run_id;
   if(!matched||!/^fcr_[a-f0-9]{64}$/.test(matched)||!d.exception_run_id||matched===d.exception_run_id||!d.prior_finding||!d.prior_investigation)throw Error("The resolution lacks exact original and matched evidence references.");
   if(run.proposal)for(const kind of ["Finding","Investigation"] as const){const prior=kind==="Finding"?d.prior_finding:d.prior_investigation,mutations=run.proposal.proposal.mutations.filter(m=>m.object_type===kind);if(mutations.length!==1||mutations[0].resource_id!==prior.resource_id||mutations[0].expected_version_id!==prior.version_id)throw Error("Resolution does not preserve the selected pair and exact prior heads.");}
  }
  if(run.state==="PUBLISHED")for(const kind of ["Finding","Investigation"] as const){
   const pin=run.publication?.[kind==="Finding"?"finding":"investigation"],mutations=run.proposal?.proposal.mutations.filter(m=>m.object_type===kind)??[];
   if(!pin||mutations.length!==1||pin.resource_id!==mutations[0].resource_id||!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(pin.version_id)||!/^[a-f0-9]{64}$/.test(pin.content_hash))throw Error("Exact investigation publication is unavailable.");
  }
 }
}
