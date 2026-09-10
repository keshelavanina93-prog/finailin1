"use client";
import {createContext,useContext} from "react";
import type {SourceReviewTarget} from "./source-review-route";
export {sourceReviewPath,sourceReviewTarget,sourceReviewUrl,type SourceReviewTarget} from "./source-review-route";
export const SourceReviewNavigation=createContext<((target:SourceReviewTarget)=>void)|null>(null);
export function useSourceReview(){
 const open=useContext(SourceReviewNavigation);
 if(!open)throw Error("Source review navigation requires the G8 workspace.");
 return open;
}
