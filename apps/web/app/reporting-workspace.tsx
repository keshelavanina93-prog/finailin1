"use client";

import {useEffect,useMemo,useRef,useState} from "react";
import type {AnalysisProjection,ReportComposition,ReportPreview,ReportSectionReference,RetainedReport,RetainedReportPage} from "@finai/contracts";
import SemanticWorksheet,{type WorksheetLayout} from "./semantic-worksheet";
import {assertReportPreview,downloadRetainedReport,listRetainedReports,reportCellLabel,reportCompositionReferences,reportEvidenceTarget,reopenRetainedReport,saveRetainedReport,previewRetainedReport,sameReportComposition} from "./retained-report-state";
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

type ReportWorkspaceSection={section:ReportSectionReference;projection:AnalysisProjection};

/** Route-native reporting workflow. Results enter from the owning Finance route; all values and artifacts remain server-owned. */
export function RetainedReportingWorkspace({token,companyId,initialSections,active=true}:{token:string;companyId:string;initialSections:ReportWorkspaceSection[];active?:boolean}){
 const [title,setTitle]=useState("Retained financial report");
 const [commentary,setCommentary]=useState("");
 const [sections,setSections]=useState<ReportWorkspaceSection[]>(initialSections.slice(0,8));
 const [preview,setPreview]=useState<ReportPreview|null>(null);
 const [saved,setSaved]=useState<RetainedReport|null>(null);
 const [page,setPage]=useState<RetainedReportPage|null>(null);
 const [busy,setBusy]=useState(false);
 const [error,setError]=useState("");
 const [message,setMessage]=useState("");
 const initialKey=useMemo(()=>initialSections.map(item=>item.section.section_id).join("|"),[initialSections]);
 const composition=useMemo<ReportComposition>(()=>({company_id:companyId,valid_at:sections[0]?.projection.descriptor.valid_at??"",known_at:sections[0]?.projection.descriptor.known_at??"",title,commentary,sections:sections.map(item=>item.section)}),[companyId,title,commentary,sections]);
 useEffect(()=>{setSections(initialSections.slice(0,8));setPreview(null);setSaved(null);},[companyId,initialKey]);
 useEffect(()=>{if(!active)return;let cancelled=false;listRetainedReports(token,companyId).then(value=>{if(!cancelled)setPage(value);}).catch(cause=>{if(!cancelled)setError(String(cause));});return()=>{cancelled=true;};},[active,token,companyId]);
 const setSection=(index:number,section:ReportSectionReference)=>{setSections(current=>current.map((item,itemIndex)=>itemIndex===index?{...item,section}:item));setPreview(null);setSaved(null);setMessage("");};
 const runPreview=async()=>{setBusy(true);setError("");setMessage("");try{const next=reportCompositionReferences(composition);const value=await previewRetainedReport(token,next);assertReportPreview(value,next);setPreview(value);setMessage("Server preview verified for this exact composition.");}catch(cause){setPreview(null);setError(String(cause));}finally{setBusy(false);}};
 const runSave=async()=>{if(!preview||!sameReportComposition(preview.snapshot.composition,composition)){setError("Preview this exact composition before saving.");return;}setBusy(true);setError("");try{const report=await saveRetainedReport(token,composition,preview,saved?.reference.proposal_id??null);setSaved(report);setPage(current=>current?{...current,items:[report,...current.items.filter(item=>item.reference.proposal_id!==report.reference.proposal_id)]}:current);setMessage(`Saved ${report.title} as an immutable draft.`);}catch(cause){setError(String(cause));}finally{setBusy(false);}};
 const reopen=async(proposalId:string)=>{setBusy(true);setError("");try{const report=await reopenRetainedReport(token,companyId,proposalId);setSaved(report);setTitle(report.title);setCommentary(report.snapshot.composition.commentary);setMessage(`Reopened ${report.title}; exact retained version is active.`);}catch(cause){setError(String(cause));}finally{setBusy(false);}};
 return <main className="retained-reporting-workspace" aria-label="Retained reporting workspace">
  <header className="reporting-workspace-header"><div><p className="semantic-eyebrow">Reporting · {companyId}</p><h1>Build a retained financial report</h1><p>Choose retained analyses from Finance, arrange readable sections, then preview and save the server-owned result.</p></div><div className="reporting-actions"><button type="button" onClick={runPreview} disabled={busy||sections.length===0}>Preview report</button><button type="button" className="primary" onClick={runSave} disabled={busy||!preview}>Save immutable report</button></div></header>
  {error&&<p role="alert" className="reporting-error">{error}</p>}{message&&<p role="status" className="reporting-message">{message}</p>}
  <section className="reporting-compose" aria-label="Report details"><label>Report title<input value={title} onChange={event=>{setTitle(event.target.value);setPreview(null);setSaved(null);}} disabled={busy}/></label><label>Commentary<textarea value={commentary} onChange={event=>{setCommentary(event.target.value);setPreview(null);setSaved(null);}} disabled={busy} rows={2}/></label></section>
  {sections.length===0?<div className="reporting-empty">Select one or more retained analyses from the Finance workspace to begin.</div>:<div className="reporting-sections">{sections.map((item,index)=><ReportSectionEditor key={item.section.section_id} section={item.section} projection={item.projection} companyId={companyId} disabled={busy} onChange={section=>setSection(index,section)}/>)}</div>}
  {preview&&<section className="reporting-preview" aria-label="Verified report preview"><div><strong>Preview verified</strong><span>{preview.snapshot.sections.length} section{preview.snapshot.sections.length===1?"":"s"} · {preview.snapshot_sha256.slice(0,12)}…</span></div><p>Rows, contributors, revisions and authority observations remain attached to the exact retained analyses.</p></section>}
  <section className="reporting-history" aria-label="Saved reports"><div className="reporting-history-heading"><h2>Saved reports</h2><span>{page?.items.length??0}</span></div>{page?.items.length?<ul>{page.items.map(item=><li key={item.reference.proposal_id}><button type="button" onClick={()=>reopen(item.reference.proposal_id)} disabled={busy}>{item.title}</button><span>{item.review_state}</span><small>{item.reference.proposal_id.slice(0,8)}…</small></li>)}</ul>:<p>No retained reports saved for this company yet.</p>}{saved&&<div className="reporting-export-actions"><span>Active version: {saved.reference.proposal_id.slice(0,12)}…</span><button type="button" onClick={()=>downloadRetainedReport(token,companyId,saved,"xlsx")} disabled={busy}>Download XLSX</button><button type="button" onClick={()=>downloadRetainedReport(token,companyId,saved,"html")} disabled={busy}>Open print HTML</button></div>}</section>
 </main>;
}
