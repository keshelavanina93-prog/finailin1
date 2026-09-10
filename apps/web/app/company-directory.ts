import type {CanonicalResource} from "@finai/contracts";

export type CompanyDirectory={contract:"company-directory/1";companies:{company:CanonicalResource;basis:"EXPLICIT_COMPANY_DECLARATION"|"CONFIGURED_WORKSPACE";workspace_ids:string[]}[];source_identities:CanonicalResource[];reported_parties:CanonicalResource[];unclassified_identities:CanonicalResource[]};
const uuid=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i,hash=/^[a-f0-9]{64}$/;
function node(value:unknown):value is CanonicalResource {if(!value||typeof value!=="object")return false;const v=value as CanonicalResource;return typeof v.resource_id==="string"&&uuid.test(v.resource_id)&&typeof v.version_id==="string"&&uuid.test(v.version_id)&&typeof v.content_hash==="string"&&hash.test(v.content_hash)&&typeof v.display_name==="string"&&typeof v.object_type==="string"&&typeof v.evidence_class==="string"&&Boolean(v.attributes)&&typeof v.attributes==="object"&&!Array.isArray(v.attributes);}
/** Consume the server classification; legacy index collections never grant selection. */
export function companyDirectory(index:unknown):CompanyDirectory|null {
 if(!index||typeof index!=="object")return null;const d=(index as {company_directory?:CompanyDirectory}).company_directory;
 if(!d||d.contract!=="company-directory/1"||!Array.isArray(d.companies)||![d.source_identities,d.reported_parties,d.unclassified_identities].every(rows=>Array.isArray(rows)&&rows.every(node)))return null;
 const seen=new Set<string>();
 for(const entry of d.companies){if(!entry||!node(entry.company)||entry.company.object_type!=="LegalEntity"||entry.company.authority_state!=="APPROVED"||!["USER_ASSERTED","SOURCE_BOUND"].includes(entry.company.evidence_class)||!["EXPLICIT_COMPANY_DECLARATION","CONFIGURED_WORKSPACE"].includes(entry.basis)||!Array.isArray(entry.workspace_ids)||entry.workspace_ids.some(id=>typeof id!=="string"||!uuid.test(id))||new Set(entry.workspace_ids).size!==entry.workspace_ids.length||entry.basis==="CONFIGURED_WORKSPACE"&&!entry.workspace_ids.length||entry.basis==="EXPLICIT_COMPANY_DECLARATION"&&entry.company.evidence_class!=="USER_ASSERTED"||seen.has(entry.company.resource_id))return null;seen.add(entry.company.resource_id);}
 const reviewed=new Set<string>();
 for(const rows of [d.source_identities,d.reported_parties]){const ids=new Set<string>();for(const item of rows){if(seen.has(item.resource_id)||ids.has(item.resource_id))return null;ids.add(item.resource_id);reviewed.add(item.resource_id);}}
 const unclassified=new Set<string>();for(const item of d.unclassified_identities){if(seen.has(item.resource_id)||reviewed.has(item.resource_id)||unclassified.has(item.resource_id))return null;unclassified.add(item.resource_id);}
 return d;
}
export function selectableCompanies(index:unknown):CanonicalResource[]{return companyDirectory(index)?.companies.map(entry=>entry.company)??[];}

export const readCompanyDirectory=companyDirectory;
