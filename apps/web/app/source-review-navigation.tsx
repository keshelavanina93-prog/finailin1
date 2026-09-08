"use client";
import {createContext,useContext} from "react";

export type SourceReviewTarget={companyId:string;invocationId:string};
const uuid="[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}";
const route=new RegExp(`^/source-review/(${uuid})/(${uuid})/?$`,"i");
export function sourceReviewTarget(pathname:string):SourceReviewTarget|null {
 const match=route.exec(pathname);
 return match?{companyId:match[1],invocationId:match[2]}:null;
}
export function sourceReviewPath(target:SourceReviewTarget):string {
 const path=`/source-review/${target.companyId}/${target.invocationId}`;
 if(!sourceReviewTarget(path))throw Error("Source review requires exact company and result references.");
 return path;
}
export const SourceReviewNavigation=createContext<((target:SourceReviewTarget)=>void)|null>(null);
export function useSourceReview(){
 const open=useContext(SourceReviewNavigation);
 if(!open)throw Error("Source review navigation requires the G8 workspace.");
 return open;
}
