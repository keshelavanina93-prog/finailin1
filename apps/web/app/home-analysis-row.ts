import type {AnalysisProjection} from "@finai/contracts";
import {assertProjection,parseView} from "./semantic-analysis-state";
import {assertHomeRevision,homeAnalysisRequest,type HomeAnalysisReference} from "./company-home-revision";
import {displayedAnalysisView,type SourceReviewTarget} from "./source-review-route";

/** Request evidence for an existing displayed row; the destination rechecks its contributor. */
export function homeAnalysisRowTarget(projection:AnalysisProjection,reference:HomeAnalysisReference,companyId:string,rowKey:string,contributorIndex=0):SourceReviewTarget|null {
 assertProjection(projection,homeAnalysisRequest(reference,companyId));
 assertHomeRevision(projection,reference);
 const displayed=displayedAnalysisView(projection,companyId,reference.journalSnapshot);
 const row=projection.rows.find(item=>item.key===rowKey);
 if(!row)throw Error("This row is not part of the displayed retained analysis.");
 if(!Number.isSafeInteger(contributorIndex)||contributorIndex<0)throw Error("The requested contributor is invalid.");
 if(row.contributor_count===0)return null;
 if(contributorIndex>=row.contributor_count)throw Error("The requested contributor is unavailable for this retained row.");
 const view=parseView(JSON.stringify({...displayed,request:{...displayed.request,selected_row:row.key,contributor_index:contributorIndex},pane:"evidence",workspace:{grid:{widths:{},pinned:[],focus:{row:row.key,column:projection.descriptor.fields[0].key},left:0,search:""},dock:"right",collapsed:false,size:340}}),companyId,reference.invocationId,reference.journalSnapshot);
 if(!view)throw Error("This row does not contain a valid exact review reference.");
 return {companyId,invocationId:reference.invocationId,...(reference.journalSnapshot===undefined?{}:{journalSnapshot:reference.journalSnapshot}),view};
}
