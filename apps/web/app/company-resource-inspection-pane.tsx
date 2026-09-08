"use client";
import {useLayoutEffect,useRef,type ReactNode} from "react";
import type {CompanyResourceInspection} from "./company-resource-inspection";
export default function CompanyResourceInspectionPane({origin,busy,error,onClose,children}:{origin:CompanyResourceInspection|null;busy:boolean;error:string;onClose:()=>void;children:ReactNode}) {
 const close=useRef<HTMLButtonElement>(null);
 useLayoutEffect(()=>{close.current?.focus({preventScroll:true});},[]);
 return <aside className="g8-company-inspection" aria-label="Company resource inspection" onKeyDown={event=>{if(event.key==="Escape"){event.preventDefault();event.stopPropagation();onClose();}}}>
  <header><div><p className="overline">CONTEXTUAL EVIDENCE</p><h2>Resource inspection</h2></div><button ref={close} type="button" onClick={onClose} aria-label="Close resource inspection">Close</button></header>
  <div className="g8-company-inspection-body">
   {origin&&<p className="g8-context-note"><strong>{origin.company.display_name}</strong><br/>Company effective {new Date(origin.validAt).toLocaleString()}<br/>Company known {new Date(origin.knownAt).toLocaleString()}<br/>Resource inspected as known {new Date(origin.resource.known_at).toLocaleString()}</p>}
   {busy&&<p role="status">Reading the exact retained resource version...</p>}
   {error&&<p role="alert">{error}</p>}
   {!busy&&!error&&children}
  </div>
 </aside>;
}
