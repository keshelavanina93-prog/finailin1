import type {CompanyJournalReviewItem,CompanyJournalReviews} from "@finai/contracts";
import {restorationInstant} from "./definition-restoration-time";

const uuid=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i;
export const journalReviewLabels={PREPARED:"Prepared",PENDING_REVIEW:"Awaiting review",PUBLISHED:"Accepted",REJECTED:"Rejected"};
export type JournalReviewFilter="ALL"|CompanyJournalReviewItem["state"];
export function journalReviewKey(item:CompanyJournalReviewItem):string{return `${item.request_id}:${item.proposal_id}`;}
export function assertCompanyJournalReviews(raw:unknown,companyId:string):asserts raw is CompanyJournalReviews {
 const value=raw as CompanyJournalReviews;
 if(!value||value.authority!=="CURRENT_CANONICAL_JOURNAL_REVIEW"||!restorationInstant(value.observed_at)||value.limit!==25||typeof value.truncated!=="boolean"||!["AVAILABLE","UNAVAILABLE"].includes(value.state)||!Array.isArray(value.items)||value.items.length>25||value.state==="AVAILABLE"&&value.reason!==null||value.state==="UNAVAILABLE"&&(typeof value.reason!=="string"||!value.reason.trim()||value.items.length!==0))throw Error("Journal review work is unavailable from this server. No empty-queue or review decision has been assumed.");
 if(value.items.some(item=>!item||item.company_id!==companyId||![item.request_id,item.proposal_id,item.invocation_id].every(id=>typeof id==="string"&&uuid.test(id))||item.basis!=="EXPLICIT_JOURNAL_PRODUCTION_REQUEST"||!Object.hasOwn(journalReviewLabels,item.state)||!restorationInstant(item.created_at)||typeof item.coordinate!=="string"||!item.coordinate.trim()||item.coordinate.length>512||typeof item.title!=="string"||typeof item.reason!=="string")||new Set(value.items.map(journalReviewKey)).size!==value.items.length)throw Error("Journal review work did not preserve its exact company and canonical request/proposal references.");
}
export function rankJournalReviews(items:CompanyJournalReviewItem[],filter:JournalReviewFilter,query:string):CompanyJournalReviewItem[]{
 const priority={PENDING_REVIEW:0,PREPARED:1,REJECTED:2,PUBLISHED:3},search=query.trim().toLocaleLowerCase();
 return items.filter(item=>(filter==="ALL"||item.state===filter)&&(!search||`${item.title} ${item.coordinate} ${item.reason}`.toLocaleLowerCase().includes(search))).sort((a,b)=>priority[a.state]-priority[b.state]||Date.parse(b.created_at)-Date.parse(a.created_at)||journalReviewKey(a).localeCompare(journalReviewKey(b)));
}
export function journalReviewProposal(item:CompanyJournalReviewItem):string|null{return item.state==="PREPARED"?null:item.proposal_id;}
