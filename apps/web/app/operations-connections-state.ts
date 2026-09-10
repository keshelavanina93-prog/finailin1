import type {CanonicalResource} from "@finai/contracts";
import type {MapSelection} from "./operations-model";
import {restorationInstant} from "./definition-restoration-time";

export type ConnectionSnapshot={root_id:string;valid_at:string;known_at:string;depth:number;interpretation:string;
 resources:CanonicalResource[];edges:{source_id:string;target_id:string;relation:string}[];
 completeness:{snapshot_bounded:boolean;node_bounded:boolean;depth_bounded:boolean;node_limit:number}};

export function assertConnectionSnapshot(value:ConnectionSnapshot,selected:MapSelection):void {
 const sameTime=(a:string,b:string)=>Boolean(restorationInstant(a)&&restorationInstant(a)===restorationInstant(b));
 if(!value||value.root_id!==selected.resource.resource_id||value.depth!==2||value.interpretation!=="EXPLICIT_DIRECTED_CONNECTIVITY_ONLY"||
  !sameTime(value.valid_at,selected.validAt)||!sameTime(value.known_at,selected.knownAt))throw Error("Connections did not preserve the selected asset and exact snapshot.");
 if(!Array.isArray(value.resources)||value.resources.length>250||value.resources.some(node=>!node||!node.resource_id||!node.version_id||typeof node.display_name!=="string")||
  new Set(value.resources.map(node=>node.resource_id)).size!==value.resources.length)throw Error("Connected asset references are unavailable.");
 const root=value.resources.find(node=>node.resource_id===value.root_id);
 if(!root||root.version_id!==selected.resource.version_id||root.content_hash!==selected.resource.content_hash)throw Error("The selected asset revision differs from the connection snapshot.");
 const ids=new Set(value.resources.map(node=>node.resource_id));
 if(!Array.isArray(value.edges)||value.edges.some(edge=>!edge||!ids.has(edge.source_id)||!ids.has(edge.target_id)||typeof edge.relation!=="string"||!edge.relation))throw Error("Connection endpoints are unavailable in the retained snapshot.");
 const c=value.completeness;
 if(!c||c.node_limit!==250||[c.snapshot_bounded,c.node_bounded,c.depth_bounded].some(flag=>typeof flag!=="boolean"))throw Error("Connection coverage is unavailable.");
}

/** A historical connection keeps its own time, independently of the surrounding map. */
export function connectedSelection(value:ConnectionSnapshot,resourceId:string):MapSelection|null {
 const resource=value.resources.find(node=>node.resource_id===resourceId);
 return resource?{resource,validAt:value.valid_at,knownAt:value.known_at}:null;
}
