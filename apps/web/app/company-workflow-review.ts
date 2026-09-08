import type {ActionItem,WorkRun} from "./action-model";
import type {CompanyWorkflowReference} from "./journal-review-handoff";
/** Queue membership is the operation's explicit company attribution; detail has no company field. */
export function companyWorkflowQueueItem(items:ActionItem[],reference:CompanyWorkflowReference):ActionItem {
 const matches=items.filter(item=>item.workflow_id===reference.workflowId);
 const item=matches[0];
 if(matches.length!==1||item.company_id!==reference.company.resource_id||item.company_binding!=="EXPLICIT_INVOCATION"||item.family!=="ontology")throw Error("The selected workflow is unavailable in this company's current explicitly bound queue. No other work has been substituted.");
 return item;
}
export function assertCompanyWorkflowRun(run:WorkRun&{prepared_proposal_id?:string},reference:CompanyWorkflowReference):void {
 const decision=run.proposal?.decision;
 const consistent=run.state==="PREPARED"?run.proposal===null:run.state==="PENDING_REVIEW"?Boolean(run.proposal)&&decision===null:run.state==="PUBLISHED"?decision==="APPROVED":run.state==="REJECTED"?decision==="REJECTED":false;
 if(run.definition?.version!=="ontology-action/1"||!consistent||!["PREPARED","PENDING_REVIEW","PUBLISHED","REJECTED"].includes(run.state??"")||(run.state!=="PREPARED"&&!run.proposal)||run.operation_id!==reference.workflowId||run.prepared_proposal_id!==reference.proposalId||(run.proposal&&run.proposal.proposal.proposal_id!==reference.proposalId))throw Error("The operation or retained proposal does not match the selected company work reference.");
}
