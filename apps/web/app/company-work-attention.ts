/** Display grouping only, after canonical company/work verification; never a financial ranking. */
export function partitionCompanyWork<T extends {state:"PREPARED"|"PENDING_REVIEW"|"PUBLISHED"|"REJECTED"}>(items:readonly T[]):{attention:T[];outcomes:T[]} {
 const attention:T[]=[],outcomes:T[]=[];
 for(const item of items){
  if(item.state==="PREPARED"||item.state==="PENDING_REVIEW")attention.push(item);
  else if(item.state==="PUBLISHED"||item.state==="REJECTED")outcomes.push(item);
  else throw Error("The returned work state cannot be grouped for attention.");
 }
 return {attention,outcomes};
}
