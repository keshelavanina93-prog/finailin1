import type {CanonicalResource} from "@finai/contracts";
import type {Geometry,Feature,FeatureCollection} from "geojson";
export interface MapProperties {resource:CanonicalResource;geometry_resource_id?:string;geometry_version_id?:string}
export type MapFeature=Feature<Geometry,MapProperties>;
export interface MapSnapshot extends FeatureCollection<Geometry,MapProperties> {
 valid_at:string;known_at:string;lens:string;completeness:{snapshot_bounded:boolean;features_truncated:boolean;unmapped_truncated:boolean;scan_limit:number;limit:number};
 counts:{assets:number;mapped_in_bounds:number;outside_bounds:number;unmapped:number};
 unmapped?:Array<{resource:CanonicalResource;reason:string}>;
 warnings?:string[];
}
export interface MapWorkspaceState {lens:"enterprise_assets"|"gas_network";validAt:string;knownAt:string;center:[number,number];zoom:number}
export const initialMapState:MapWorkspaceState={lens:"enterprise_assets",validAt:"",knownAt:"",center:[43.5,42.1],zoom:6};
export interface MapSelection {resource:CanonicalResource;validAt:string;knownAt:string}
export async function operationsRequest<T>(path:string,token:string,signal?:AbortSignal,body?:unknown):Promise<T>{
 const result=await fetch(`/api/operations/${path}`,{method:body?"POST":"GET",headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},cache:"no-store",signal,body:body?JSON.stringify(body):undefined});
 const data=await result.json();if(!result.ok)throw new Error(typeof data.detail==="string"?data.detail:`Operations request failed (${result.status})`);return data;
}
