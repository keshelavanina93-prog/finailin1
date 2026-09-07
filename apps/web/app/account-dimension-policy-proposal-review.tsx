import type {ResourceProposalDetail} from "@finai/contracts";

const object=(value:unknown):Record<string,unknown>=>value!==null&&typeof value==="object"&&!Array.isArray(value)?value as Record<string,unknown>:{};
export default function AccountDimensionPolicyProposalReview({detail}:{detail:ResourceProposalDetail}){
 const policies=detail.proposal.mutations.filter(item=>item.object_type==="AccountDimensionPolicy");
 if(!policies.length)return null;
 return <section aria-label="Proposed account analytical policies"><h3>Proposed account analytical requirements</h3><p>Review the complete allowed rule set for the exact company, chart and account. Approval does not establish journal balance, source authenticity or permission to post amounts.</p>
  {policies.map(policy=>{
   const definition=object(policy.attributes.definition);
   const rules=Array.isArray(definition.rules)?definition.rules.map(object):null;
   return <article key={policy.resource_id}><h4>{policy.display_name}</h4>
    {definition.contract!=="account-dimension-policy/1"||!rules?<p role="status">The retained policy definition cannot be interpreted by this review.</p>:<><p><strong>{rules.length?`${rules.length} exact rule versions proposed` : "Explicitly empty allowed-rule policy proposed"}</strong></p><p>Reason: {typeof definition.reason==="string"?definition.reason:"Not retained"}</p><details><summary>Complete proposed rule references</summary>{rules.map((rule,index)=><p key={index}>{typeof rule.resource_id==="string"?rule.resource_id:"Unavailable rule"} · {typeof rule.version_id==="string"?rule.version_id:"Unavailable version"}</p>)}</details></>}
    <details><summary>Exact account policy scope</summary>{Object.entries(policy.attributes).filter(([key])=>key.endsWith("_id")).map(([key,value])=><p key={key}>{key.replaceAll("_"," ")}: {typeof value==="string"?value:"Unavailable"}</p>)}<p>Policy: {policy.resource_id}</p><p>Expected prior version: {policy.expected_version_id??"New policy"}</p></details>
   </article>;
  })}
 </section>;
}
