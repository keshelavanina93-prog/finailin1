"use client";

import {useRef,useState} from "react";
import type {AnalysisProjection,ReportSectionReference} from "@finai/contracts";
import SemanticWorksheet,{type WorksheetLayout} from "./semantic-worksheet";
import {reportCellLabel,reportEvidenceTarget} from "./retained-report-state";
import {useSourceReview} from "./source-review-navigation";
import "./semantic-analysis-workspace.css";
import "./reporting-workspace.css";

/** Edits only the report's reference composition; preview values stay server-owned. */
export function ReportSectionEditor({section,projection,companyId,disabled,onChange}:{section:ReportSectionReference;projection:AnalysisProjection;companyId:string;disabled:boolean;onChange:(section:ReportSectionReference)=>void}){
 const openSourceReview=useSourceReview();
 const scroll=useRef<HTMLDivElement>(null);
 const [layout,setLayout]=useState<WorksheetLayout>({widths:{},pinned:[],focus:null,left:0,search:""});
 const [error,setError]=useState("");
 const fields=projection.descriptor.fields;
 return <section className="reporting-section semantic-analysis" aria-label={section.title}>
  <label>Section title<input value={section.title} disabled={disabled} onChange={event=>onChange({...section,title:event.target.value})}/></label>
  <details className="reporting-section-filters"><summary>Report filters and arrangement</summary><p>Changes take effect in the next server preview. No measures are recalculated in this browser.</p><fieldset disabled={disabled}>{fields.filter(field=>field.filterable).map(field=>{
   const filter=section.filters.find(item=>item.field===field.key);
   return <label key={field.key}>{field.label}<select value={filter?String(field.options.findIndex(option=>option.state===filter.state&&option.value===filter.value)):""} disabled={!filter&&section.filters.length>=4} onChange={event=>{const filters=section.filters.filter(item=>item.field!==field.key),option=field.options[Number(event.target.value)];if(event.target.value!==""&&option)filters.push({field:field.key,state:option.state,value:option.value});onChange({...section,filters});}}><option value="">All retained values</option>{field.options.map((option,index)=><option key={index} value={index}>{reportCellLabel(option,field)}</option>)}</select></label>;
  })}<label>Arrange rows<select value={section.group_by??""} onChange={event=>onChange({...section,group_by:event.target.value||null})}><option value="">Original order</option>{fields.filter(field=>field.groupable).map(field=><option key={field.key} value={field.key}>{field.label}</option>)}</select></label></fieldset></details>
  {error&&<p role="alert">{error}</p>}
  <fieldset className="reporting-grid" disabled={disabled}><legend className="semantic-sr-only">Report section worksheet</legend><SemanticWorksheet projection={projection} fields={fields} columns={section.columns} layout={layout} onLayout={setLayout} onColumns={columns=>{if(!columns.length||columns.length>32){setError("Choose one to 32 report columns.");return;}setError("");onChange({...section,columns});}} scroll={scroll} label={reportCellLabel} onPick={row=>{try{const target=reportEvidenceTarget(projection,companyId,row.key);if(target)openSourceReview(target);else setError("This retained row has no contributor evidence.");}catch(cause){setError(String(cause));}}}/></fieldset>
 </section>;
}
