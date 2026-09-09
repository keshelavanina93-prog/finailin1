import test from "node:test";
import assert from "node:assert/strict";
import {loadTypeScript} from "./load-typescript.mjs";
const {companyWorkflowQueueItem,assertCompanyWorkflowRun}=await loadTypeScript(new URL("../app/company-workflow-review.ts",import.meta.url));
const company="00000000-0000-4000-8000-000000000001",proposal="00000000-0000-4000-8000-000000000002",workflow=`opa_${"a".repeat(64)}`;
const reference={company:{resource_id:company},workflowId:workflow,proposalId:proposal};
const item={workflow_id:workflow,family:"ontology",company_id:company,company_binding:"EXPLICIT_INVOCATION"};
const run={operation_id:workflow,prepared_proposal_id:proposal,state:"PUBLISHED",definition:{version:"ontology-action/1"},proposal:{proposal:{proposal_id:proposal},decision:"APPROVED"}};
test("exact bound queue membership is required before canonical operation detail",()=>{
 assert.equal(companyWorkflowQueueItem([item],reference),item);
 for(const items of [[],[item,item],[{...item,company_id:null}],[{...item,company_id:"foreign"}],[{...item,company_binding:"INFERRED"}],[{...item,family:"source"}],[{...item,workflow_id:`opa_${"b".repeat(64)}`}]] )assert.throws(()=>companyWorkflowQueueItem(items,reference));
});
test("current operation and submitted proposal retain the selected identity; prepared never claims submission",()=>{
 assert.doesNotThrow(()=>assertCompanyWorkflowRun(run,reference));
 assert.doesNotThrow(()=>assertCompanyWorkflowRun({...run,state:"PREPARED",proposal:null},reference));
 assert.doesNotThrow(()=>assertCompanyWorkflowRun({...run,state:"PENDING_REVIEW",proposal:{...run.proposal,decision:null}},reference));
 assert.doesNotThrow(()=>assertCompanyWorkflowRun({...run,state:"REJECTED",proposal:{...run.proposal,decision:"REJECTED"}},reference));
 for(const patch of [{operation_id:"foreign"},{prepared_proposal_id:"foreign"},{proposal:{proposal:{proposal_id:"foreign"}}},{state:"PUBLISHED",proposal:null},{state:"CURRENT_LICENCE"},{definition:{version:"wrong"}},{state:"PREPARED"},{state:"PENDING_REVIEW"},{state:"REJECTED"},{proposal:{proposal:{proposal_id:proposal},decision:"REJECTED"}}])assert.throws(()=>assertCompanyWorkflowRun({...run,...patch},reference));
});
