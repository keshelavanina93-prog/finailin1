import type { CanonicalResource, IntakeItem, ProposalSummary, WorkspaceSummary } from "@finai/contracts";

export type Loadable<T> = { data: T | null; error: string | null };
export type Graph = { resources: CanonicalResource[]; bounded: boolean };
export type Binding = { binding: CanonicalResource | null; canonical_references: Record<string, {resource_id: string; version_id: string}> };
export type Readiness = { status: string; database: string; schema: string; evidence_store: string };
export type Snapshot = {
  summary: Loadable<WorkspaceSummary>; evidence: Loadable<IntakeItem[]>; graph: Loadable<Graph>;
  proposals: Loadable<ProposalSummary[]>; context: Loadable<Binding>; readiness: Loadable<Readiness>;
};
export type WorkItem = { id: string; kind: "evidence" | "proposal"; title: string; state: string; reason: string; date: string; severity: number };
export const emptySnapshot = (): Snapshot => ({summary: {data:null,error:null}, evidence: {data:null,error:null}, graph: {data:null,error:null}, proposals: {data:null,error:null}, context: {data:null,error:null}, readiness: {data:null,error:null}});
export function workItems(evidence: IntakeItem[], proposals: ProposalSummary[]): WorkItem[] {
  return [
    ...evidence.map(item => ({id:item.receipt_id, kind:"evidence" as const, title:item.filename, state:item.review_state, date:item.ingested_at,
      severity:item.review_state === "PENDING" ? (item.reject_count ? 0 : 1) : 3,
      reason:item.reject_count ? `${item.reject_count} source rows failed validation. Inspect the retained evidence.` : item.review_state === "PENDING" ? "An independent review is required before these objects can be accepted." : item.is_current ? "Current accepted source version. Financial certification is separate." : "Retained historical decision; inspect its version and evidence."})),
    ...proposals.map(item => ({id:item.proposal_id,kind:"proposal" as const,title:item.title,state:item.decision,date:item.created_at,
      severity:item.decision === "PENDING" ? 1 : 3,reason:item.rationale})),
  ].sort((a,b) => a.severity-b.severity || b.date.localeCompare(a.date) || a.id.localeCompare(b.id));
}
export function acceptedCompanies(resources: CanonicalResource[]) {
  return resources.filter(resource => ["LegalEntity","Company"].includes(resource.object_type) && resource.authority_state === "APPROVED" && resource.evidence_class === "SOURCE_BOUND");
}
export function belongsToCompany(resource: CanonicalResource, companyId: string) {
  return resource.resource_id === companyId || ["legal_entity_id","company_id","owner_id"].some(key => resource.attributes[key] === companyId);
}
export const readable = (value: string) => value.replaceAll("_", " ").replace(/([a-z])([A-Z])/g,"$1 $2");
