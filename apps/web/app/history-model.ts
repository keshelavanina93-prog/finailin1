import type {CanonicalResource} from "@finai/contracts";

export type HistorySelection = {resource_id:string; version_id:string; company_id:string; known_at?:string};
export type HistoryValue = {present:boolean; value?:unknown};
export type HistoryChange = {path:string[]; before:HistoryValue; after:HistoryValue; changed:boolean};

// Compare returned evidence only. Missing values may also be withheld by policy.
export function compareVersions(before:CanonicalResource, after:CanonicalResource):HistoryChange[] {
  const rows:HistoryChange[]=[];
  const object=(v:unknown):v is Record<string,unknown>=>v!==null&&typeof v==="object"&&!Array.isArray(v);
  function visit(path:string[], a:HistoryValue, b:HistoryValue) {
    if(object(a.value)&&object(b.value)) {
      for(const key of [...new Set([...Object.keys(a.value),...Object.keys(b.value)])].sort())
        visit([...path,key],{present:Object.hasOwn(a.value,key),value:a.value[key]},{present:Object.hasOwn(b.value,key),value:b.value[key]});
    } else if(Array.isArray(a.value)&&Array.isArray(b.value)) {
      for(let i=0;i<Math.max(a.value.length,b.value.length);i++)
        visit([...path,`Item ${i+1}`],{present:i<a.value.length,value:a.value[i]},{present:i<b.value.length,value:b.value[i]});
    } else rows.push({path,before:a,after:b,changed:a.present!==b.present||!equal(a.value,b.value)});
  }
  function equal(a:unknown,b:unknown):boolean {
    if(Object.is(a,b))return true;
    if(object(a)&&object(b))return Object.keys(a).length===Object.keys(b).length&&Object.keys(a).every(k=>Object.hasOwn(b,k)&&equal(a[k],b[k]));
    if(Array.isArray(a)&&Array.isArray(b))return a.length===b.length&&a.every((v,i)=>equal(v,b[i]));
    return false;
  }
  for(const field of ["display_name","authority_state","evidence_class","valid_from","valid_to","attributes"] as const)
    visit(field==="attributes"?[]:[field],{present:true,value:before[field]},{present:true,value:after[field]});
  return rows;
}
