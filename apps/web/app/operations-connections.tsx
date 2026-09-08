"use client";
import {useEffect,useState} from "react";
import {operationsRequest,type MapSelection} from "./operations-model";
import {assertConnectionSnapshot,connectedSelection,type ConnectionSnapshot} from "./operations-connections-state";
import {Badge} from "./g8-ui";

type Props={token:string;selection:MapSelection;companyId?:string;onSelect:(selection:MapSelection)=>void};
export default function OperationsConnections(props:Props){
 const s=props.selection;
 return <Connections key={JSON.stringify([props.token,props.companyId,s.resource.resource_id,s.resource.version_id,s.resource.content_hash,s.validAt,s.knownAt])} {...props}/>;
}
function Connections({token,selection,companyId,onSelect}:Props){
 const [data,setData]=useState<ConnectionSnapshot|null>(null),[error,setError]=useState("");const [revision,setRevision]=useState(0);
 const {resource,validAt,knownAt}=selection;
 useEffect(()=>{const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),25000);let disposed=false;
  const query=new URLSearchParams({valid_at:validAt,known_at:knownAt,depth:"2"});if(companyId)query.set("company_id",companyId);
  void operationsRequest<ConnectionSnapshot>(`map/${resource.resource_id}/connections?${query}`,token,controller.signal).then(value=>{
   assertConnectionSnapshot(value,selection);if(!disposed&&!controller.signal.aborted){setData(value);setError("");}
  }).catch(failure=>{if(!disposed){setData(null);setError(controller.signal.aborted?"Connection retrieval timed out.":failure instanceof Error?failure.message:"Connections unavailable");}}).finally(()=>clearTimeout(timer));
  return()=>{disposed=true;clearTimeout(timer);controller.abort();};
 },[token,companyId,resource.resource_id,validAt,knownAt,selection,revision]);
 return <section className="ops-connections"><h3>Recorded downstream connections · {resource.display_name}</h3><p>Two steps along explicit directed relationships. Connectivity is not a hydraulic or customer-impact prediction.</p>
  <p>Effective {validAt} · known {knownAt}. Connected assets retain this snapshot when selected.</p>
  {error?<div role="alert"><p>{error}</p><button onClick={()=>{setError("");setData(null);setRevision(value=>value+1);}}>Retry exact asset snapshot</button></div>:!data?<p role="status">Loading connections…</p>:!data.edges.length?<p>No explicit outgoing connections are recorded in this snapshot.</p>:<ul>{data.edges.map((edge,index)=><li key={index}>{data.resources.find(node=>node.resource_id===edge.source_id)?.display_name} <Badge>{edge.relation}</Badge> <button onClick={()=>{const next=connectedSelection(data,edge.target_id);if(next)onSelect(next);}}>{data.resources.find(node=>node.resource_id===edge.target_id)?.display_name}</button></li>)}</ul>}
  {data&&(data.completeness.snapshot_bounded||data.completeness.depth_bounded||data.completeness.node_bounded)&&<p className="g8-inline-error">Traversal is bounded; further connections may exist.</p>}
 </section>;
}
