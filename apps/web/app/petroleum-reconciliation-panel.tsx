"use client";
import {useEffect,useState} from "react";
import {operationsRequest} from "./operations-model";
import {Badge} from "./g8-ui";
import type {PetroleumVarianceCollection} from "@finai/contracts";

type Result=PetroleumVarianceCollection & {coverage:string;counts:Record<string,number>;accounting_authorized:boolean;business_effect_authorized:boolean;warning:string};

export default function PetroleumReconciliationPanel({token,companyId}:{token:string;companyId?:string}){
 const [result,setResult]=useState<Result|null>(null);const [error,setError]=useState("");const [busy,setBusy]=useState(false);
  useEffect(()=>{const controller=new AbortController();const query=companyId?`?company_id=${encodeURIComponent(companyId)}`:"";
  void operationsRequest<Result>(`petroleum/variances${query}`,token,controller.signal).then(value=>{setResult(value);setError("");}).catch(e=>{if(!controller.signal.aborted)setError(e instanceof Error?e.message:"Petroleum variance control unavailable");}).finally(()=>{if(!controller.signal.aborted)setBusy(false);});return()=>controller.abort();
 },[token,companyId]);
 return <section className="g8-panel petroleum-reconciliation" aria-label="Petroleum physical to financial reconciliation"><header className="g8-panel-heading"><div><p className="overline">PETROLEUM · FULL-DIMENSIONAL CONTROL</p><h3>Conservation, evidence and financial bridge</h3><p>Every variance is scoped, bitemporal and evidence-linked. Physical observations never become accounting authority without governed approval.</p></div><Badge>{busy?"Reading accepted facts":result?`${result.rows.length} control object${result.rows.length===1?"":"s"}`:"Unavailable"}</Badge></header>{error&&<p className="g8-inline-error" role="alert">{error}</p>}{result&&<><p role="status">{result.coverage} · accounting authorized: {String(result.accounting_authorized)} · business effect authorized: {String(result.business_effect_authorized)}</p>{result.rows.length?<div className="g8-table-scroll"><table><thead><tr><th>Governed scope</th><th>Expected</th><th>Measured</th><th>Variance</th><th>Review</th><th>Financial</th><th>Evidence gaps</th></tr></thead><tbody>{result.rows.map(row=><tr key={row.variance_id}><td>{Object.entries(row.dimensions).filter(([,value])=>value).map(([key,value])=>`${key}: ${value}`).join(" · ")}</td><td>{row.physical.expected_closing}</td><td>{row.physical.measured_closing}</td><td>{row.physical.variance_quantity} ({row.physical.variance_pct}%)</td><td>{row.review.status}<br/><small>{row.review.lifecycle}</small></td><td>{row.financial.status}</td><td>{row.evidence.gaps.length?row.evidence.gaps.join(", "):"None recorded"}</td></tr>)}</tbody></table></div>:<p>No accepted petroleum control objects are available in this company scope.</p>}<small>{result.warning} · action execution: {result.action_execution}</small></>}</section>;
}
