import test from "node:test";
import assert from "node:assert/strict";
import {loadTypeScript} from "./load-typescript.mjs";
const {selectedAccountingContext}=await loadTypeScript(new URL("../app/company-accounting-selection.ts",import.meta.url));
const id=n=>`00000000-0000-4000-8000-${String(n).padStart(12,"0")}`;
const node=(n,type,attributes={})=>({resource_id:id(n),version_id:id(n+100),object_type:type,attributes,display_name:`Exact ${type}`,authority_state:"APPROVED",evidence_class:"AUTHENTIC_SOURCE",access_entity:"test-company"});
function fixture(){
 const company=node(1,"LegalEntity"),calendar=node(2,"FiscalCalendar"),chart=node(3,"LocalChartOfAccounts"),currency=node(4,"Currency");
 const ledger=node(5,"Ledger",{legal_entity_id:company.resource_id,calendar_id:calendar.resource_id,chart_id:chart.resource_id,currency_id:currency.resource_id});
 const book=node(6,"AccountingBook",{ledger_id:ledger.resource_id}),period=node(7,"FiscalPeriod",{calendar_id:calendar.resource_id,start_date:"2024-01-01",end_date:"2024-12-31"});
 const nodes={legal_entity_id:company,ledger_id:ledger,book_id:book,period_id:period,chart_id:chart,currency_id:currency,calendar_id:calendar};
 return {companyId:company.resource_id,choice:{companyId:company.resource_id,ledgerId:ledger.resource_id,bookId:book.resource_id,periodId:period.resource_id},
  context:{company,ledgers:[{ledger,calendar_id:calendar,chart_id:chart,currency_id:currency,books:[book],periods:[period],ready:true}]},
  validAt:"2026-09-08T01:00:00.123456Z",knownAt:"2026-09-08T02:00:00.123456Z",selectionKey:"current-actor/company/snapshot/selection",
  validation:{key:"current-actor/company/snapshot/selection",error:"",pins:Object.fromEntries(Object.entries(nodes).map(([key,node])=>[key,{resource_id:node.resource_id,version_id:node.version_id}]))}};
}
const refused=input=>{const result=selectedAccountingContext(input);assert.equal(result.state,"UNAVAILABLE");assert.equal("ledger" in result,false);assert.equal("pins" in result,false);};
test("exact seven server pins resolve original snapshot resources while fiscal period remains separate",()=>{
 const input=fixture(),result=selectedAccountingContext(input);
 assert.equal(result.state,"VALIDATED");
 assert.equal(result.ledger,input.context.ledgers[0].ledger);
 assert.equal(result.book,input.context.ledgers[0].books[0]);
 assert.equal(result.period,input.context.ledgers[0].periods[0]);
 assert.equal(result.currency,input.context.ledgers[0].currency_id);
 assert.equal(result.knownAt,"2026-09-08T02:00:00.123456Z");
 assert.equal(result.validAt,"2026-09-08T01:00:00.123456Z");
 assert.equal(result.period.attributes.start_date,"2024-01-01");
 assert.deepEqual(result.pins,input.validation.pins);
 assert.notEqual(result.pins,input.validation.pins);
});
test("empty selection is distinct from incomplete selection, unavailable snapshot and server refusal",()=>{
 const empty=fixture();Object.assign(empty.choice,{ledgerId:"",bookId:"",periodId:""});
 assert.equal(selectedAccountingContext(empty).state,"UNSELECTED");
 for(const field of ["ledgerId","bookId","periodId"]){const input=fixture();input.choice[field]="";refused(input);}
 for(const patch of [{context:null},{validAt:"2026-09-08"},{knownAt:""},{validation:null},{validation:{key:fixture().selectionKey,pins:fixture().validation.pins,error:"403"}}])refused({...fixture(),...patch});
});
test("company, actor, cutoff and choice changes cannot reuse a previous validation",()=>{
 for(const key of ["other-actor/company/snapshot/selection","current-actor/other-company/snapshot/selection","current-actor/company/other-snapshot/selection","current-actor/company/snapshot/other-selection"]){const input=fixture();input.validation.key=key;refused(input);}
 const wrongChoice=fixture();wrongChoice.choice.companyId=id(99);refused(wrongChoice);
 const wrongCompany=fixture();wrongCompany.context.company={...wrongCompany.context.company,resource_id:id(99)};refused(wrongCompany);
 for(const field of ["ledgerId","bookId","periodId"]){const input=fixture();input.choice[field]=id(99);refused(input);}
});
test("every exact pin is required and stale versions, malformed or additional references fail closed",()=>{
 for(const key of Object.keys(fixture().validation.pins)){
  const missing=fixture();delete missing.validation.pins[key];refused(missing);
  const stale=fixture();stale.validation.pins[key].version_id=id(999);refused(stale);
  const foreign=fixture();foreign.validation.pins[key].resource_id=id(999);refused(foreign);
  const malformed=fixture();malformed.validation.pins[key]=null;refused(malformed);
 }
 for(const pins of [null,[],"invalid",{...fixture().validation.pins,unexpected:{resource_id:id(1),version_id:id(101)}}])refused({...fixture(),validation:{...fixture().validation,pins}});
});
test("ambiguous resources, unresolved dependencies and unapproved or template resources are unavailable",()=>{
 for(const field of ["calendar_id","chart_id","currency_id"]){const input=fixture();input.context.ledgers[0][field]=null;refused(input);}
 const unready=fixture();unready.context.ledgers[0].ready=false;refused(unready);
 const duplicateLedger=fixture();duplicateLedger.context.ledgers.push(duplicateLedger.context.ledgers[0]);refused(duplicateLedger);
 for(const field of ["books","periods"]){const input=fixture();input.context.ledgers[0][field].push(input.context.ledgers[0][field][0]);refused(input);}
 for(const patch of [{authority_state:"REVOKED"},{evidence_class:"REFERENCE_TEMPLATE"},{object_type:"ReportedCurrency"}]){const input=fixture();Object.assign(input.context.ledgers[0].currency_id,patch);refused(input);}
});
test("pin equality cannot override a foreign company, book, calendar, chart or currency relationship",()=>{
 for(const field of ["legal_entity_id","calendar_id","chart_id","currency_id"]){const input=fixture();input.context.ledgers[0].ledger.attributes[field]=id(999);refused(input);}
 const book=fixture();book.context.ledgers[0].books[0].attributes.ledger_id=id(999);refused(book);
 const period=fixture();period.context.ledgers[0].periods[0].attributes.calendar_id=id(999);refused(period);
});
