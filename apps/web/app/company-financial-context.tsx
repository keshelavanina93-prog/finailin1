"use client";
import type {CanonicalResource,CompanyHomeDescriptor} from "@finai/contracts";
import {displayName} from "./display-name";
import type {SelectedAccountingContext} from "./company-accounting-selection";

export function SelectedAccountingStrip({selection,onInspect,onAccounting}:{selection:SelectedAccountingContext;onInspect:(node:CanonicalResource,knownAt:string)=>void;onAccounting:()=>void}){
 return <section className="c360-section" aria-label="Selected accounting context">
  <header><h3>Selected accounting context</h3><button className="c360-text-button" onClick={onAccounting}>Choose accounting context</button></header>
  {selection.state!=="VALIDATED"?<p className="c360-message" role="status"><strong>{selection.state==="UNSELECTED"?"No accounting selection":"Selection unavailable"}</strong> · {selection.reason}</p>:<>
   <div className="c360-table-wrap"><table><caption className="c360-small">Validated for this company snapshot · accounting context only</caption><thead><tr><th>Ledger</th><th>Book</th><th>Fiscal period</th><th>Currency</th></tr></thead><tbody><tr>{[selection.ledger,selection.book,selection.period,selection.currency].map(node=><td key={node.version_id}><button className="c360-text-button" onClick={()=>onInspect(node,selection.knownAt)}>{displayName(node.display_name)}</button></td>)}</tr></tbody></table></div>
   <details className="c360-message"><summary>Advanced · exact selection references & snapshot</summary><p>Effective {selection.validAt} · known {selection.knownAt}</p><dl>{Object.entries(selection.pins).map(([field,pin])=><div key={field}><dt>{field.replaceAll("_"," ")}</dt><dd><code>{pin.resource_id} · {pin.version_id}</code></dd></div>)}</dl></details>
  </>}
  <p className="c360-message">The fiscal period is the accounting selection. It does not change operational effective or known time, filter all company coverage, or certify balances or close.</p>
 </section>;
}

type FinancialContext=CompanyHomeDescriptor["financial_context"];
type Props={context:FinancialContext;knownAt:string;onInspect?:(node:CanonicalResource,knownAt:string)=>void;onAccounting?:()=>void};
const day=(value:unknown)=>typeof value==="string"?value:"Not recorded";
export default function CompanyFinancialContext({context,knownAt,onInspect,onAccounting}:Props){
 return <section className="home-accounting-condition" aria-label="Retained financial coverage">
  <header><div><h3>Accounting coverage</h3><p>{context.ledgers.length?"Accepted ledger context available":"Ledger authority not established"} · {context.source_scopes.length} linked source {context.source_scopes.length===1?"boundary":"boundaries"}</p></div>{onAccounting&&<button onClick={onAccounting}>Open accounting controls</button>}</header>
  {context.ledgers.length?<div className="home-result-grid"><table><caption>Retained ledgers · balances and close certification are separate</caption><thead><tr><th>Ledger / currency</th><th>Books & periods</th><th>Context</th></tr></thead><tbody>{context.ledgers.map(item=><tr key={item.ledger.version_id}><th scope="row">{onInspect?<button className="g8-link" onClick={()=>onInspect(item.ledger,knownAt)}>{displayName(item.ledger.display_name)}</button>:displayName(item.ledger.display_name)}<small>{item.currency?displayName(item.currency.display_name):"Currency unresolved"}</small></th><td><details><summary>{item.books.length} books · {item.periods.length} defined periods</summary><ul>{item.books.map(book=><li key={book.version_id}>{displayName(book.display_name)}</li>)}</ul><ul>{item.periods.map(period=><li key={period.version_id}>{onInspect?<button className="g8-link" onClick={()=>onInspect(period,knownAt)}>{displayName(period.display_name)}</button>:displayName(period.display_name)}</li>)}</ul></details></td><td><span className={item.context_ready?"home-context-ready":"home-context-review"}>{item.context_ready?"Ready for selection":"Dependencies unresolved"}</span></td></tr>)}</tbody></table></div>:<p className="home-condition-empty">Source evidence can be reviewed, but it cannot stand in for an accepted ledger or financial statement.</p>}
  <details className="home-source-boundaries"><summary>Source coverage behind this context</summary>{context.source_scopes.length?<ul>{context.source_scopes.map(scope=><li key={scope.version_id}>{onInspect?<button className="g8-link" onClick={()=>onInspect(scope,knownAt)}>{displayName(scope.display_name)}</button>:displayName(scope.display_name)}<span>{day(scope.attributes.observed_from)} — {day(scope.attributes.observed_through)}</span></li>)}</ul>:<p>No accepted company-bound accounting source scope in this snapshot.</p>}<p>{context.limitation}</p></details>
 </section>;
}
