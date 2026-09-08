import type {CompanyHomeDescriptor} from "@finai/contracts";

/** Check the financial context before rendering exact-resource drill links. */
export function assertHomeFinancialContext(home:CompanyHomeDescriptor):void {
 const f=home.financial_context,company=home.company.resource_id;
 if(!f||f.authority!=="ACCOUNTING_CONTEXT_ONLY"||!Array.isArray(f.ledgers)||!Array.isArray(f.source_scopes))throw Error("Financial context is unavailable for this company snapshot.");
 const accepted=(value:{authority_state:string;evidence_class:string;object_type:string},kind:string)=>value?.authority_state==="APPROVED"&&value.evidence_class!=="REFERENCE_TEMPLATE"&&value.object_type===kind;
 for(const item of f.ledgers){
  if(!accepted(item.ledger,"Ledger")||item.ledger.attributes.legal_entity_id!==company||!Array.isArray(item.books)||!Array.isArray(item.periods))throw Error("Ledger context differs from the selected company.");
  for(const [field,node,kind] of [["calendar_id",item.calendar,"FiscalCalendar"],["chart_id",item.chart,"LocalChartOfAccounts"],["currency_id",item.currency,"Currency"]] as const)if(node&&(!accepted(node,kind)||item.ledger.attributes[field]!==node.resource_id))throw Error("Ledger dependency differs from the retained context.");
  if(item.books.some(book=>!accepted(book,"AccountingBook")||book.attributes.ledger_id!==item.ledger.resource_id)||item.periods.some(period=>!accepted(period,"FiscalPeriod")||!item.calendar||period.attributes.calendar_id!==item.calendar.resource_id))throw Error("Books or periods differ from the retained accounting context.");
  if(typeof item.context_ready!=="boolean"||item.context_ready&&(!item.calendar||!item.chart||!item.currency||!item.books.length))throw Error("Accounting readiness is unsupported by its retained dependencies.");
 }
 if(f.source_scopes.some(scope=>!accepted(scope,"SourceAccountingScope")||scope.attributes.legal_entity_id!==company))throw Error("Source boundary differs from the selected company.");
}
