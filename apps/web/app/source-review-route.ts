import type {AnalysisProjection} from "@finai/contracts";
import {assertProjection,parseView,type AnalysisView} from "./semantic-analysis-state";

import {journalSnapshot,assertProjectionTransport} from "./analysis-projection-identity";

export type SourceReviewTarget={companyId:string;invocationId:string;journalSnapshot?:string;view?:AnalysisView};
const uuid="[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}";
const route=new RegExp(`^/source-review/(${uuid})/(${uuid})(?:/accepted-journals/([^/]+))?/?$`,"i");
export function sourceReviewTarget(pathname:string):SourceReviewTarget|null {
 const match=route.exec(pathname);
 try{return match?{companyId:match[1],invocationId:match[2],...(match[3]===undefined?{}:{journalSnapshot:journalSnapshot(decodeURIComponent(match[3]))})}:null;}catch{return null;}
}
/** Invalid review-family URLs must never resolve to the remembered business workspace. */
export function sourceReviewRouteRefused(pathname:string):boolean {
 return (pathname==="/source-review"||pathname.startsWith("/source-review/"))&&sourceReviewTarget(pathname)===null;
}
export function sourceReviewPath(target:SourceReviewTarget):string {
 const path=`/source-review/${target.companyId}/${target.invocationId}${target.journalSnapshot===undefined?"":`/accepted-journals/${encodeURIComponent(journalSnapshot(target.journalSnapshot))}`}`;
 if(!sourceReviewTarget(path))throw Error("Source review requires exact company and result references.");
 return path;
}
/** Existing saved-view contract carries revision, receipt and time without copying row values. */
export function displayedAnalysisView(projection:AnalysisProjection,companyId:string,snapshot?:string):AnalysisView {
 assertProjection(projection,{...projection.request,company_id:companyId});
 assertProjectionTransport(projection,snapshot);
 const d=projection.descriptor;
 const view=parseView(JSON.stringify({version:1,...(snapshot===undefined?{}:{journalSnapshot:journalSnapshot(snapshot)}),request:{...projection.request,descriptor_sha256:projection.descriptor_sha256,filters:projection.request.filters??[],group_by:projection.request.group_by??null,selected_row:projection.request.selected_row??null,contributor_index:projection.request.contributor_index??0},valid_at:d.valid_at,known_at:d.known_at,receipt_hash:d.receipt_hash,columns:d.fields.map(field=>field.key),visual:false,pane:"evidence",scroll:0}),companyId,d.invocation_id,snapshot);
 if(!view)throw Error("The displayed analysis does not contain an exact review reference.");
 return view;
}
export function sourceReviewUrl(target:SourceReviewTarget,current:URL):URL {
 const url=new URL(current);url.pathname=sourceReviewPath(target);url.searchParams.delete("analysis_view");
 if(target.view!==undefined){
  const view=parseView(JSON.stringify(target.view),target.companyId,target.invocationId,target.journalSnapshot);
  if(!view)throw Error("The exact source review reference is invalid or belongs to another result.");
  url.searchParams.set("analysis_view",JSON.stringify(view));
 }
 return url;
}
