import type {CanonicalResource} from "@finai/contracts";
import type {Context} from "./company-workspace";
import {restorationInstant} from "./definition-restoration-time";

type Snapshot={context:Context;validAt:string;knownAt:string};
export type CompanyCutoffs={validAt:string;knownAt:string};
const instant=(value:unknown):value is string=>typeof value==="string"&&value.length<=40&&restorationInstant(value)!==null;
/** Only explicit timezone-aware references can restore a historical company view. */
export function companyCutoffs(value:unknown):CompanyCutoffs|null {
 const candidate=value as Partial<CompanyCutoffs>|null;
 return candidate&&instant(candidate.validAt)&&instant(candidate.knownAt)?{validAt:candidate.validAt,knownAt:candidate.knownAt}:null;
}
export function restoreCompanyCutoffs(value:unknown,companyId:string):CompanyCutoffs|null {
 const saved=value as {companyId?:unknown;cutoffs?:unknown}|null;
 return saved?.companyId===companyId?companyCutoffs(saved.cutoffs):null;
}
/** Retain the server's company snapshot; a response for another company cannot enter this view. */
export function companySnapshot(value:unknown,companyId:string,requested:CompanyCutoffs|null=null):Snapshot {
 const response=value as {context?:Context;valid_at?:unknown;known_at?:unknown}|null;
 const context=response?.context;
 if(!context||context.company?.resource_id!==companyId||context.company.object_type!=="LegalEntity"||context.company.authority_state!=="APPROVED"||context.company.evidence_class==="REFERENCE_TEMPLATE"||!instant(response?.valid_at)||!instant(response?.known_at)||![context.relationships,context.structural_resources,context.ledgers,context.accounting_sources,context.licence_evidence,context.disclosures,context.dimensions].every(Array.isArray))throw Error("Company context did not match the selected legal entity and exact snapshot.");
 if(requested&&(!companyCutoffs(requested)||restorationInstant(response.valid_at)!==restorationInstant(requested.validAt)||restorationInstant(response.known_at)!==restorationInstant(requested.knownAt)))throw Error("Company response did not preserve the requested effective and known-time snapshot.");
 return {context,validAt:response.valid_at,knownAt:response.known_at};
}

export type Company360Descriptor={
 contract:"g8-company-360-view/1";company:CanonicalResource;validAt:string;knownAt:string;
 connections:Context["relationships"];operatingResources:CanonicalResource[];
 sources:Context["accounting_sources"];ledgers:Context["ledgers"];licences:Context["licence_evidence"];
 reportedRelationships:number;
};
/** Presentation composition only: relationships and eligibility remain server-owned. */
export function company360Descriptor(context:Context,validAt:string,knownAt:string):Company360Descriptor {
 const operatingTypes=new Set(["Facility","OperationalNetwork","AssetPortfolio","BusinessUnit","LicensedOperator"]);
 const connected=new Set(context.relationships.flatMap(row=>[row.source.version_id,row.target.version_id]));
 return {contract:"g8-company-360-view/1",company:context.company,validAt,knownAt,
  connections:context.relationships,
  operatingResources:context.structural_resources.filter(node=>operatingTypes.has(node.object_type)&&connected.has(node.version_id)),
  sources:context.accounting_sources,ledgers:context.ledgers,licences:context.licence_evidence,
  reportedRelationships:context.disclosures.length};
}
