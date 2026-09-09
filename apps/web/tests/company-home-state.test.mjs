import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import ts from "typescript";
const source=readFileSync(new URL("../app/company-home-state.ts",import.meta.url),"utf8");
const {assertHomeFinancialContext}=await import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText).toString("base64")}`);
const resource=(id,kind,attributes={})=>({resource_id:id,version_id:`${id}-v1`,object_type:kind,authority_state:"APPROVED",evidence_class:"SOURCE_BOUND",attributes});
function home(){return {company:resource("company","LegalEntity"),financial_context:{authority:"ACCOUNTING_CONTEXT_ONLY",source_scopes:[resource("source","SourceAccountingScope",{legal_entity_id:"company"})],ledgers:[{ledger:resource("ledger","Ledger",{legal_entity_id:"company",calendar_id:"calendar",chart_id:"chart",currency_id:"currency"}),calendar:resource("calendar","FiscalCalendar"),chart:resource("chart","LocalChartOfAccounts"),currency:resource("currency","Currency"),books:[resource("book","AccountingBook",{ledger_id:"ledger"})],periods:[resource("period","FiscalPeriod",{calendar_id:"calendar"})],context_ready:true}]}};}
test("accepted financial context retains exact linked company resources",()=>{
 const h=home();assert.doesNotThrow(()=>assertHomeFinancialContext(h));
 h.financial_context.ledgers=[];assert.doesNotThrow(()=>assertHomeFinancialContext(h));
 h.financial_context.source_scopes=[];assert.doesNotThrow(()=>assertHomeFinancialContext(h));
});
test("foreign or unsupported accounting drill cannot enter Home",()=>{
 for(const mutate of [h=>h.financial_context.authority="CERTIFIED",h=>h.financial_context.ledgers[0].ledger.attributes.legal_entity_id="other",h=>h.financial_context.ledgers[0].books[0].attributes.ledger_id="other",h=>h.financial_context.ledgers[0].periods[0].attributes.calendar_id="other",h=>h.financial_context.source_scopes[0].attributes.legal_entity_id="other",h=>h.financial_context.ledgers[0].currency.authority_state="REVOKED",h=>h.financial_context.ledgers[0].ledger.evidence_class="REFERENCE_TEMPLATE",h=>h.financial_context.ledgers[0].calendar=null]){
  const h=home();mutate(h);assert.throws(()=>assertHomeFinancialContext(h));
 }
});
test("unready context remains available without upgrading incomplete dependencies",()=>{
 const h=home();const ledger=h.financial_context.ledgers[0];ledger.context_ready=false;ledger.currency=null;
 assert.doesNotThrow(()=>assertHomeFinancialContext(h));ledger.context_ready=true;
 assert.throws(()=>assertHomeFinancialContext(h));
});
