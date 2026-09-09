import type {CanonicalResource} from "@finai/contracts";
import type {Context} from "./company-workspace";
import {companyCutoffs} from "./company-360-descriptor";

export type AccountingPins=Record<string,{resource_id:string;version_id:string}>;
export type AccountingChoice={companyId:string;ledgerId:string;bookId:string;periodId:string};
export type SelectedAccountingContext=
 | {state:"UNSELECTED"|"UNAVAILABLE";reason:string}
 | {state:"VALIDATED";company:CanonicalResource;ledger:CanonicalResource;book:CanonicalResource;
    period:CanonicalResource;currency:CanonicalResource;pins:AccountingPins;validAt:string;knownAt:string};

/** Presentation guard only; an exact server selection is required before exposing drill links. */
export function selectedAccountingContext(input:{
 companyId:string;choice:AccountingChoice;context:Context|null;validAt:string;knownAt:string;
 selectionKey:string;validation:{key:string;pins:unknown;error:string}|null;
}):SelectedAccountingContext {
 const {companyId,choice,context,validAt,knownAt,selectionKey,validation}=input;
 const unavailable=(reason:string):SelectedAccountingContext=>({state:"UNAVAILABLE",reason});
 if(choice.companyId!==companyId)return unavailable("The accounting choice belongs to another company. Select it again.");
 if(!choice.ledgerId&&!choice.bookId&&!choice.periodId)return {state:"UNSELECTED",reason:"Choose a ledger, book and fiscal period in Finance & accounting."};
 if(!choice.ledgerId||!choice.bookId||!choice.periodId)return unavailable("Complete the ledger, book and fiscal period selection.");
 if(!context||context.company?.resource_id!==companyId||!companyCutoffs({validAt,knownAt}))return unavailable("The company snapshot is unavailable. The accounting selection needs validation.");
 if(!validation||validation.key!==selectionKey)return unavailable("Awaiting validation for this company snapshot and accounting choice.");
 if(validation.error)return unavailable("The server could not validate this selection. Review Finance & accounting.");
 const matches=context.ledgers.filter(row=>row.ledger.resource_id===choice.ledgerId);
 const row=matches.length===1?matches[0]:null;
 if(!row||!row.ready||!row.calendar_id||!row.chart_id||!row.currency_id)return unavailable("The selected ledger or its dependencies are unavailable in this snapshot.");
 const books=row.books.filter(node=>node.resource_id===choice.bookId),periods=row.periods.filter(node=>node.resource_id===choice.periodId);
 if(books.length!==1||periods.length!==1)return unavailable("The selected book or fiscal period is unavailable in this ledger snapshot.");
 const book=books[0],period=periods[0];
 const nodes={legal_entity_id:context.company,ledger_id:row.ledger,book_id:book,period_id:period,
  chart_id:row.chart_id,currency_id:row.currency_id,calendar_id:row.calendar_id};
 const types={legal_entity_id:"LegalEntity",ledger_id:"Ledger",book_id:"AccountingBook",period_id:"FiscalPeriod",
  chart_id:"LocalChartOfAccounts",currency_id:"Currency",calendar_id:"FiscalCalendar"};
 const pins=validation.pins;
 if(!pins||typeof pins!=="object"||Array.isArray(pins)||Object.keys(pins).length!==Object.keys(nodes).length)return unavailable("The server's exact accounting references are incomplete.");
 const exactPins:AccountingPins={};
 for(const key of Object.keys(nodes) as (keyof typeof nodes)[]){
  const node=nodes[key],pin=(pins as Record<string,unknown>)[key];
  if(node.object_type!==types[key]||node.authority_state!=="APPROVED"||node.evidence_class==="REFERENCE_TEMPLATE"||
   !pin||typeof pin!=="object"||Array.isArray(pin))return unavailable("The selected accounting references do not match accepted resources.");
  const ref=pin as Record<string,unknown>;
  if(Object.keys(ref).length!==2||typeof ref.resource_id!=="string"||!ref.resource_id||typeof ref.version_id!=="string"||!ref.version_id||
   ref.resource_id!==node.resource_id||ref.version_id!==node.version_id)return unavailable("The accounting selection differs from the exact company snapshot. Select it again.");
  exactPins[key]={resource_id:ref.resource_id,version_id:ref.version_id};
 }
 if(row.ledger.attributes.legal_entity_id!==companyId||book.attributes.ledger_id!==row.ledger.resource_id||
  period.attributes.calendar_id!==row.calendar_id.resource_id||row.ledger.attributes.calendar_id!==row.calendar_id.resource_id||
  row.ledger.attributes.chart_id!==row.chart_id.resource_id||row.ledger.attributes.currency_id!==row.currency_id.resource_id)
  return unavailable("The selected accounting resources do not share the company's ledger context.");
 return {state:"VALIDATED",company:context.company,ledger:row.ledger,book,period,currency:row.currency_id,
  pins:exactPins,validAt,knownAt};
}
