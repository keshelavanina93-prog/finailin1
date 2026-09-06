"use client";

import {useEffect,useRef,useState,type FormEvent} from "react";
import type {Principal} from "@finai/contracts";
import {Panel} from "./g8-ui";

type Document = {document_id:string;filename:string;sha256:string;byte_length:number};
type Observation = {companies:{source_label:string;row_count:number;first_coordinate:string}[];unassigned_row_count:number};
type Preview = {sheets:string[];sheet?:string;row_count?:number;column_count?:number;offset?:number;next_offset?:number|null;rows?:{row:number;cells:{coordinate:string;type:number;value:string|number}[]}[]};

export default function SourceDocuments({token,principal,onProposal}:{token:string;principal:Principal;onProposal:(id:string)=>void}) {
  const [document,setDocument]=useState<Document|null>(null);
  const [documents,setDocuments]=useState<Document[]>([]);
  const [reference,setReference]=useState("");
  const [observed,setObserved]=useState<Observation|null>(null);
  const [preview,setPreview]=useState<Preview|null>(null);
  const [mode,setMode]=useState("company_column");
  const [sheet,setSheet]=useState("");const [row,setRow]=useState(2);const [column,setColumn]=useState(10);
  const [busy,setBusy]=useState(false);const [error,setError]=useState("");
  const pending=useRef<AbortController|null>(null);
  useEffect(()=>()=>pending.current?.abort(),[token]);
  useEffect(()=>{const controller=new AbortController();
    async function load(){try{const rows:Document[]=[];
      for(let offset=0;;offset+=100){const response=await fetch(`/api/ontology/source-documents?offset=${offset}`,{headers:{Authorization:`Bearer ${token}`},signal:controller.signal,cache:"no-store"});if(!response.ok)throw new Error("Retained document inventory unavailable");const page:Document[]=await response.json();rows.push(...page);if(page.length<100)break;}
      if(!controller.signal.aborted)setDocuments(rows);
    }catch(failure){if(!controller.signal.aborted)setError(failure instanceof Error?failure.message:"Inventory unavailable");}}
    void load();return()=>controller.abort();
  },[token,document]);
  async function run(action:(signal:AbortSignal)=>Promise<void>){
    pending.current?.abort();const controller=new AbortController();pending.current=controller;setBusy(true);setError("");
    try{await action(controller.signal);}catch(failure){if(!controller.signal.aborted)setError(failure instanceof Error?failure.message:"Source request failed");}
    finally{if(!controller.signal.aborted)setBusy(false);}
  }
  async function post(path:string,body:BodyInit,signal:AbortSignal,binary=false){
    const response=await fetch(`/api/ontology/source-documents${path}`,{method:"POST",headers:{Authorization:`Bearer ${token}`,"Content-Type":binary?"application/octet-stream":"application/json"},body,signal});
    const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==="string"?data.detail:"Source request rejected");return data;
  }
  function upload(event:FormEvent<HTMLFormElement>){event.preventDefault();const file=new FormData(event.currentTarget).get("file");
    if(!(file instanceof File)||!file.size)return;
    if(file.size>32_000_000){setError("Select an original document no larger than 32 MB.");return;}
    void run(async signal=>{const data=await post(`?filename=${encodeURIComponent(file.name)}`,file,signal,true);if(signal.aborted)return;setDocument(data);setReference(data.document_id);setObserved(null);});
  }
  function inspect(propose=false){void run(async signal=>{
    const data=await post(`/${reference}/companies/${propose?"proposal":"inspect"}`,JSON.stringify({mode,sheet,header_row:row,column}),signal);
    if(signal.aborted)return;if(propose)onProposal(data.proposal.proposal_id);else setObserved(data);
  });}
  function change(){setObserved(null);}
  function readSource(offset=0){void run(async signal=>{
    const query=sheet?`?sheet=${encodeURIComponent(sheet)}&offset=${offset}`:"";
    const response=await fetch(`/api/ontology/source-documents/${reference}/preview${query}`,{headers:{Authorization:`Bearer ${token}`},signal,cache:"no-store"});
    const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==="string"?data.detail:"Source preview unavailable");if(!signal.aborted)setPreview(data);
  });}
  function download(){void run(async signal=>{
    const response=await fetch(`/api/ontology/source-documents/${reference}/content`,{headers:{Authorization:`Bearer ${token}`},signal,cache:"no-store"});
    if(!response.ok)throw new Error("Original source unavailable");const blob=await response.blob();
    const hash=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",await blob.arrayBuffer())),b=>b.toString(16).padStart(2,"0")).join("");
    if(hash!==response.headers.get("x-source-sha256")||(document&&hash!==document.sha256))throw new Error("Source integrity verification failed");
    if(signal.aborted)return;const url=URL.createObjectURL(blob);const link=window.document.createElement("a");link.href=url;link.download=document?.filename??"retained-source.xls";link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });}
  return <Panel title="Original source documents"><p>Retain the original workbook, then inspect its company evidence. Accounting interpretation and company review remain separate steps.</p>
    {principal.permissions.includes("ingest")&&<form onSubmit={upload}><label>Original document (maximum 32 MB)<input type="file" name="file" required disabled={busy}/></label><button disabled={busy}>Retain original</button></form>}
    {document&&<p role="status">Retained {document.filename} · {document.byte_length.toLocaleString()} bytes · SHA-256 {document.sha256}</p>}
    <fieldset disabled={busy}><legend>Inspect retained company evidence</legend>
      <label>Retained sources<select value={reference} onChange={e=>{setReference(e.target.value);setDocument(documents.find(d=>d.document_id===e.target.value)??null);setPreview(null);setSheet("");change();}}><option value="">Select an original source</option>{documents.map(d=><option key={d.document_id} value={d.document_id}>{d.filename}</option>)}</select></label>
      <label>Retained document reference<input value={reference} onChange={e=>{setReference(e.target.value);setDocument(null);setPreview(null);change();}} placeholder="doc_…"/></label>
      <label>Source format<select value={mode} onChange={e=>{setMode(e.target.value);change();}}><option value="company_column">Company column in XLS</option><option value="1c_tb_title">1C trial balance title in XLS</option></select></label>
      <label>Worksheet name<input value={sheet} list="source-worksheet-names" onChange={e=>{setSheet(e.target.value);change();}}/></label><datalist id="source-worksheet-names">{preview?.sheets.map(name=><option key={name} value={name}/>)}</datalist>
      <button disabled={!/^doc_[a-f0-9]{64}$/.test(reference)} onClick={()=>readSource()}>Read source cells / list worksheets</button>
      {principal.permissions.includes("export")&&<button disabled={!/^doc_[a-f0-9]{64}$/.test(reference)} onClick={download}>Download verified original</button>}
      {mode==="company_column"&&<><label>Header row<input type="number" min={1} max={100000} value={row} onChange={e=>{setRow(Number(e.target.value));change();}}/></label><label>Company column number (A = 1)<input type="number" min={1} max={256} value={column} onChange={e=>{setColumn(Number(e.target.value));change();}}/></label></>}
      <button disabled={!/^doc_[a-f0-9]{64}$/.test(reference)||!sheet} onClick={()=>inspect()}>Inspect company evidence</button>
    </fieldset>
    {preview&&<div><p>Worksheets: {preview.sheets.join(" · ")}</p>{preview.rows&&<><p>{preview.sheet}: {preview.row_count?.toLocaleString()} source rows. Cell values are unclassified; totals, detail, debit and credit are preserved separately.</p><div className="g8-table-scroll"><table><thead><tr><th>Source row</th>{Array.from({length:preview.column_count??0},(_,i)=><th key={i}>Column {i+1}</th>)}</tr></thead><tbody>{preview.rows.map(row=><tr key={row.row}><th>{row.row}</th>{row.cells.map(cell=><td key={cell.coordinate} title={`${cell.coordinate} · XLS cell type ${cell.type}`}>{String(cell.value)}</td>)}</tr>)}</tbody></table></div><button disabled={busy||!preview.offset||preview.sheet!==sheet} onClick={()=>readSource(Math.max(0,(preview.offset??0)-50))}>Previous rows</button><button disabled={busy||preview.next_offset==null||preview.sheet!==sheet} onClick={()=>readSource(preview.next_offset??0)}>Next rows</button></>}</div>}
    {observed&&<><table><thead><tr><th>Source company label</th><th>Observed cells</th><th>First source cell</th></tr></thead><tbody>{observed.companies.map(company=><tr key={company.source_label}><td>{company.source_label}</td><td>{company.row_count}</td><td>{company.first_coordinate}</td></tr>)}</tbody></table><p>{observed.unassigned_row_count} nonempty rows without a company label. Registration, group ownership, licences and chart applicability are not established by these labels.</p>{principal.permissions.includes("ontology_propose")&&<button disabled={busy||!!observed.unassigned_row_count||!observed.companies.length} onClick={()=>inspect(true)}>Propose observed companies for review</button>}</>}
    {busy&&<p role="status">Processing original source…</p>}{error&&<p role="alert">{error}</p>}
  </Panel>;
}
