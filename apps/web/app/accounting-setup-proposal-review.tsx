import {useId} from "react";
import type {ResourceProposalDetail} from "@finai/contracts";
import {displayName} from "./display-name";
import "./accounting-setup-proposal-review.css";

const record=(value:unknown):Record<string,unknown>=>value!==null&&typeof value==="object"&&!Array.isArray(value)?value as Record<string,unknown>:{};
const labels:Record<string,string>={Ledger:"Ledger",AccountingBook:"Accounting book",FiscalCalendar:"Fiscal calendar",FiscalPeriod:"Fiscal period",Currency:"Currency"};
const fields:Record<string,string>={code:"Code",legal_entity_id:"Company",chart_id:"Local chart",calendar_id:"Calendar",currency_id:"Currency",ledger_id:"Ledger",starts_on:"Starts on",ends_on:"Ends on",minor_units:"Minor units"};

export default function AccountingSetupProposalReview({detail}:{detail:ResourceProposalDetail}) {
 const prefix=useId();
 const proposal=detail.proposal;
 if(proposal.request_binding?.operation!=="source-accounting-setup/1")return null;
 const mutations=detail.proposal.mutations;
 const sourceVersions=record(proposal.source_versions);
 const selections=mutations.filter(item=>item.object_type in labels);
 return <section className="accounting-setup-review" aria-label="Accounting structure proposed for review">
  <header><h3>Proposed accounting structure</h3><strong>User asserted configuration</strong><p>Approval establishes the proposed accounting structure. They do not establish the source amounts’ currency, activate accounting use, or certify financial results.</p></header>
  <p><strong>Proposal rationale:</strong> {detail.proposal.rationale}</p>
  {selections.filter(item=>item.object_type==="Ledger").map(item=>{
   const code=item.identity_key.match(/^company:[0-9a-f-]+:ledger:([A-Za-z0-9._-]+)$/)?.[1];
   return code?<p key={item.resource_id}><strong>Ledger identity code:</strong> {code}</p>:null;
  })}
  <div className="accounting-setup-review-table"><table><thead><tr><th>Proposed resource</th><th>Choices and relationships</th><th>Evidence basis</th></tr></thead><tbody>
   {selections.map(item=><tr key={item.resource_id} id={`${prefix}-${item.resource_id}`}><th scope="row">{displayName(item.display_name)}<small>{labels[item.object_type]}</small></th><td><dl>{Object.entries(item.attributes).map(([field,value])=>{
    const target=mutations.find(candidate=>candidate.resource_id===value);
    const reference=field.endsWith("_id");
    return <div key={field}><dt>{fields[field]??field.replaceAll("_"," ")}</dt><dd>{target?<a href={`#${prefix}-${target.resource_id}`}>{displayName(target.display_name)} <small>(proposed)</small></a>:reference?<details><summary>Existing {fields[field]?.toLowerCase()??"canonical reference"}</summary><code>{String(value)}</code>{typeof record(sourceVersions[item.resource_id])[String(value)]==="string"&&<p>Exact version: <code>{String(record(sourceVersions[item.resource_id])[String(value)])}</code></p>}</details>:typeof value==="string"||typeof value==="number"?String(value):"See retained proposal for this structured value"}</dd></div>;
   })}</dl></td><td>{item.evidence_class?.replaceAll("_"," ")??"Not specified"}<small>Effective from {new Date(item.valid_from).toLocaleString()}</small><details><summary>Exact resource and source references</summary><p>Resource: <code>{item.resource_id}</code></p>{Object.entries(record(sourceVersions[item.resource_id])).map(([identity,version])=><p key={identity}>Source resource: <code>{identity}</code><br/>Version: <code>{String(version)}</code></p>)}</details></td></tr>)}
  </tbody></table></div>
  {!selections.length&&<p role="status">No accounting structure mutations are present in this retained proposal.</p>}
 </section>;
}
