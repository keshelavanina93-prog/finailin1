import type {AnalysisProjection} from "@finai/contracts";
import {restorationInstant} from "./definition-restoration-time";

/** Transport identity only; source invocation and journal snapshot are different projections. */
export function journalSnapshot(value:unknown):string {
 const instant=restorationInstant(value);
 if(!instant)throw Error("Accepted journal review requires an exact aware snapshot.");
 return instant;
}
export function projectionIdentity(invocationId:string,snapshot?:string):string {
 return snapshot===undefined?invocationId:`${invocationId}:accepted-journals:${journalSnapshot(snapshot)}`;
}
export function projectionEndpoint(snapshot?:string):string {
 return snapshot===undefined?"/api/ontology/analysis/project":`/api/ontology/company-journals/reconciliation/projection?snapshot_at=${encodeURIComponent(journalSnapshot(snapshot))}`;
}
export function assertProjectionTransport(projection:AnalysisProjection,snapshot?:string):void {
 if(snapshot===undefined)return;
 const expected=journalSnapshot(snapshot),returned=projection.descriptor.coverage?.filter(item=>item.label==="Snapshot");
 if(projection.descriptor.contract!=="semantic-analysis/2"||returned?.length!==1||restorationInstant(returned[0].value)!==expected)
  throw Error("Accepted journal review did not preserve its exact snapshot.");
}
