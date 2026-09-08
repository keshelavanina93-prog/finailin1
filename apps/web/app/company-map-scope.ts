/** Directory failure must never turn an explicit company into a workspace query. */
export function companyMapScope(companyId:string, admittedCompanyId:string|undefined, directoryReady:boolean, workspaceRequested:boolean):"company"|"workspace"|"unresolved"|"choose" {
  if(companyId)return directoryReady&&admittedCompanyId===companyId?"company":"unresolved";
  return workspaceRequested?"workspace":"choose";
}
