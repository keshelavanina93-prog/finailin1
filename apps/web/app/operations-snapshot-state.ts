import type {MapSnapshot,MapWorkspaceState} from "./operations-model";
import {restorationInstant} from "./definition-restoration-time";

export type MapQueryScope={companyId?:string;lens:MapWorkspaceState["lens"];validAt:string;knownAt:string};
/** Verify projection scope before any geography, count or resource reaches the canvas. */
export function assertMapSnapshot(value:MapSnapshot,scope:MapQueryScope):void {
 const fail=()=>{throw Error("Map response did not preserve the requested company, lens and exact snapshot.");};
 if(!value||value.type!=="FeatureCollection"||value.company_id!==(scope.companyId??null)||value.lens!==scope.lens)fail();
 const valid=restorationInstant(value.valid_at),known=restorationInstant(value.known_at);
 if(!valid||!known||(scope.validAt&&valid!==restorationInstant(scope.validAt))||(scope.knownAt&&known!==restorationInstant(scope.knownAt)))fail();
 const c=value.completeness;
 if(!c||c.limit!==500||c.scan_limit!==5000||[c.snapshot_bounded,c.features_truncated,c.unmapped_truncated].some(flag=>typeof flag!=="boolean")||
  !Array.isArray(value.features)||value.features.length>c.limit||!Array.isArray(value.unmapped)||value.unmapped.length>c.limit)fail();
 const counts=value.counts;
 if(!counts||[counts.assets,counts.mapped_in_bounds,counts.outside_bounds,counts.unmapped].some(count=>!Number.isSafeInteger(count)||count<0)||
  value.features.length!==Math.min(counts.mapped_in_bounds,c.limit)||value.unmapped!.length!==Math.min(counts.unmapped,c.limit))fail();
 const references=[...value.features.map(feature=>feature?.properties?.resource),...value.unmapped!.map(item=>item?.resource)];
 if(references.some(resource=>!resource||!resource.resource_id||!resource.version_id||!resource.content_hash||resource.authority_state!=="APPROVED")||
  new Set(references.map(resource=>resource.resource_id)).size!==references.length)fail();
}
