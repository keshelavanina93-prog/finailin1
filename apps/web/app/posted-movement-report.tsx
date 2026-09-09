"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";

import {createOntologyClient} from "@g8/ontology-client";
import {pairPostingGroups,displayPostedAmount,type PostingGroup} from "./posted-movement-presentation";
import "./posted-movement-report.css";

import {useSourceReview} from "./source-review-navigation";
import {financeReportReference} from "./finance-report-reference";
import SemanticAnalysisWorkspace from "./semantic-analysis-workspace";
import AcceptedJournalReviewAction from "./accepted-journal-review-action";

export type PostedFunction = { resource_id: string; version_id: string; display_name: string };
type Group = PostingGroup;
type SourceRow = { row: number; attributes: { posting_date: string; source_recorder: string; account_code: string; credit_account_code: string }; cells: Record<string, { value: string; formula: string | null }>; numeric_observations: Record<string, { coordinate: string; literal_decimal: string | null }> };
type RetainedReport = { invocation_id: string; status: string; receipt_hash: string; output?: {
  function?: PostedFunction; query?: {known_at:string;valid_at:string};
  source_document: { filename: string; sheet: string;document_id?:string;scope?:{resource_id:string};binding?:{resource_id:string;version_id:string} };
  source_rows: SourceRow[];
  posted_movements: { groups: Group[]; coverage: { source_rows: number; included_rows: number; excluded_rows: number }; excluded_rows: { row: number; coordinate: string; reason: string }[] };
} };

export default function PostedMovementReport({ active=false,token, contextKey, functions, currency, eligible,expectedSource,initialInvocationId,onInspectFunction,onTraceFunction }: {
  active?:boolean;token: string; contextKey: string; functions: PostedFunction[]; currency: string; eligible: boolean;
  initialInvocationId?:string;
  expectedSource?:{company_id:string;document_id:string;scope_id:string;binding_id:string;binding_version_id:string;ledger_id:string;book_id:string;period_id:string;currency_id:string};
  onInspectFunction?:(reference:{resource_id:string;version_id:string;known_at?:string})=>void;
  onTraceFunction?:(reference:{resource_id:string;version_id:string;known_at?:string})=>void;
}) {
  const openSourceReview=useSourceReview();
  const [saved, setSaved] = useState<{ key: string; value: RetainedReport; currency:string } | null>(null);
  const sourceTitleId=useId();
  const [inspectorOpen,setInspectorOpen]=useState(false);
  const inspector=useRef<HTMLDialogElement|null>(null);
  const sourceTrigger=useRef<HTMLButtonElement|null>(null);
  const [labels,setLabels]=useState<{output:RetainedReport["output"];names:Record<string,string>;unavailable:boolean}|null>(null);
  const client=useMemo(()=>createOntologyClient({baseUrl:"/api/ontology",getToken:()=>token}),[token]);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [page, setPage] = useState(0);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), [contextKey]);
  const report = saved?.key === contextKey ? saved.value : null;
  const output = report?.output;
  const groups = output?.posted_movements.groups ?? [];
  const group = groups.find(row => `${row.account_code}:${row.side}` === selected);
  const excluded = output?.posted_movements.excluded_rows ?? [];
  const rows = output?.source_rows.filter(row => selected === "excluded"
    ? excluded.some(item => item.row === row.row)
    : group?.source_coordinates.includes(row.numeric_observations.source_amount?.coordinate)) ?? [];

  const worksheet=useMemo(()=>{try{return {rows:pairPostingGroups(output?.posted_movements.groups??[]),error:""};}catch(cause){return {rows:[],error:cause instanceof Error?cause.message:"Unsupported retained report"};}},[output]);
  useEffect(()=>{
    if(!output?.query)return;
    const controller=new AbortController();
    const pins=output.posted_movements.groups.flatMap(group=>group.account?[group.account]:[]);
    const ids=[...new Set(pins.map(pin=>pin.resource_id))];
    async function load(){
      const names:Record<string,string>={};let unavailable=false;
      try{
        for(let offset=0;offset<ids.length;offset+=100){
          const result=await client.query({object_type:"LocalAccount",resource_ids:ids.slice(offset,offset+100),search:"",filters:[],traversal:[],offset:0,limit:100,known_at:output!.query!.known_at,valid_at:output!.query!.valid_at},{signal:controller.signal});
          for(const resource of result.objects){const pin=pins.find(pin=>pin.resource_id===resource.resource_id&&pin.version_id===resource.version_id&&(!pin.content_hash||pin.content_hash===resource.content_hash));if(pin)names[pin.version_id]=resource.display_name;}
        }
        unavailable=pins.some(pin=>!names[pin.version_id])||output!.posted_movements.groups.some(group=>!group.account);
      }catch{unavailable=true;}
      if(!controller.signal.aborted)setLabels({output,names,unavailable});
    }
    void load();return()=>controller.abort();
  },[client,output]);
  useEffect(()=>{if(inspectorOpen&&!inspector.current?.open)inspector.current?.showModal();},[inspectorOpen]);
  function openSources(value:string,trigger:HTMLButtonElement){sourceTrigger.current=trigger;setSelected(value);setPage(0);setInspectorOpen(true);}
  function closeSources(){inspector.current?.close();setInspectorOpen(false);sourceTrigger.current?.focus({preventScroll:true});}
  function accountName(row:{debit?:Group;credit?:Group}){const group=row.debit??row.credit;let label=labels&&labels.output===output?(group?.account?labels.names[group.account.version_id]??"Account name unavailable":"Account name unavailable"):"Resolving account name…";const prefix=`${group?.account_code} · `;while(label.startsWith(prefix))label=label.slice(prefix.length);return label;}

  const expectedKey=JSON.stringify(expectedSource);
  const run=useCallback(async(functionRef?: PostedFunction,reopenId?:string) => {
    pending.current?.abort();
    const controller = new AbortController(); pending.current = controller;
    setBusy(true); setError("");
    const timer=setTimeout(()=>controller.abort(),20000);
    try {
      const now = new Date().toISOString();
      const response = await fetch(functionRef ? "/api/ontology/functions/invocations"
        : `/api/ontology/functions/invocations/${encodeURIComponent(reopenId??"")}`, {
        method: functionRef ? "POST" : "GET", signal: controller.signal,
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        ...(functionRef ? { body: JSON.stringify({ function: { resource_id: functionRef.resource_id,
          version_id: functionRef.version_id }, valid_at: now, known_at: now }) } : {}),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Calculation unavailable");
      if (!financeReportReference(data)) throw new Error("The guarded calculation did not complete. No totals were released.");
      const expected:typeof expectedSource=expectedKey?JSON.parse(expectedKey):undefined;
      const source=data.output.source_document;
      if(reopenId&&data.invocation_id!==reopenId)throw new Error("The saved report reference did not match.");
      if(expected&&(source.company_id!==expected.company_id||source.document_id!==expected.document_id||source.scope?.resource_id!==expected.scope_id||source.binding?.resource_id!==expected.binding_id||source.binding?.version_id!==expected.binding_version_id||["ledger_id","book_id","period_id","currency_id"].some(field=>source.context?.[field]!==expected[field as keyof typeof expected])))throw new Error("The retained report does not match this reviewed company, period and currency. Review its original accounting context.");
      if(functionRef&&(data.output.function?.resource_id!==functionRef.resource_id||data.output.function?.version_id!==functionRef.version_id))throw new Error("The calculation did not return the selected Function version.");
      if (controller.signal.aborted) return;
      setSaved({ key: contextKey, value: data,currency });
      if (functionRef) { setSelected(null); setPage(0); }
    } catch (failure) {
      if(pending.current===controller)setError(controller.signal.aborted?"The report request timed out. Reopen its retained result or retry.":failure instanceof Error ? failure.message : "Report unavailable");
    } finally { clearTimeout(timer);if(pending.current===controller)setBusy(false); }
  },[token,contextKey,expectedKey,currency]);
  // State updates follow the retained API response.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(()=>{if(initialInvocationId)void run(undefined,initialInvocationId);},[initialInvocationId,run]);

  if(report && expectedSource) return <section className="finance-retained-result" aria-label="Retained financial worksheet">
    {busy&&<p role="status">Checking the retained report…</p>}
    {error&&<p role="alert">{error}</p>}
    <SemanticAnalysisWorkspace owner="finance" expectedReceiptHash={report.receipt_hash} active={active} token={token} companyId={expectedSource.company_id} invocationId={report.invocation_id} onInspect={onInspectFunction} onOpenSourceReview={openSourceReview}/>
    <details className="finance-result-actions"><summary>Reviewed accounting actions</summary><AcceptedJournalReviewAction token={token} companyId={expectedSource.company_id} invocationId={report.invocation_id} disabled={busy}/></details>
  </section>;
  return <section className="posted-worksheet" aria-label="Posted account movements">
    <h3>Posted account movements · {saved?.key===contextKey?saved.currency:currency}</h3>
    <p>Amounts as posted in Сумма. VAT is not recalculated. Amount is preserved separately and excluded from totals.</p>
    <div className="posted-toolbar">{functions.map(item => <button className={output?"":"posted-primary"} key={item.version_id} disabled={busy || !eligible} onClick={() => void run(item)}>{output?"Run new calculation":functions.length===1?"Calculate posted account movements":item.display_name}</button>)}
      {output&&<button disabled={busy} onClick={()=>void run(undefined,report.invocation_id)}>Reopen saved report</button>}
      {excluded.length>0&&<button onClick={event=>openSources("excluded",event.currentTarget)}>Review {excluded.length} excluded row{excluded.length===1?"":"s"}</button>}
    </div>
    {!functions.length && <p>A reviewed calculation is not available for this source yet.</p>}
    {busy && <p role="status">Checking reviewed inputs and calculating retained postings…</p>}
    {error && <p role="alert">{error}</p>}
    {output && <>
      <p><strong>Partial source coverage:</strong> {output.posted_movements.coverage.included_rows} of {output.posted_movements.coverage.source_rows} rows included. Full-ledger completeness and financial-statement classification are not established.</p>
      {labels?.output===output&&labels.unavailable&&<p role="status">Some account names are unavailable at this report’s retained version. Account codes and exact amounts are unchanged.</p>}
      {worksheet.error?<p role="alert">{worksheet.error}</p>:<div className="posted-grid" tabIndex={0} aria-label="Account movement worksheet"><table>
        <caption>{output.source_document.filename} · {saved?.currency} · Displayed to 2 decimals; source precision is retained in evidence.</caption>
        <thead><tr><th scope="col">Account</th><th scope="col">Debit</th><th scope="col">Credit</th></tr></thead>
        <tbody>{worksheet.rows.map(row=><tr key={row.code} aria-selected={selected?.startsWith(`${row.code}:`)===true}>
          <th scope="row"><strong>{row.code}</strong><span title={accountName(row)}>{accountName(row)}</span></th>
          {(["debit","credit"] as const).map(side=>{const group=row[side];return <td key={side}>{group?<button className="posted-amount" aria-label={`${row.code} ${side} ${displayPostedAmount(group.value)}, ${group.source_coordinates.length} source rows`} title={`Exact retained amount: ${group.value}`} onClick={event=>openSources(`${row.code}:${side}`,event.currentTarget)}><span>{displayPostedAmount(group.value)}</span><small>{group.source_coordinates.length} rows ↗</small></button>:<span className="posted-absent" title="No retained group for this side">—</span>}</td>;})}
        </tr>)}</tbody>
      </table>{!worksheet.rows.length&&<p>No account groups were returned. This does not establish a zero balance.</p>}</div>}
      <dialog className="posted-source-dialog" ref={inspector} aria-labelledby={sourceTitleId} onCancel={event=>{event.preventDefault();closeSources();}}>
        <header><div><p>RETAINED SOURCE EVIDENCE</p><h4 id={sourceTitleId}>{selected==="excluded"?"Excluded source rows":`Account ${group?.account_code??""} · ${group?.side==="credit"?"Credit":"Debit"}`}</h4><p>{group&&accountName({debit:group})}</p><p>{output.source_document.filename} · {saved?.currency}</p></div><button autoFocus onClick={closeSources} aria-label="Close source inspector">Close ×</button></header>
        <div className="posted-source-body">
          {group&&selected!=="excluded"&&<p><strong>Exact retained amount: {group.value}</strong><br/>{group.source_coordinates.length} contributing rows. Worksheet rounding changes display only.</p>}
          {selected==="excluded"&&<><p>The posted amount is missing or is not a literal source number. No supplementary value or zero was substituted.</p>{excluded.map(item=><p key={item.row}><strong>{item.coordinate}</strong>: no literal posted amount.</p>)}</>}
          <section aria-label="Posted movement source contributors">
            {rows.slice(page*20,(page+1)*20).map(row=><details key={row.row}><summary>{output.source_document.sheet}!{row.row} · {row.attributes.posting_date} · {row.attributes.source_recorder}</summary><p>Debit {row.attributes.account_code} · Credit {row.attributes.credit_account_code}</p><div className="posted-cells"><table><caption>Original retained cells</caption><thead><tr><th>Source cell</th><th>Recorded value</th><th>Source formula</th></tr></thead><tbody>{Object.entries(row.cells).map(([coordinate,cell])=><tr key={coordinate}><th scope="row">{coordinate}</th><td>{cell.value||"Not recorded"}</td><td>{cell.formula??"—"}</td></tr>)}</tbody></table></div></details>)}
          </section>
        </div>
        <footer><span>{rows.length?`${page*20+1}–${Math.min((page+1)*20,rows.length)} of ${rows.length} source rows`:"No source rows"}</span><button disabled={page===0} onClick={()=>setPage(value=>value-1)}>Previous source rows</button><button disabled={(page+1)*20>=rows.length} onClick={()=>setPage(value=>value+1)}>Next source rows</button></footer>
      </dialog>
      <details><summary>Saved calculation evidence</summary><p>Invocation: {report.invocation_id}</p><p>Receipt: {report.receipt_hash}</p><p>This is retained calculation evidence. Reopening it does not authorize new accounting use.</p></details>
      {output.function&&<p>{onInspectFunction&&<button onClick={()=>onInspectFunction({...output.function!,known_at:output.query?.known_at})}>Explain calculation in NYX</button>}{onTraceFunction&&<button onClick={()=>onTraceFunction({...output.function!,known_at:output.query?.known_at})}>Show Function system trace</button>}</p>}
    </>}
  </section>;
}
