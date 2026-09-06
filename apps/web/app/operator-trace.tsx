"use client";

import {useEffect, useRef, useState} from "react";
import {displayName} from "./display-name";
import "./operator-trace.css";

export type TraceSelection = {resource_id:string; version_id:string; company_id:string; known_at?:string};
type Node = {resource_id:string;version_id:string;object_type:string;display_name:string;authority_state:string;system_from:string;valid_from:string;source_document_id?:string|null};
type Edge = {source_version_id:string;target_version_id:string;relation:string};
type Graph = {root_version_id:string;known_at:string;nodes:Node[];edges:Edge[]};

export default function OperatorTrace({token,root,onClose,onInspect}:{token:string;root:TraceSelection;onClose:()=>void;onInspect:(node:Node)=>void}) {
 const [graph,setGraph]=useState<Graph|null>(null);const [error,setError]=useState("");
 const [focus,setFocus]=useState(root.version_id);const [filter,setFilter]=useState("");
 const [technical,setTechnical]=useState(false);const [zoom,setZoom]=useState(1);
 const [windowBox,setWindowBox]=useState({left:0,top:0,width:0,height:0});
 const reveal=useRef(false);
 const viewport=useRef<HTMLDivElement>(null);const drag=useRef<{x:number;y:number;left:number;top:number}|null>(null);
 useEffect(()=>{const element=viewport.current;if(!element)return;
  const update=()=>setWindowBox({left:element.scrollLeft,top:element.scrollTop,width:element.clientWidth,height:element.clientHeight});
  const observer=new ResizeObserver(update);observer.observe(element);element.addEventListener("scroll",update,{passive:true});update();
  return()=>{observer.disconnect();element.removeEventListener("scroll",update);};
 },[graph]);
 useEffect(()=>{const controller=new AbortController();
  void fetch(`/api/ontology/operator/trace/${root.resource_id}?version_id=${root.version_id}${root.known_at?`&known_at=${encodeURIComponent(root.known_at)}`:""}`,{headers:{Authorization:`Bearer ${token}`},signal:controller.signal}).then(async response=>{const result=await response.json();if(!response.ok)throw Error(typeof result.detail==="string"?result.detail:"Trace unavailable");if(!controller.signal.aborted)setGraph(result);}).catch(e=>{if(!controller.signal.aborted)setError(String(e));});return()=>controller.abort();
 },[token,root.resource_id,root.version_id,root.known_at]);
 const depth=new Map<string,number>([[root.version_id,0]]);
 if(graph){const queue=[root.version_id];for(let i=0;i<queue.length;i++){for(const edge of graph.edges.filter(e=>e.source_version_id===queue[i]))if(!depth.has(edge.target_version_id)){depth.set(edge.target_version_id,depth.get(queue[i])!+1);queue.push(edge.target_version_id);}}}
 const matching=graph?.nodes.filter(n=>(technical||!["SchemaDefinition","SemanticContract","LinkType"].includes(n.object_type))&&`${n.display_name} ${n.object_type}`.toLowerCase().includes(filter.toLowerCase()))??[];
 const nodes=matching.slice(0,200);const selectedMatch=matching.find(n=>n.version_id===focus);
 if(selectedMatch&&!nodes.includes(selectedMatch))nodes.splice(199,1,selectedMatch);
 const levels=new Map<number,number>();
 const positions=new Map(nodes.map(n=>{const level=depth.get(n.version_id)??0;const row=levels.get(level)??0;levels.set(level,row+1);return[n.version_id,{x:30+level*300,y:30+row*110}];}));
 const width=Math.max(850,...[...positions.values()].map(p=>p.x+270));const height=Math.max(420,...[...positions.values()].map(p=>p.y+100));
 const selected=graph?.nodes.find(n=>n.version_id===focus);
 function revealNode(id:string){const node=graph?.nodes.find(n=>n.version_id===id);if(!node)return;
  reveal.current=true;setFilter("");if(["SchemaDefinition","SemanticContract","LinkType"].includes(node.object_type))setTechnical(true);setFocus(id);setZoom(1);
  // Clicking an already selected node must still reveal it after a manual pan.
  if(id===focus&&zoom===1&&!filter&&positions.has(id)){const p=positions.get(id)!;viewport.current?.scrollTo({left:Math.max(0,p.x+120-windowBox.width/2),top:Math.max(0,p.y+40-windowBox.height/2)});reveal.current=false;}
 }
 useEffect(()=>{if(!reveal.current)return;const p=positions.get(focus);const element=viewport.current;if(!p||!element)return;
  element.scrollTo({left:Math.max(0,(p.x+120)*zoom-element.clientWidth/2),top:Math.max(0,(p.y+40)*zoom-element.clientHeight/2)});reveal.current=false;
 });
 function fit(){const element=viewport.current;if(!element)return;setZoom(Math.max(.01,Math.min(1,(element.clientWidth-16)/width,(element.clientHeight-16)/height)));element.scrollTo(0,0);}
 async function download(node:Node){try{const response=await fetch(`/api/ontology/source-documents/${node.source_document_id}/content`,{headers:{Authorization:`Bearer ${token}`}});if(!response.ok)throw Error("Original source unavailable in this context");const url=URL.createObjectURL(await response.blob());const anchor=document.createElement("a");anchor.href=url;anchor.download=node.source_document_id!;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){setError(String(e));}}
 return <section className="g8-trace" aria-label="System trace">
  <header><div><strong>System trace</strong><p>Recorded dependency versions · changes require a separate reviewed action</p>{graph&&<p>Known by G8 at <time dateTime={graph.known_at}>{new Date(graph.known_at).toLocaleString()}</time></p>}</div><button onClick={onClose}>Close trace</button></header>
  <div className="g8-trace-toolbar"><label>Find in trace<input value={filter} onChange={e=>setFilter(e.target.value)} placeholder="Company, rule, source…"/></label><label><input type="checkbox" checked={technical} onChange={e=>setTechnical(e.target.checked)}/>Include schema mechanics</label><button onClick={()=>setZoom(z=>Math.max(.01,z/1.25))} aria-label="Zoom out">−</button><span aria-label="Canvas zoom">{Math.round(zoom*100)}%</span><button onClick={()=>setZoom(z=>Math.min(2,z*1.25))} aria-label="Zoom in">+</button><button disabled={!nodes.length} onClick={fit}>Fit visible graph</button><button disabled={!selected} onClick={()=>revealNode(focus)}>Fit selected object</button><button onClick={()=>{setZoom(1);viewport.current?.scrollTo(0,0);}}>Reset canvas</button></div>
  {error&&<p role="alert">{error}</p>}{!graph&&!error&&<p role="status">Resolving recorded version dependencies…</p>}
  {graph&&<><p>{nodes.length} of {graph.nodes.length} recorded versions visible{matching.length>200?" · narrow the filter to see additional matches":""}. Arrows point to dependencies. Drag the canvas or use its scrollbars.</p><div className="g8-trace-body">
   <div className="g8-trace-canvas" ref={viewport} onPointerDown={e=>{if((e.target as Element).closest('[data-trace-node]'))return;drag.current={x:e.clientX,y:e.clientY,left:e.currentTarget.scrollLeft,top:e.currentTarget.scrollTop};e.currentTarget.setPointerCapture(e.pointerId);}} onPointerMove={e=>{if(drag.current){e.currentTarget.scrollLeft=drag.current.left+drag.current.x-e.clientX;e.currentTarget.scrollTop=drag.current.top+drag.current.y-e.clientY;}}} onPointerUp={()=>{drag.current=null;}} onPointerCancel={()=>{drag.current=null;}}>
    <svg width={width*zoom} height={height*zoom} viewBox={`0 0 ${width} ${height}`} aria-label="Recorded ontology dependency canvas">
     <defs><marker id="trace-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="currentColor"/></marker></defs>
     {graph.edges.map(e=>{const a=positions.get(e.source_version_id),b=positions.get(e.target_version_id);return a&&b?<path key={`${e.source_version_id}:${e.target_version_id}:${e.relation}`} className={focus===e.source_version_id||focus===e.target_version_id?"focused-edge":""} d={`M${a.x+240},${a.y+40} C${a.x+275},${a.y+40} ${b.x-35},${b.y+40} ${b.x},${b.y+40}`} markerEnd="url(#trace-arrow)"><title>{e.relation}</title></path>:null;})}
     {nodes.map(n=>{const p=positions.get(n.version_id)!;return <g data-trace-node key={n.version_id} role="button" tabIndex={0} aria-label={`Inspect ${displayName(n.display_name)} ${n.object_type}`} aria-pressed={focus===n.version_id} onClick={()=>setFocus(n.version_id)} onKeyDown={e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();setFocus(n.version_id);}}} transform={`translate(${p.x},${p.y})`} className={focus===n.version_id?"selected-node":""}><rect width="240" height="80" rx="5"/><text x="12" y="20" className="trace-kind">{n.object_type}</text><text x="12" y="42">{displayName(n.display_name).slice(0,28)}</text><text x="12" y="65" className="trace-kind">{n.authority_state} · {n.version_id.slice(0,8)}</text><title>{displayName(n.display_name)} · {n.version_id}</title></g>;})}
    </svg>
   </div>
   <aside aria-label="Trace object details"><div className="g8-trace-overview"><small>Canvas overview · click to move, or focus and use arrow keys</small><svg role="button" tabIndex={0} aria-label="Navigate trace overview" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" onPointerDown={e=>{const box=e.currentTarget.getBoundingClientRect();viewport.current?.scrollTo({left:Math.max(0,(e.clientX-box.left)/box.width*width*zoom-windowBox.width/2),top:Math.max(0,(e.clientY-box.top)/box.height*height*zoom-windowBox.height/2)});}} onKeyDown={e=>{const delta={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[e.key];if(delta){e.preventDefault();viewport.current?.scrollBy(delta[0]*windowBox.width/2,delta[1]*windowBox.height/2);}}}>
    {nodes.map(n=>{const p=positions.get(n.version_id)!;return <rect key={n.version_id} x={p.x} y={p.y} width="240" height="80" className={n.version_id===focus?"overview-selected":""}/>;})}
    <rect className="overview-window" x={windowBox.left/zoom} y={windowBox.top/zoom} width={Math.min(width,windowBox.width/zoom)} height={Math.min(height,windowBox.height/zoom)}/>
   </svg></div>{selected&&<><small>{selected.object_type}</small><h3>{displayName(selected.display_name)}</h3><p>{selected.authority_state} · recorded {new Date(selected.system_from).toLocaleString()}</p><button onClick={()=>onInspect(selected)}>Open this version</button>{selected.source_document_id&&<button onClick={()=>void download(selected)}>Download original evidence</button>}<h4>Recorded connections</h4>{graph.edges.filter(e=>e.source_version_id===focus||e.target_version_id===focus).map(e=>{const other=graph.nodes.find(n=>n.version_id===(e.source_version_id===focus?e.target_version_id:e.source_version_id));return other?<button className="trace-connection" key={`${e.source_version_id}:${e.target_version_id}:${e.relation}`} onClick={()=>revealNode(other.version_id)}><small>{e.source_version_id===focus?"Depends on":"Used by"} · {e.relation.replace("FIELD:","")}</small>{displayName(other.display_name)}</button>:null;})}<details><summary>Identity and version</summary><p>{selected.resource_id}</p><p>{selected.version_id}</p></details></>}</aside>
  </div></>}
 </section>;
}
