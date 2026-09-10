import type {AnalysisProjection} from "@finai/contracts";
import {assertProjection} from "./semantic-analysis-state";
import {displayedAnalysisView,type SourceReviewTarget} from "./source-review-route";
import {journalSnapshot} from "./analysis-projection-identity";

/** The journal snapshot is independent of the original Function's valid/known times. */
export function acceptedJournalTarget(projection:AnalysisProjection,companyId:string,invocationId:string,snapshotAt:string):SourceReviewTarget {
 assertProjection(projection,{company_id:companyId,invocation_id:invocationId});
 const snapshot=journalSnapshot(snapshotAt);
 return {companyId,invocationId,journalSnapshot:snapshot,view:displayedAnalysisView(projection,companyId,snapshot)};
}
