"use client";
import {useEffect,useRef,useState} from "react";
import maplibregl,{type GeoJSONSource} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type {MapFeature,MapWorkspaceState} from "./operations-model";

export default function OperationsCanvas({features,state,onViewport,onSelect,onBounds,selectedId}:{selectedId?:string;features:MapFeature[];state:MapWorkspaceState;onViewport:(center:[number,number],zoom:number)=>void;onSelect:(feature:MapFeature)=>void;onBounds:(bbox:string)=>void}) {
 const host=useRef<HTMLDivElement>(null);const map=useRef<maplibregl.Map|null>(null);
 const latest=useRef({features,onViewport,onSelect,onBounds,selectedId});
 const initial=useRef(state);const [error,setError]=useState("");
 useEffect(()=>{latest.current={features,onViewport,onSelect,onBounds,selectedId};},[features,onViewport,onSelect,onBounds,selectedId]);
 useEffect(()=>{
  if(!host.current)return;
  let instance:maplibregl.Map;
  // Report failure to initialize the external WebGL renderer.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  try{instance=new maplibregl.Map({container:host.current,style:process.env.NEXT_PUBLIC_G8_MAP_STYLE||"https://tiles.openfreemap.org/styles/dark",center:initial.current.center,zoom:initial.current.zoom,attributionControl:{compact:true}});}catch{setError("Map graphics are unavailable. The asset list remains accessible.");return;}
  map.current=instance;
  instance.addControl(new maplibregl.NavigationControl({showCompass:false}),"top-right");
  instance.on("load",()=>{
   instance.addSource("assets",{type:"geojson",data:{type:"FeatureCollection",features:latest.current.features}});
   instance.addLayer({id:"asset-areas",type:"fill",source:"assets",filter:["==",["geometry-type"],"Polygon"],paint:{"fill-color":"#20cbb8","fill-opacity":.18}});
   instance.addLayer({id:"asset-lines",type:"line",source:"assets",filter:["!=",["geometry-type"],"Point"],paint:{"line-color":"#2de0cf","line-width":3}});
   instance.addLayer({id:"asset-points",type:"circle",source:"assets",filter:["==",["geometry-type"],"Point"],paint:{"circle-radius":6,"circle-color":"#27dcc7","circle-stroke-color":"#d5fffa","circle-stroke-width":1.5}});
   highlight(instance,latest.current.selectedId);
   for(const layer of ["asset-areas","asset-lines","asset-points"]){instance.on("click",layer,e=>{const id=e.features?.[0]?.id;const feature=latest.current.features.find(f=>String(f.id)===String(id));if(feature)latest.current.onSelect(feature);});instance.on("mouseenter",layer,()=>{instance.getCanvas().style.cursor="pointer";});instance.on("mouseleave",layer,()=>{instance.getCanvas().style.cursor="";});}
  });
  instance.on("moveend",()=>{const center=instance.getCenter();latest.current.onViewport([center.lng,center.lat],instance.getZoom());});
  instance.on("error",()=>setError("Some basemap tiles could not load. Reviewed assets and the list remain available."));
  const resize=new ResizeObserver(()=>instance.resize());resize.observe(host.current);
  return()=>{resize.disconnect();instance.remove();map.current=null;};
 },[]);
 useEffect(()=>{const source=map.current?.getSource("assets") as GeoJSONSource|undefined;source?.setData({type:"FeatureCollection",features});},[features]);
 useEffect(()=>{if(map.current?.getLayer("asset-points"))highlight(map.current,selectedId);},[selectedId,features]);
 function fit(){if(!map.current||!features.length)return;const bounds=new maplibregl.LngLatBounds();function add(value:unknown){if(!Array.isArray(value))return;if(typeof value[0]==="number"&&typeof value[1]==="number")bounds.extend([value[0],value[1]]);else value.forEach(add);}features.forEach(f=>{if("coordinates" in f.geometry)add(f.geometry.coordinates);});if(!bounds.isEmpty())map.current.fitBounds(bounds,{padding:50,maxZoom:14});}
 return <div className="ops-map-wrap"><div className="ops-map" ref={host} role="region" aria-label="Geographic asset map"/><div className="ops-map-controls"><button onClick={fit} disabled={!features.length}>Fit assets</button><button onClick={()=>{const bounds=map.current?.getBounds();if(bounds)onBounds([Math.max(-180,bounds.getWest()),Math.max(-90,bounds.getSouth()),Math.min(180,bounds.getEast()),Math.min(90,bounds.getNorth())].join(","));}}>Search this area</button></div>{error&&<p className="ops-map-error" role="status">{error}</p>}<span className="ops-legend">● Reviewed positions &nbsp; ━ Recorded geometry</span></div>;
}

function highlight(map:maplibregl.Map,id?:string){const color:maplibregl.ExpressionSpecification=["case",["==",["id"],id??""],"#fff0a3","#27dcc7"];map.setPaintProperty("asset-points","circle-color",color);map.setPaintProperty("asset-lines","line-color",color);map.setPaintProperty("asset-areas","fill-color",color);}
