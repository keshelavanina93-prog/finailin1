export type AccountPin={resource_id:string;version_id:string;content_hash?:string};
export type PostingGroup={account_code:string;account?:AccountPin;side:string;value:string;source_coordinates:string[]};
export type AccountRow={code:string;debit?:PostingGroup;credit?:PostingGroup};
/** Lay out the retained groups. Never aggregate, net, or fill absent sides with zero. */
export function pairPostingGroups(groups:PostingGroup[]):AccountRow[] {
  const rows=new Map<string,AccountRow>();
  for(const group of groups){
    if(group.side!=="debit"&&group.side!=="credit")throw Error("Unsupported posting side in the retained report.");
    const row=rows.get(group.account_code)??{code:group.account_code};
    if(row[group.side])throw Error("Multiple retained groups for this account and side cannot be combined in the worksheet.");
    row[group.side]=group;rows.set(row.code,row);
  }
  return [...rows.values()];
}
const amountFormat=new Intl.NumberFormat("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});
/** ECMA-402 accepts decimal strings without Number coercion; TypeScript's older lib omits that overload. */
export function displayPostedAmount(exact:string):string {
  if(!/^-?\d+(?:\.\d+)?$/.test(exact))return exact;
  return (amountFormat.format as unknown as (value:string)=>string)(exact);
}
