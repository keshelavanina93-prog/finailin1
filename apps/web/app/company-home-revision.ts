import type {AnalysisProjection,AnalysisRequest} from "@finai/contracts";
import {restorationInstant} from "./definition-restoration-time";

import {journalSnapshot,projectionIdentity,assertProjectionTransport} from "./analysis-projection-identity";

export type HomeAnalysisRevision={descriptorSha256:string;receiptHash:string;validAt:string;knownAt:string};
export type HomeAnalysisReference=
 | {kind:"LEGACY";invocationId:string;journalSnapshot?:never}
 | {kind:"EXACT";invocationId:string;revision:HomeAnalysisRevision;journalSnapshot?:string};
const hash=/^[a-f0-9]{64}$/;
const uuid=/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const invalid=()=>Error("Saved Home references are invalid. Clear them and pin the retained analyses again.");

export function homeRevision(value:unknown):HomeAnalysisRevision{
 if(!value||typeof value!=="object"||Array.isArray(value))throw invalid();
 const r=value as Record<string,unknown>;
 if(Object.keys(r).length!==4||typeof r.descriptorSha256!=="string"||!hash.test(r.descriptorSha256)||
  typeof r.receiptHash!=="string"||!hash.test(r.receiptHash)||typeof r.validAt!=="string"||
  typeof r.knownAt!=="string"||!restorationInstant(r.validAt)||!restorationInstant(r.knownAt))throw invalid();
 return {descriptorSha256:r.descriptorSha256,receiptHash:r.receiptHash,validAt:r.validAt,knownAt:r.knownAt};
}

/** Only historical string entries are legacy; a malformed exact entry can never become legacy. */
export function parseHomeAnalysisReferences(value:unknown):HomeAnalysisReference[]{
 if(!Array.isArray(value)||value.length>6)throw invalid();
 const refs=value.map((entry):HomeAnalysisReference=>{
  if(typeof entry==="string"&&uuid.test(entry))return {kind:"LEGACY",invocationId:entry};
  if(!entry||typeof entry!=="object"||Array.isArray(entry)||Object.keys(entry).some(key=>!["invocationId","revision","journalSnapshot"].includes(key))||
   typeof entry.invocationId!=="string"||!uuid.test(entry.invocationId)||!("revision" in entry))throw invalid();
  return {kind:"EXACT",invocationId:entry.invocationId,revision:homeRevision(entry.revision),...("journalSnapshot" in entry?{journalSnapshot:journalSnapshot(entry.journalSnapshot)}:{})};
 });
 if(new Set(refs.map(ref=>projectionIdentity(ref.invocationId,ref.journalSnapshot))).size!==refs.length)throw invalid();
 return refs;
}
export function encodedHomeReferences(references:HomeAnalysisReference[]):string{
 return JSON.stringify(references.map(ref=>ref.kind==="LEGACY"?ref.invocationId:{invocationId:ref.invocationId,revision:ref.revision,...(ref.journalSnapshot===undefined?{}:{journalSnapshot:ref.journalSnapshot})}));
}
export function homeAnalysisRequest(reference:HomeAnalysisReference,companyId:string):AnalysisRequest{
 return {company_id:companyId,invocation_id:reference.invocationId,
  ...(reference.kind==="EXACT"?{descriptor_sha256:reference.revision.descriptorSha256}:{})};
}
/** This augments the shared projection guard; it does not grant financial authority. */
export function assertHomeRevision(projection:AnalysisProjection,reference:HomeAnalysisReference):void{
 assertProjectionTransport(projection,reference.journalSnapshot);
 if(reference.kind==="LEGACY")return;
 const expected=reference.revision,d=projection.descriptor;
 if(projection.descriptor_sha256!==expected.descriptorSha256||d.receipt_hash!==expected.receiptHash||
  d.valid_at!==expected.validAt||d.known_at!==expected.knownAt)
  throw Error("The pinned analysis revision no longer matches. Its exact reference remains saved; reopen the original source review.");
}

/** Placement depends on retained transport references, never inferred financial values. */
export function homeReferencesForGroup(references:HomeAnalysisReference[],group?:"sources"|"journals"):HomeAnalysisReference[]{
 return references.filter(ref=>group===undefined||(group==="journals"?ref.journalSnapshot!==undefined:ref.journalSnapshot===undefined));
}
