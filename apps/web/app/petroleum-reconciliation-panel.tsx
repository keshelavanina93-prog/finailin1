"use client";
import {useEffect,useState} from "react";
import {operationsRequest} from "./operations-model";
import {Badge} from "./g8-ui";

type Row={dimensions:Record<string,string>;opening:string;receipts:string;dispatches:string;losses:string;closing:string;expected_closing:string;sales:string;variance:string;status:string};
type Result={contract:string;coverage:string;rows:Row[];counts:Record<string,number>;accounting_authorized:boolean;business_effect_authorized:boolean;warning:string};

export default function PetroleumReconciliationPanel({token,companyId}:{token:string;companyId?:string}){
 const [result,setResult]=useState<Result|null>(null);const [error,setError]=useState("");const [busy,setBusy]=useState(false);
  useEffect(()=>{const controller=new AbortController();const query=companyId?`?company_id=${encodeURIComponent(companyId)}`:"";
  void operationsRequest<Result>(`petroleum/reconciliation${query}`,token,controller.signal).then(value=>{setResult(value);setError("");}).catch(e=>{if(!controller.signal.aborted)setError(e instanceof Error?e.message:"Petroleum reconciliation unavailable");}).finally(()=>{if(!controller.signal.aborted)setBusy(false);});return()=>controller.abort();
 },[token,companyId]);
 return <section className="g8-panel petroleum-reconciliation" aria-label="Petroleum physical to financial reconciliation"><header className="g8-panel-heading"><div><p className="overline">PETROLEUM · CONSERVATION BRIDGE</p><h3>Physical-to-financial reconciliation</h3><p>Approved inventory, movement, measurement and sales resources are compared by operating dimension. This projection cannot post accounting or execute actions.</p></div><Badge>{busy?"Reading accepted facts":result?`${result.rows.length} dimension${result.rows.length===1?"":"s"}`:"Unavailable"}</Badge></header>{error&&<p className="g8-inline-error" role="alert">{error}</p>}{result&&<><p role="status">{result.coverage} · accounting authorized: {String(result.accounting_authorized)} · business effect authorized: {String(result.business_effect_authorized)}</p>{result.rows.length?<div className="g8-table-scroll"><table><thead><tr><th>Operating dimensions</th><th>Opening</th><th>Receipts</th><th>Dispatches</th><th>Losses</th><th>Closing</th><th>Variance</th><th>Status</th></tr></thead><tbody>{result.rows.map(row=><tr key={JSON.stringify(row.dimensions)}><td>{Object.entries(row.dimensions).filter(([,value])=>value).map(([key,value])=>`${key}: ${value}`).join(" · ")}</td><td>{row.opening}</td><td>{row.receipts}</td><td>{row.dispatches}</td><td>{row.losses}</td><td>{row.closing}</td><td>{row.variance}</td><td>{row.status}</td></tr>)}</tbody></table></div>:<p>No approved petroleum measurement resources are available in this company scope.</p>}<small>{result.warning}</small></>}</section>;
}
