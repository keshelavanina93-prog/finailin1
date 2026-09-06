"use client";

import {useId, useMemo, useState} from "react";
import type {CanonicalResource} from "@finai/contracts";
import type {Context} from "./company-workspace";
import {displayName} from "./display-name";
import "./company-structure-graph.css";

type Node = CanonicalResource;
type Edge = {record:Node;source:Node;target:Node;label:string;year:string};
type Props = {context:Context;onInspect:(node:Node)=>void;onSelect:(node:Node)=>void;onTrace?:(node:Node)=>void};
const pin = (node:Node) => `${node.resource_id}:${node.version_id}`;
const words = (value:unknown) => String(value??"").replaceAll("_"," ");
const short = (value:string) => value.length>27?`${value.slice(0,26)}…`:value;

export default function CompanyStructureGraph(props:Props) {
 return <StructureGraph key={pin(props.context.company)} {...props}/>;
}

function StructureGraph({context,onInspect,onSelect,onTrace}:Props) {
 const [mode,setMode]=useState<"current"|"reported">("current");
 const [year,setYear]=useState("");
 const [search,setSearch]=useState("");
 const [selected,setSelected]=useState(pin(context.company));
 const [selectedEdge,setSelectedEdge]=useState("");
 const [camera,setCamera]=useState({x:0,y:0,zoom:1});
 const id=useId().replaceAll(":","");
 const edges=useMemo<Edge[]>(()=>mode==="current"?context.relationships.map(row=>({record:row.record,source:row.source,target:row.target,label:words(row.kind),year:""})):context.disclosures.map(row=>{
  const observation=row.observation.attributes.observation as {reported_role?:string;reported_percent?:string|null;former_indicator?:string}|undefined;
  return {record:row.binding,source:row.reporter,target:row.party,year:String(row.binding.attributes.reporting_year??"Not stated"),label:[words(observation?.reported_role)||"Reported relationship",observation?.reported_percent!=null?`${observation.reported_percent}% reported`:"",observation?.former_indicator?`Former-party marker: ${observation.former_indicator}`:""].filter(Boolean).join(" · ")};
 }),[context,mode]);
 const years=[...new Set(edges.map(edge=>edge.year))].sort().reverse();
 const query=search.trim().toLocaleLowerCase();
 const matching=edges.filter(edge=>(!year||edge.year===year)&&(!query||`${edge.source.display_name} ${edge.target.display_name} ${edge.label}`.toLocaleLowerCase().includes(query)));
 const nodes=new Map<string,Node>([[pin(context.company),context.company]]);
 const shown:Edge[]=[];
 for(const edge of matching){
  const additions=[edge.source,edge.target].filter(node=>!nodes.has(pin(node)));
  if(nodes.size+new Set(additions.map(pin)).size>200||shown.length>=400)continue;
  additions.forEach(node=>nodes.set(pin(node),node));shown.push(edge);
 }
 const items=[...nodes.values()];
 const height=Math.max(480,Math.ceil(items.length/3)*110+70);
 const positions=new Map(items.map((node,index)=>[pin(node),{x:45+(index%3)*315,y:40+Math.floor(index/3)*110}]));
 const active=nodes.get(selected)??context.company;
 const edge=shown.find(item=>pin(item.record)===selectedEdge);
 const viewWidth=1000/camera.zoom,viewHeight=height/camera.zoom;
 const x=Math.min(Math.max(0,camera.x),1000-viewWidth),y=Math.min(Math.max(0,camera.y),height-viewHeight);
 function reset(){setSelectedEdge("");setCamera({x:0,y:0,zoom:1});}
 function choose(node:Node){setSelected(pin(node));setSelectedEdge("");}
 function reveal(node:Node){choose(node);const point=positions.get(pin(node));if(point)setCamera({x:Math.max(0,point.x-80),y:Math.max(0,point.y-70),zoom:Math.min(30,Math.max(2,height/700))});}
 const detail=edge?.record??active;
 return <section className="csg" aria-label="Company relationship graph">
  <header className="csg-heading"><div><span>COMPANY STRUCTURE</span><h3>Explore connected companies</h3></div><div className="csg-mode" aria-label="Relationship authority"><button aria-pressed={mode==="current"} onClick={()=>{setMode("current");setYear("");reset();}}>Current structure</button><button aria-pressed={mode==="reported"} onClick={()=>{setMode("reported");setYear("");reset();}}>Reported filings</button></div></header>
  <p className="csg-authority">{mode==="current"?"Effective relationships returned by the shared company authority. No relationship is inferred from a filing.":"Dated statements in retained filings. These edges do not establish current ownership, operating control or consolidation membership."}</p>
  <div className="csg-toolbar"><label>Find a connection<input value={search} onChange={event=>{setSearch(event.target.value);reset();}} placeholder="Company or relationship"/></label>{mode==="reported"&&<label>Reporting year<select value={year} onChange={event=>{setYear(event.target.value);reset();}}><option value="">All retained years</option>{years.map(value=><option key={value}>{value}</option>)}</select></label>}<div className="csg-camera"><button aria-label="Zoom out graph" disabled={camera.zoom<=1} onClick={()=>setCamera({...camera,zoom:Math.max(1,camera.zoom/1.5)})}>−</button><button aria-label="Zoom in graph" onClick={()=>setCamera({...camera,zoom:Math.min(30,camera.zoom*1.5)})}>+</button><button onClick={reset}>Fit graph</button><button onClick={()=>reveal(active)}>Reveal selected</button></div></div>
  {!matching.length?<div className="csg-empty"><h4>{edges.length?"No relationships match these filters":mode==="current"?"No effective company relationships are accepted":"No reviewed filing relationships are linked"}</h4><p>{mode==="current"?"Inspect the company identity or switch to dated evidence. A retained filing is not current company structure.":"Company identity remains available. Additional relationships require retained evidence and shared review."}</p>{mode==="current"&&context.disclosures.length>0&&<button onClick={()=>{setMode("reported");setYear("");reset();}}>Explore {context.disclosures.length} dated filing relationships</button>}<button onClick={()=>onInspect(context.company)}>Inspect company</button></div>:<>
   <div className="csg-count" role="status">{shown.length} of {matching.length} matching relationships · {items.length} exact company versions{shown.length<matching.length?" · Display bounded to 200 nodes / 400 edges. Narrow the year or search to reveal omitted connections.":""}</div>
   <div className="csg-body"><div className="csg-canvas"><svg className="csg-main" viewBox={`${x} ${y} ${viewWidth} ${viewHeight}`} role="group" aria-label={`${mode==="reported"?"Dated reported":"Effective"} company relationships`}><defs><marker id={`${id}-arrow`} viewBox="0 0 10 10" refX="10" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"/></marker></defs>{shown.map(item=>{const a=positions.get(pin(item.source))!,b=positions.get(pin(item.target))!;return <g key={pin(item.record)} role="button" tabIndex={0} aria-label={`${displayName(item.source.display_name)} to ${displayName(item.target.display_name)}: ${item.label}${item.year?`, filing ${item.year}`:""}. Inspect exact relationship.`} className={`csg-edge ${selectedEdge===pin(item.record)?"selected":""}`} onClick={()=>setSelectedEdge(pin(item.record))} onKeyDown={event=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();setSelectedEdge(pin(item.record));}}}><title>{item.label}{item.year?` · Filing ${item.year}`:""}</title><path markerEnd={`url(#${id}-arrow)`} d={`M ${a.x+130} ${a.y+64} Q ${(a.x+b.x)/2+130} ${(a.y+b.y)/2+100} ${b.x+130} ${b.y}`}/></g>;})}{items.map(node=>{const point=positions.get(pin(node))!;return <g key={pin(node)} transform={`translate(${point.x},${point.y})`} className={`csg-node ${pin(active)===pin(node)&&!edge?"selected":""}`} role="button" tabIndex={0} aria-label={`Select ${displayName(node.display_name)}, exact version ${node.version_id}`} onClick={()=>choose(node)} onKeyDown={event=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();choose(node);}}}><title>{displayName(node.display_name)}</title><rect width="265" height="64" rx="5"/><text x="12" y="25">{short(displayName(node.display_name))}</text><text className="csg-node-type" x="12" y="46">{node.resource_id===context.company.resource_id?"Selected company context":words(node.object_type)}</text></g>;})}</svg>
    <div className="csg-map"><svg viewBox={`0 0 1000 ${height}`} role="img" aria-label="Graph overview. Use pan controls to move the viewport.">{shown.map(item=>{const a=positions.get(pin(item.source))!,b=positions.get(pin(item.target))!;return <line key={pin(item.record)} x1={a.x+130} y1={a.y+30} x2={b.x+130} y2={b.y+30}/>;})}{items.map(node=>{const p=positions.get(pin(node))!;return <rect key={pin(node)} x={p.x} y={p.y} width="265" height="64"/>;})}<rect className="csg-viewport" x={x} y={y} width={viewWidth} height={viewHeight}/></svg></div>
    <div className="csg-pan" aria-label="Pan graph">{([{label:"Left",dx:-1,dy:0},{label:"Up",dx:0,dy:-1},{label:"Down",dx:0,dy:1},{label:"Right",dx:1,dy:0}]).map(move=><button key={move.label} disabled={camera.zoom<=1} onClick={()=>setCamera({...camera,x:Math.max(0,x+move.dx*viewWidth/3),y:Math.max(0,y+move.dy*viewHeight/3)})}>{move.label}</button>)}</div>
   </div><aside className="csg-inspector" aria-label="Selected graph item"><span>{edge?"RELATIONSHIP EVIDENCE":"COMPANY INSPECTOR"}</span><h4>{displayName(detail.display_name)}</h4>{edge&&<><p>{displayName(edge.source.display_name)} → {displayName(edge.target.display_name)}</p><p>{edge.label}</p>{edge.year&&<strong>Filing year {edge.year} · reported statement</strong>}</>}<dl><dt>Authority state</dt><dd>{words(detail.authority_state)}</dd><dt>Evidence basis</dt><dd>{words(detail.evidence_class)}</dd><dt>Effective from</dt><dd>{detail.valid_from}</dd><dt>Recorded at</dt><dd>{detail.system_from}</dd></dl><div className="csg-inspector-actions"><button onClick={()=>onInspect(detail)}>Inspect exact version</button>{onTrace&&<button onClick={()=>onTrace(detail)}>Trace evidence</button>}{!edge&&active.object_type==="LegalEntity"&&<button onClick={()=>onSelect(active)}>Open company workspace</button>}</div><details><summary>Canonical version reference</summary><code>{detail.resource_id}<br/>{detail.version_id}</code></details></aside></div>
   <details className="csg-list"><summary>Accessible relationship list · {shown.length} connections</summary>{shown.map(item=><div key={pin(item.record)}><button onClick={()=>reveal(item.source)}>{displayName(item.source.display_name)}</button><span>→</span><button onClick={()=>reveal(item.target)}>{displayName(item.target.display_name)}</button><span>{item.year&&`${item.year} · `}{item.label}</span><button onClick={()=>{setSelectedEdge(pin(item.record));onInspect(item.record);}}>Inspect relationship</button></div>)}</details>
  </>}
 </section>;
}
