import type {ResourceProposalDetail} from "@finai/contracts";
export type WorkFamily="source"|"ontology"|"monitor"|"unsupported";
export type ActionItem={workflow_id:string;family:WorkFamily;title:string;company_id:string|null;created_at:string;period:string|null;currency:string|null;company_binding:string};
export type WorkEvent={event_id:string;created_at:string;node?:string;state?:string;command?:string;reason?:string;actor_id?:string;document_id?:string;document?:{document_id:string;filename:string;sha256:string};assessment_id?:string};
export type WorkRun={workflow_id?:string;operation_id?:string;actor_id?:string;state?:string;runtime_status?:string;runtime?:{state:string;next_checks?:string[]};execution?:{state:string};source_health?:string;freshness?:string;
 request?:{report?:{receipt_ids:string[]};document_id?:string};definition:{version:string;nodes?:{id:string;depends_on:string[];function:string}[]};events:WorkEvent[];
 proposal?:ResourceProposalDetail|null;
 publications?:{publication_id:string;generation:number;authority:string;outputs:{slot:string;sha256:string}[]}[]};
export const workState=(family:WorkFamily,run:WorkRun)=>family==="monitor"?run.runtime?.state??"UNOBSERVABLE":family==="ontology"?run.state??"UNOBSERVABLE":run.execution?.state??"UNOBSERVABLE";
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
export const workPath=(item:ActionItem)=>item.family==="monitor"?`ontology/regulation/monitors/${item.workflow_id}`:item.family==="ontology"?`ontology/operations/${item.workflow_id}`:`workspace/workflows/${item.workflow_id}`;
export const stepLabel=(value:string)=>({hierarchy:"Understand source structure",coverage:"Check source coverage",review:"Independent review",publication:"Retain complete results"}[value]??value.replaceAll("_"," "));
