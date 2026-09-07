import type {ResourceProposalDetail} from "@finai/contracts";
import {displayName} from "./display-name";

export default function CalculatedBindingReview({detail}:{detail:ResourceProposalDetail}) {
 const entries=Object.entries(detail.proposal.calculated_bindings??{});
 if(!entries.length)return null;
 return <section aria-label="Calculated change provenance"><h4>Retained calculation behind this change</h4>
  <p>This proposed value comes from a retained calculation. Compare the proposed change with the current value before deciding; calculation evidence is not publication approval.</p>
  {entries.map(([target,binding])=>{
   const mutation=detail.proposal.mutations.find(row=>row.resource_id===target);
   const impact=detail.validation.impact.find(row=>row.resource_id===target);
   const diff=impact?.semantic_diff;
   return <article key={target}><h4>{mutation?displayName(mutation.display_name):"Proposed object"}</h4>
    {diff?.format_version===1?<>
     <p>Retained comparison against {diff.base_version_id?"the reviewed base version":"no existing base version (new object)"}. This comparison is part of the proposal evidence.</p>
     <div className="g8-table-scroll"><table><thead><tr><th>Property</th><th>Before</th><th>Proposed</th></tr></thead><tbody>
      {diff.changes.map(change=><tr key={change.path}>
       <th scope="row">{change.path.split("/").slice(1).map(part=>part.replaceAll("~1","/").replaceAll("~0","~").replaceAll("_"," ")).join(" › ")||"Object"}</th>
       <td><ComparedValue entry={change.before}/></td><td><ComparedValue entry={change.after}/></td>
      </tr>)}
     </tbody></table></div>
     {!diff.changes.length&&<p>No changed values are recorded in this retained comparison.</p>}
     <details><summary>Exact comparison base</summary><p>{diff.base_version_id??"No existing base version"}</p><p>Target: {target}</p></details>
    </>:<p role="alert">The exact before-and-after comparison is unavailable. The proposed value alone does not establish what changed.</p>}
    <details><summary>Calculation lineage</summary>
    <p>Effective calculation context: {new Date(binding.query.valid_at!).toLocaleString()} · Known context: {new Date(binding.query.known_at!).toLocaleString()}</p>
    <dl><dt>Source object / version</dt><dd>{binding.source.resource_id} / {binding.source.version_id}</dd>
     <dt>Reviewed binding / version</dt><dd>{binding.binding.resource_id} / {binding.binding.version_id}</dd>
     <dt>Retained invocation</dt><dd>{binding.input_result.invocation_id}</dd><dt>Receipt hash</dt><dd>{binding.receipt_hash}</dd><dt>Retained result</dt><dd>{binding.run_id}</dd>
    </dl>
    {binding.properties.map(property=><details key={property.version_id}><summary>Exact calculated property</summary><p>{property.resource_id} / {property.version_id}</p><p>{property.content_hash}</p></details>)}
   </details></article>;
  })}
 </section>;
}


function ComparedValue({entry}:{entry:{present:boolean;value?:unknown}}) {
 if(!entry.present)return <span>Not present</span>;
 if(entry.value===null)return <span>Explicit null</span>;
 if(entry.value===undefined)return <span>Value not retained</span>;
 if(typeof entry.value==="object")return <pre style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere"}}>{JSON.stringify(entry.value,null,2)}</pre>;
 return <span style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere"}}>{String(entry.value)}</span>;
}
