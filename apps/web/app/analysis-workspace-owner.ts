import {sourceReviewTarget} from "./source-review-route";

export type AnalysisOwner="source-review"|"finance";
type Scope={companyId:string;invocationId:string;journalSnapshot?:string};
export function analysisViewParameter(owner:AnalysisOwner):string {
 return owner==="finance"?"finance_analysis_view":"analysis_view";
}
/** A hidden consumer must never read or rewrite the foreground route's view. */
export function ownsAnalysisHistory(url:URL,scope:Scope,owner:AnalysisOwner,active:boolean):boolean {
 if(!active)return false;
 if(owner==="finance")return url.pathname==="/";
 const target=sourceReviewTarget(url.pathname);
 return target?.companyId===scope.companyId&&target.invocationId===scope.invocationId&&target.journalSnapshot===scope.journalSnapshot;
}
