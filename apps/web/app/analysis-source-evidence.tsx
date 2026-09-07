"use client";
import {useEffect,useRef,useState} from "react";
import type {CanonicalResource,HistoricalGraph,OperatorInspection} from "@finai/contracts";

export default function AnalysisSourceEvidence({token,movement,knownAt,onClose,onTrace}:{token:string;movement:CanonicalResource;knownAt:string;onClose:()=>void;onTrace:()=>void}){
  const [source,setSource]=useState<CanonicalResource|null>(null);const [error,setError]=useState("");const [revision,setRevision]=useState(0);
  const heading=useRef<HTMLHeadingElement>(null);
  useEffect(()=>{heading.current?.focus();},[]);
  useEffect(()=>{
    const controller=new AbortController();
    async function read<T>(path:string):Promise<T>{
      const response=await fetch(`/api/ontology/operator/${path}`,{headers:{Authorization:`Bearer ${token}`},signal:controller.signal});
      if(!response.ok)throw Error(response.status===403?"Source evidence is not permitted for this identity.":`Source evidence unavailable (${response.status}).`);
      return response.json();
    }
    async function load(){try{
      const graph=await read<HistoricalGraph>(`trace/${movement.resource_id}?version_id=${movement.version_id}&known_at=${encodeURIComponent(knownAt)}`);
      if(graph.root_version_id!==movement.version_id)throw Error("Evidence did not match the selected movement version.");
      const edges=graph.edges.filter(edge=>edge.source_version_id===movement.version_id&&edge.relation==="FIELD:source_record_id");
      const pin=graph.nodes.find(node=>node.object_type==="SourceRecord"&&node.resource_id===movement.attributes.source_record_id&&edges.some(edge=>edge.target_version_id===node.version_id));
      if(!pin)throw Error("The exact source-row relationship is unavailable. No substitute evidence is shown.");
      const detail=await read<OperatorInspection>(`resources/${pin.resource_id}?version_id=${pin.version_id}&known_at=${encodeURIComponent(knownAt)}`);
      if(detail.resource.resource_id!==pin.resource_id||detail.resource.version_id!==pin.version_id)throw Error("Source evidence version changed unexpectedly.");
      if(!controller.signal.aborted)setSource(detail.resource);
    }catch(cause){if(!controller.signal.aborted)setError(String(cause));}}
    void load();return()=>controller.abort();
  },[token,movement,knownAt,revision]);
  const details=movement.attributes.source_details as {cells?:Record<string,{value:unknown}>;aggregation_policy?:string}|undefined;
  return <section className="analysis-evidence" aria-label="Source row evidence" onKeyDown={event=>{if(event.key==="Escape")onClose();}}>
    <header><h3 ref={heading} tabIndex={-1}>Source evidence · {source?.display_name??movement.display_name}</h3><button onClick={onClose}>Return to contributors</button></header>
    <p>{String(movement.attributes.document_reference??"Source document reference unavailable")}</p>
    <p>Posting date {String(movement.attributes.posting_date)} · Source amount {String(movement.attributes.amount)} · Currency not established</p>
    {error?<p role="alert">{error} <button onClick={()=>{setError("");setRevision(value=>value+1);}}>Retry source evidence</button></p>:!source?<p role="status">Resolving the exact retained source row…</p>:<>
      <p>Retained worksheet position: <strong>{String(source.attributes.coordinate??source.display_name)}</strong>. Values below are the source cells retained with this movement, without accounting interpretation.</p>
      {details?.cells?<div className="finance-analysis-table"><table><thead><tr><th>Source column</th><th>Retained value</th></tr></thead><tbody>{Object.entries(details.cells).map(([column,cell])=><tr key={column}><th scope="row">{column}</th><td>{cell.value===""?"Blank in source":String(cell.value??"Not retained")}</td></tr>)}</tbody></table></div>:<p role="status">Source cell values are unavailable for this movement. No reconstructed values are shown.</p>}
      <p>Aggregation requires review. These observations do not establish an additive or certified report.</p>
      <details><summary>Exact evidence references</summary><dl><dt>Movement version</dt><dd>{movement.version_id}</dd><dt>Movement hash</dt><dd>{movement.content_hash}</dd><dt>Source row version</dt><dd>{source.version_id}</dd><dt>Source row hash</dt><dd>{source.content_hash}</dd><dt>Known at</dt><dd>{knownAt}</dd></dl></details>
    </>}
    <button onClick={onTrace}>Show system trace</button>
  </section>;
}
