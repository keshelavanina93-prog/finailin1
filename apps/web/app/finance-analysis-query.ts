import type {ObjectSetQuery, SchemaField} from "@finai/contracts";

export type AnalysisSelection = {account: string; side: "either" | "debit" | "credit"; from: string; to: string; minimum: string; maximum: string};
export const emptySelection: AnalysisSelection = {account:"",side:"either",from:"",to:"",minimum:"",maximum:""};

/** A presentation adapter only: all matching, arithmetic and provenance remain server-owned. */
export function compileAnalysis(companyId:string, selection:AnalysisSelection, fields:Record<string,SchemaField>):ObjectSetQuery {
  const filters:ObjectSetQuery["filters"]=[];
  function add(field:string,value:string,operator:"eq"|"gte"|"lte"="eq",kind?:string,target?:string){
    const schema=fields[field];
    if(!schema||schema.deprecated||kind&&schema.kind!==kind||target&&schema.target_type!==target)throw Error("This analysis dimension is unavailable in the current source contract. Refresh the workspace.");
    filters.push({field,operator,value});
  }
  if(!companyId)throw Error("Select a company before analysing contributors.");
  add("legal_entity_id",companyId,"eq","reference","LegalEntity");
  if(selection.from&&selection.to&&selection.from>selection.to)throw Error("The end date must be on or after the start date.");
  if(selection.from)add("posting_date",selection.from,"gte","date");
  if(selection.to)add("posting_date",selection.to,"lte","date");
  for(const [value,operator] of [[selection.minimum,"gte"],[selection.maximum,"lte"]] as const){
    if(!value)continue;
    if(!/^-?\d+(?:\.\d+)?$/.test(value))throw Error("Enter an exact decimal amount, without grouping separators.");
    add("amount",value,operator,"decimal");
  }
  const query:ObjectSetQuery={object_type:"SourceJournalMovement",search:"",filters,traversal:[],offset:0,limit:50};
  if(selection.account){
    const accountFields=selection.side==="either"?["debit_account_id","credit_account_id"]:[`${selection.side}_account_id`];
    const conditions=accountFields.map(field=>{
      if(fields[field]?.kind!=="reference"||fields[field]?.target_type!=="LocalAccount"||fields[field]?.deprecated)throw Error("Account-side analysis is unavailable in this source contract.");
      return {field,operator:"eq" as const,value:selection.account};
    });
    if(conditions.length===2)query.filter_expression={op:"any",conditions};else filters.push(...conditions);
  }
  return query;
}
