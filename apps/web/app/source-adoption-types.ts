export type Ref={resource_id:string;version_id:string};
export type Pin=Ref&{content_hash:string};
export type SourceSnapshot={binding:Pin;scope:Pin;evidence:Pin;company:Pin;chart:Pin;period:Pin;period_starts_on:string;period_ends_on:string;observed_from:string;observed_through:string;source_sha256:string;schema_sha256:string;document_id:string;worksheet:string;source_profile:string;source_rows:number;missing_amount_count:number;missing_amount_coordinates:string[];coverage_state:"UNESTABLISHED";meaning:Record<string,Pin|string|null>};
export type FamilySelection={family_key:string;source_system:string;display_name:string;baseline_binding:Ref;rationale:string};
export type AdoptionSelection={family:Ref;predecessor_binding:Ref;successor_binding:Ref;predecessor_adoption?:Ref|null;policy:"DISJOINT_PERIOD_ADDITION"|"REPLACES_PREDECESSOR_SNAPSHOT";rationale:string};
export type Selection=FamilySelection|AdoptionSelection;
export type FamilyDefinition={version:1;selection:FamilySelection;baseline:SourceSnapshot};
export type AdoptionDefinition={version:1;selection:AdoptionSelection;family:Pin;predecessor:SourceSnapshot;successor:SourceSnapshot};
export type Prepared={resource_id:string;object_type:"SourceFamily"|"SourceSnapshotAdoption";display_name:string;attributes:{company_id:string;definition:FamilyDefinition|AdoptionDefinition};accounting_aggregation_authorized:false};
const record=(value:unknown):value is Record<string,unknown>=>!!value&&typeof value==="object"&&!Array.isArray(value);
const hash=(value:unknown)=>typeof value==="string"&&/^[a-f0-9]{64}$/.test(value);
export const sameRef=(a:Ref,b:Ref)=>a.resource_id===b.resource_id&&a.version_id===b.version_id;
export function requestKey(value:unknown):string{return JSON.stringify(value,(_,item)=>record(item)?Object.fromEntries(Object.entries(item).filter(([,v])=>v!==undefined).sort(([a],[b])=>a.localeCompare(b))):item);}
export function checkedSnapshot(value:unknown,companyId:string):SourceSnapshot {
  if(!record(value)||!["binding","scope","evidence","company","chart","period"].every(key=>record(value[key])&&typeof value[key].resource_id==="string"&&typeof value[key].version_id==="string"&&hash(value[key].content_hash))||!record(value.company)||value.company.resource_id!==companyId||!hash(value.source_sha256)||!hash(value.schema_sha256)||!["period_starts_on","period_ends_on","observed_from","observed_through"].every(key=>typeof value[key]==="string"&&/^\d{4}-\d{2}-\d{2}$/.test(value[key]))||!Number.isInteger(value.source_rows)||Number(value.source_rows)<1||!Number.isInteger(value.missing_amount_count)||Number(value.missing_amount_count)<0||Number(value.missing_amount_count)>Number(value.source_rows)||!Array.isArray(value.missing_amount_coordinates)||!value.missing_amount_coordinates.every(item=>typeof item==="string")||value.coverage_state!=="UNESTABLISHED"||!record(value.meaning)||typeof value.worksheet!=="string"||typeof value.document_id!=="string")throw Error("The server returned an incomplete source snapshot or a different company.");
  return value as SourceSnapshot;
}
export function checkedPrepared(value:unknown,selection:Selection,companyId:string):Prepared {
  if(!record(value)||value.accounting_aggregation_authorized!==false||!record(value.attributes)||value.attributes.company_id!==companyId||!record(value.attributes.definition)||value.attributes.definition.version!==1||requestKey(value.attributes.definition.selection)!==requestKey(selection))throw Error("The reviewed comparison does not match these exact selections. Inspect again.");
  const definition=value.attributes.definition;
  if("baseline_binding" in selection){if(value.object_type!=="SourceFamily"||!sameRef(checkedSnapshot(definition.baseline,companyId).binding,selection.baseline_binding))throw Error("The baseline source version changed.");}
  else if(value.object_type!=="SourceSnapshotAdoption"||!record(definition.family)||!sameRef(definition.family as Ref,selection.family)||!sameRef(checkedSnapshot(definition.predecessor,companyId).binding,selection.predecessor_binding)||!sameRef(checkedSnapshot(definition.successor,companyId).binding,selection.successor_binding))throw Error("The predecessor or candidate source version changed.");
  return value as Prepared;
}
