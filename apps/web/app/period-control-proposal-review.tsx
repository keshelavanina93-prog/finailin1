import type {ResourceProposalDetail} from "@finai/contracts";
export default function PeriodControlProposalReview({detail}:{detail:ResourceProposalDetail}){
 const controls=detail.proposal.mutations.filter(item=>item.object_type==="PeriodControl");
 if(!controls.length)return null;
 return <section aria-label="Proposed period posting controls"><h3>Proposed period posting control</h3><p>This proposal opens or locks the selected period for journal changes. It does not establish financial close completion, financial certification or ERP posting.</p>{controls.map(control=>{
  const definition=control.attributes.definition as {contract?:string;state?:string;reason?:string}|undefined;
  return <article key={control.resource_id}><h4>{control.display_name}</h4><p>Proposed posting state: <strong>{definition?.contract==="period-posting-control/1"&&(definition.state==="OPEN"||definition.state==="LOCKED")?definition.state:"Unsupported or unavailable control definition"}</strong></p><p>Reason: {definition?.reason??"Not retained"}</p><p>Evidence basis: {control.evidence_class?.replaceAll("_"," ")??"Not retained"}. Independent review remains required.</p><details><summary>Exact period control scope</summary>{Object.entries(control.attributes).filter(([key])=>key.endsWith("_id")).map(([key,value])=><p key={key}>{key.replaceAll("_"," ")}: {typeof value==="string"?value:"Unavailable"}</p>)}<p>Control: {control.resource_id}</p><p>Expected prior version: {control.expected_version_id??"New control"}</p></details></article>;
 })}</section>;
}
