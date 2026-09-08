import type {ResourceProposalDetail} from "@finai/contracts";
import type {ValidationRead,ValidationRunRequest} from "@g8/ontology-client";
export type WorkFamily="source"|"ontology"|"monitor"|"build"|"validation"|"unsupported";
export type ActionItem={workflow_id:string;family:WorkFamily;title:string;publication_review_state?:"NOT_REQUESTED"|"PENDING"|"APPROVED"|"REJECTED"|"CANCELLED";request_id?:string;validation_request?:ValidationRunRequest;transformation?:{resource_id:string;version_id:string;content_hash?:string};company_id:string|null;created_at:string;period:string|null;currency:string|null;company_binding:string};
export type WorkEvent={event_id:string;created_at:string;node?:string;state?:string;command?:string;reason?:string;actor_id?:string;document_id?:string;document?:{document_id:string;filename:string;sha256:string};assessment_id?:string};
export type WorkRun={workflow_id?:string;operation_id?:string;actor_id?:string;state?:string;runtime_status?:string;runtime?:{state:string;next_checks?:string[]};execution?:{state:string};source_health?:string;freshness?:string;
 request?:{report?:{receipt_ids:string[]};document_id?:string};definition:{version:string;nodes?:{id:string;depends_on:string[];function:string}[]};events:WorkEvent[];
 proposal?:ResourceProposalDetail|null;
 publications?:{publication_id:string;generation:number;authority:string;outputs:{slot:string;sha256:string}[]}[]};
export const workState=(family:WorkFamily,run:WorkRun)=>family==="monitor"?run.runtime?.state??"UNOBSERVABLE":family==="ontology"||family==="validation"?run.state??"UNOBSERVABLE":run.execution?.state??"UNOBSERVABLE";
export function commands(family:WorkFamily,run:WorkRun,permissions:readonly string[],actor:string):string[]{
 const state=workState(family,run);
 if(state==="UNOBSERVABLE")return [];
 if(family==="monitor")return permissions.includes("ingest")?(state==="ENABLED"?["pause"]:state==="PAUSED"?["resume"]:[]):[];
 if(family==="ontology")return state==="PREPARED"&&permissions.includes("ontology_propose")?["resume"]:[];
 if(family!=="source")return [];
 const controls=permissions.includes("ingest")?(state==="PAUSED"?["resume","cancel"]:state==="WAITING_REVIEW"?["pause","retry","cancel"]:state==="FAILED"?["retry","cancel"]:[]):[];
 if(state==="WAITING_REVIEW"&&permissions.includes("review")&&run.actor_id!==actor)controls.push("complete");
 return controls;
}
export const workPath=(item:ActionItem)=>item.family==="validation"?`ontology/external/validation/runs/${validationRequestId(item)}`:item.family==="build"?`ontology/transformations/runs/${item.request_id}`:item.family==="monitor"?`ontology/regulation/monitors/${item.workflow_id}`:item.family==="ontology"?`ontology/operations/${item.workflow_id}`:`workspace/workflows/${item.workflow_id}`;
export function validationRequestId(item:Pick<ActionItem,"request_id"|"workflow_id">):string {
 if(!item.request_id||!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(item.request_id)||item.workflow_id!==`ontology-validation:${item.request_id}`)throw Error("The retained validation reference is incomplete or inconsistent.");
 return item.request_id;
}
export function validationSummary(run:Pick<ValidationRead,"state"|"report">):{title:string;detail:string;tone:"neutral"|"good"|"warning"|"bad"}{
 if(run.state==="CANCELLED")return {title:"Validation cancelled",detail:"This request was cancelled. Any retained observation remains historical evidence.",tone:"neutral"};
 switch(run.report?.outcome){
 case "CONFORMS":return {title:"Selected checks passed",detail:"The evaluated constraints passed for this retained selection. Accounting authority and certification require their own review.",tone:"good"};
 case "VIOLATES":return {title:"Constraints need investigation",detail:"Review the validation evidence and its data and shape releases before proposing a change.",tone:"warning"};
 case "NOT_EVALUATED":return {title:"No substantive checks completed",detail:"The selection produced no evaluated coverage. No conformance conclusion is available.",tone:"warning"};
 case "REFUSED":return {title:"Selection could not be evaluated",detail:"The validator refused this selection. Inspect the retained refusal before preparing another request.",tone:"warning"};
 default:return {title:"Awaiting a retained result",detail:"No completed validation report has been retained. Worker activity is shown separately below.",tone:"neutral"};
 }
}
export function canProposeValidationReport(run:Pick<ValidationRead,"state"|"report"|"publication_id">,permissions:readonly string[]):boolean {
 return run.state==="PUBLISHED"&&run.report!==null&&Boolean(run.publication_id)&&["read","ontology_read","ontology_propose"].every(p=>permissions.includes(p));
}
export const stepLabel=(value:string)=>({hierarchy:"Understand source structure",coverage:"Check source coverage",review:"Independent review",publication:"Retain complete results"}[value]??value.replaceAll("_"," "));
