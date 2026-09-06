"use client";
import {useRef,useState} from "react";
import type {WorkEvent,WorkRun} from "./action-model";
import {stepLabel} from "./action-model";
import {processLayout} from "./process-graph-model";
import {Badge} from "./g8-ui";
import "./process-graph.css";

export default function ProcessGraph({run,onEvidence,onActions}:{run:WorkRun;onEvidence:(event:WorkEvent)=>void;onActions:()=>void}) {
  const graph=processLayout(run);
  const [selection,setSelection]=useState("");const [filter,setFilter]=useState("");const [zoom,setZoom]=useState(1);
  const canvas=useRef<HTMLDivElement>(null);
  const pan=useRef<{x:number;y:number;left:number;top:number}|null>(null);
  const nodes=graph.nodes;const index=new Map(nodes.map(n=>[n.id,n]));
  const width=Math.max(750,...nodes.map(n=>n.x+245));const height=Math.max(260,...nodes.map(n=>n.y+90));
  const selected=index.get(selection);
  const events=run.events.filter(e=>e.node===selection).slice().sort((a,b)=>Date.parse(b.created_at)-Date.parse(a.created_at));
  const latest=(id:string)=>run.events.filter(e=>e.node===id&&e.state).slice().sort((a,b)=>Date.parse(b.created_at)-Date.parse(a.created_at))[0];
  function reveal(id:string){const n=index.get(id);if(!n)return;setSelection(id);setFilter("");canvas.current?.scrollTo({left:Math.max(0,n.x*zoom-40),top:Math.max(0,n.y*zoom-40),behavior:"smooth"});}
  function fit(){const el=canvas.current;if(el){setZoom(Math.max(.05,Math.min(1,(el.clientWidth-12)/width,(el.clientHeight-12)/height)));el.scrollTo(0,0);}}
  if(!nodes.length&&!graph.error)return null;
  return <section className="g8-process-graph" aria-label="Recorded workflow graph">
    <header><div><h3>Process & evidence</h3><p>Connections follow the retained definition. Step receipts do not establish an external business effect.</p></div><button onClick={onActions}>Go to available actions</button></header>
    {graph.error?<p role="alert">{graph.error}</p>:<>
    <div className="g8-process-graph-controls"><label>Find a process step<input value={filter} onChange={e=>setFilter(e.target.value)} maxLength={128}/></label><button onClick={fit}>Fit process</button><button aria-label="Zoom out process" onClick={()=>setZoom(z=>Math.max(.05,z-.15))}>−</button><span>{Math.round(zoom*100)}%</span><button aria-label="Zoom in process" onClick={()=>setZoom(z=>Math.min(2,z+.15))}>+</button><button onClick={()=>setZoom(1)}>Reset zoom</button></div>
    <div className="g8-process-graph-body"><div>
      <div ref={canvas} className="g8-process-viewport" tabIndex={0} role="region" aria-label="Workflow canvas; scroll or drag background to pan" onPointerDown={e=>{if(e.target instanceof Element&&e.target.closest("button"))return;pan.current={x:e.clientX,y:e.clientY,left:e.currentTarget.scrollLeft,top:e.currentTarget.scrollTop};e.currentTarget.setPointerCapture(e.pointerId);}} onPointerMove={e=>{if(pan.current){e.currentTarget.scrollLeft=pan.current.left-e.clientX+pan.current.x;e.currentTarget.scrollTop=pan.current.top-e.clientY+pan.current.y;}}} onPointerUp={e=>{pan.current=null;if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId);}} onPointerCancel={()=>{pan.current=null;}}>
      <div style={{width:width*zoom,height:height*zoom,position:"relative"}}><div style={{width,height,transform:`scale(${zoom})`,transformOrigin:"top left",position:"relative"}}>
        <svg width={width} height={height} aria-hidden="true" className="g8-process-connections">{graph.edges.map(edge=>{const a=index.get(edge.source)!,b=index.get(edge.target)!;return <path key={`${edge.source}:${edge.target}`} d={`M${a.x+230} ${a.y+42} C${a.x+250} ${a.y+42},${b.x-20} ${b.y+42},${b.x} ${b.y+42}`}/>;})}</svg>
        {nodes.map(node=>{const receipt=latest(node.id);const match=!filter||stepLabel(node.id).toLowerCase().includes(filter.toLowerCase());return <button key={node.id} style={{left:node.x,top:node.y,opacity:match?1:.3}} className="g8-process-node" aria-pressed={selection===node.id} onClick={()=>setSelection(node.id)}><strong>{stepLabel(node.id)}</strong><span>{receipt?.state?.replaceAll("_"," ")??"No state receipt"}</span><small>{receipt?new Date(receipt.created_at).toLocaleString():"Definition only"}</small></button>;})}
      </div></div></div>
      <svg className="g8-process-overview" viewBox={`0 0 ${width} ${height}`} aria-label="Process minimap" role="group">{nodes.map(n=><g key={n.id} role="button" tabIndex={0} aria-label={`Reveal ${stepLabel(n.id)}`} onClick={()=>reveal(n.id)} onKeyDown={e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();reveal(n.id);}}}><rect x={n.x} y={n.y} width={230} height={84} fill={selection===n.id?"var(--accent)":"var(--g8-border)"}/><title>{stepLabel(n.id)}</title></g>)}</svg><nav className="g8-process-minimap" aria-label="Step navigation">{nodes.filter(n=>!filter||stepLabel(n.id).toLowerCase().includes(filter.toLowerCase())).map(n=><button key={n.id} aria-pressed={selection===n.id} onClick={()=>reveal(n.id)}>{stepLabel(n.id)}</button>)}</nav>
    </div><aside aria-label="Selected process step">{selected?<><h4>{stepLabel(selected.id)}</h4><Badge>{latest(selected.id)?.state?.replaceAll("_"," ")??"No state receipt"}</Badge><p>Depends on</p>{selected.depends_on.length?selected.depends_on.map(id=><button key={id} onClick={()=>reveal(id)}>{stepLabel(id)}</button>):<p>No predecessor recorded.</p>}<p>Next connected steps</p>{graph.edges.filter(e=>e.source===selected.id).map(e=><button key={e.target} onClick={()=>reveal(e.target)}>{stepLabel(e.target)}</button>)}<h4>Retained step history</h4>{!events.length&&<p>No event has been recorded for this step.</p>}{events.slice(0,30).map(event=><div key={event.event_id} className="g8-process-event"><time>{new Date(event.created_at).toLocaleString()}</time><p>{event.state?.replaceAll("_"," ")??"Recorded event"}</p>{event.reason&&<p>{event.reason}</p>}{(event.document||event.document_id)&&<button onClick={()=>onEvidence(event)}>Open step evidence</button>}</div>)}{events.length>30&&<p>Latest 30 events shown. Complete retained events remain below the graph.</p>}<details><summary>Execution definition reference</summary><p>{run.definition.version}</p><p>{selected.function}</p></details></>:<p>Select a step to inspect its dependencies, recorded state and evidence.</p>}</aside></div>
    </>}
  </section>;
}
