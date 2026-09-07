import type {ResourceProposalDetail} from "@finai/contracts";
import {displayName} from "./display-name";
import "./journal-proposal-review.css";

const record=(value:unknown):Record<string,unknown>=>value!==null&&typeof value==="object"&&!Array.isArray(value)?value as Record<string,unknown>:{};
const text=(value:unknown)=>typeof value==="string"?value:undefined;

export default function JournalProposalReview({detail}:{detail:ResourceProposalDetail}) {
 const mutations=detail.proposal.mutations;
 const journals=mutations.filter(item=>item.object_type==="JournalEntry");
 const lines=mutations.filter(item=>item.object_type==="JournalLine");
 if(!journals.length&&!lines.length)return null;
 const label=(id:unknown,fallback:string)=>{const match=mutations.find(item=>item.resource_id===id);return match?displayName(match.display_name):fallback;};
 return <section className="journal-proposal-review" aria-label="Journal proposal evidence"><header><h3>Journal lines &amp; balance evidence</h3><p>Proposed amounts appear exactly as submitted. Totals below are calculated and retained by the accounting validator. Balance is one review condition; it does not establish source authenticity or authorize posting on its own.</p></header>
 {journals.map(journal=>{
  const definition=record(journal.attributes.definition);
  const journalLines=lines.filter(line=>line.attributes.journal_id===journal.resource_id);
  const balance=detail.validation.journal_balances?.find(item=>item.journal_id===journal.resource_id&&item.contract==="balanced-journal/1");
  return <article key={journal.resource_id}><h4>{displayName(journal.display_name)}</h4><p>{text(journal.attributes.reference)??"No journal reference supplied"} · {label(journal.attributes.ledger_id,"Linked ledger")} · {label(journal.attributes.period_id,"Linked fiscal period")}</p>
   {balance?<p className="journal-balance-state"><strong>Balanced in retained validation</strong> · {balance.line_count} lines · {label(balance.currency_id,"Currency identified by retained reference")}</p>:<p role="status">No authoritative journal balance summary was retained for this proposal. No balance status is inferred from its displayed lines.</p>}
   <div className="journal-line-table"><table><thead><tr><th>Proposed line / account</th><th>Debit</th><th>Credit</th><th>Source evidence</th></tr></thead><tbody>{journalLines.map(line=>{
    const amount=record(line.attributes.amount);const side=text(line.attributes.side);const value=text(amount.amount);
    return <tr key={line.resource_id}><th scope="row">{displayName(line.display_name)}<small>{label(line.attributes.account_id,"Linked account")}</small>{side!=="DEBIT"&&side!=="CREDIT"&&<small>Side unavailable</small>}<details><summary>Line references</summary><p>Line: {line.resource_id}</p><p>Account: {text(line.attributes.account_id)??"Not supplied"}</p><p>Currency: {text(amount.currency_id)??"Not supplied"}</p><p>Effective from: {new Date(line.valid_from).toLocaleString()}</p></details></th><td>{side==="DEBIT"?(value??"Amount unavailable"):"—"}</td><td>{side==="CREDIT"?(value??"Amount unavailable"):"—"}</td><td>{label(line.attributes.source_record_id,"Linked source record")}<details><summary>Source provenance</summary><p>Source record: {text(line.attributes.source_record_id)??"Not supplied"}</p><p>Accounting binding: {text(line.attributes.accounting_binding_id)??"Not supplied on this line"}</p><p>Evidence class: {line.evidence_class?.replaceAll("_"," ")??"Not specified"}</p></details></td></tr>;
   })}</tbody>{balance&&<tfoot><tr><th scope="row">Server-validated totals</th><td>{balance.debit}</td><td>{balance.credit}</td><td>{balance.line_count} validated lines</td></tr></tfoot>}</table></div>
   {!journalLines.length&&<p>No proposed lines for this journal are present in this bundle.</p>}
   <details><summary>Journal scope &amp; retained references</summary><p>Proposal: {detail.proposal.proposal_id}</p><p>Journal: {journal.resource_id}</p><p>Legal entity: {text(journal.attributes.legal_entity_id)??"Not supplied"}</p><p>Ledger: {text(journal.attributes.ledger_id)??"Not supplied"}</p><p>Fiscal period: {text(journal.attributes.period_id)??"Not supplied"}</p><p>Accounting binding: {text(journal.attributes.accounting_binding_id)??"Not supplied"}</p><p>Declared contract: {text(definition.contract)??"Not supplied"}</p>{balance&&<p>Validated currency: {balance.currency_id} · validation status: {balance.status}</p>}<p>Declared line references: {Array.isArray(definition.line_ids)?definition.line_ids.filter(item=>typeof item==="string").join(", "):"Not supplied"}</p></details>
  </article>;
 })}
 {lines.some(line=>!journals.some(journal=>journal.resource_id===line.attributes.journal_id))&&<p role="status">Some proposed lines have no corresponding journal entry in this displayed bundle. No standalone balance claim is made for those lines.</p>}
 </section>;
}
