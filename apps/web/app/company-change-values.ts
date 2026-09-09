import type {CanonicalResource, CompanyContextChange} from "@finai/contracts";

export type RecordedChangeValue = {
  state: "ABSENT" | "NULL" | "VALUE";
  text: string;
  kind: "absence" | "null" | "text" | "number" | "boolean" | "technical" | "structured" | "unavailable";
  advanced?: string;
  limited?: boolean;
  limitation?: string;
};
export type RecordedFieldChange = {
  pointer: string;
  label: string;
  before: RecordedChangeValue;
  after: RecordedChangeValue;
};
const metadata = new Set(["display_name", "schema_version_id", "valid_from", "valid_to", "authority_state", "evidence_class", "access_entity"]);
const technicalFields = new Set(["schema_version_id", "authority_state", "evidence_class", "access_entity"]);
const reference = /^(?:[a-f0-9]{64}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}|(?:fcr|row|rgm)_[a-f0-9]{64})$/i;
const uuid = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i;
const hash = /^[a-f0-9]{64}$/;
const MAX_FIELDS = 1000, MAX_RAW = 8192;
const unavailable = () => Error("Recorded fields could not be compared exactly. Inspect the retained versions instead.");
const object = (value:unknown):value is Record<string,unknown> => value !== null && typeof value === "object" && !Array.isArray(value);

/** Only paths declared by company-changes/1 are read; attributes are not arbitrary nested paths. */
export function changePointer(pointer:string):{field:string;attribute:boolean} {
  if(typeof pointer !== "string" || pointer.length > 2048 || /~(?![01])/.test(pointer)) throw unavailable();
  const parts = pointer.split("/");
  if(parts[0] !== "") throw unavailable();
  if(parts.length === 2 && metadata.has(parts[1])) return {field:parts[1],attribute:false};
  if(parts.length !== 3 || parts[1] !== "attributes") throw unavailable();
  return {field:parts[2].replaceAll("~1", "/").replaceAll("~0", "~"),attribute:true};
}

function read(node:CanonicalResource, path:ReturnType<typeof changePointer>):{present:boolean;value:unknown} {
  const container = path.attribute ? node.attributes : node;
  if(!object(container)) throw unavailable();
  return {present:Object.hasOwn(container,path.field),value:Object.hasOwn(container,path.field)?container[path.field]:undefined};
}

/** A bounded retained JSON preview, never a transformed analytical result. */
function structured(value:unknown):{raw?:string;limited:boolean;limitation?:string} {
  const pending = [{value,depth:0}], seen = new Set<object>();
  let nodes = 0, characters = 0;
  while(pending.length) {
    const item = pending.pop()!;
    if(++nodes > 1000 || item.depth > 12 || characters > MAX_RAW) return {limited:true};
    const entry = item.value;
    if(entry === null || typeof entry === "boolean") continue;
    if(typeof entry === "string") {characters += entry.length;continue;}
    if(typeof entry === "number") {
      if(!Number.isFinite(entry)) throw unavailable();
      if(Object.is(entry,-0) || Number.isInteger(entry) && !Number.isSafeInteger(entry)) return {
        limited:true,limitation:"The exact numeric representation is unavailable in this browser preview. Inspect the retained version; no normalized value is substituted.",
      };
      continue;
    }
    if(typeof entry !== "object") throw unavailable();
    if(seen.has(entry)) throw unavailable();
    seen.add(entry);
    if(Array.isArray(entry)) {
      if(entry.length > 1000) return {limited:true};
      for(const child of entry) pending.push({value:child,depth:item.depth+1});
    } else {
      const entries = Object.entries(entry);
      if(entries.length > 1000) return {limited:true};
      for(const [key,child] of entries) {characters += key.length;pending.push({value:child,depth:item.depth+1});}
    }
  }
  const raw = JSON.stringify(value,null,2);
  return raw.length <= MAX_RAW ? {raw,limited:false} : {limited:true};
}

function display(entry:{present:boolean;value:unknown}, technical:boolean):RecordedChangeValue {
  if(!entry.present) return {state:"ABSENT",kind:"absence",text:"Not present in this returned version"};
  if(entry.value === null) return {state:"NULL",kind:"null",text:"Recorded null"};
  const value = entry.value;
  if(typeof value === "string") {
    const limited = value.length > MAX_RAW;
    const advanced = limited ? value.slice(0,MAX_RAW) : value;
    if(technical || reference.test(value)) return {state:"VALUE",kind:"technical",text:"Recorded reference or status · Advanced",advanced,limited};
    if(value.length === 0) return {state:"VALUE",kind:"text",text:"Empty text",advanced:'""'};
    return {state:"VALUE",kind:"text",text:value.length > 240 ? value.slice(0,240)+"…" : value,
      ...value.length > 240 ? {advanced,limited} : {}};
  }
  if(typeof value === "boolean") return {state:"VALUE",kind:"boolean",text:value ? "True" : "False"};
  if(typeof value === "number") {
    if(!Number.isFinite(value)) throw unavailable();
    if(Number.isInteger(value) && !Number.isSafeInteger(value)) return {state:"VALUE",kind:"unavailable",text:"Numeric precision unavailable. Inspect the retained evidence."};
    return {state:"VALUE",kind:"number",text:Object.is(value,-0)?"-0":String(value)};
  }
  if(typeof value !== "object") throw unavailable();
  const preview = structured(value);
  return {state:"VALUE",kind:"structured",text:Array.isArray(value) ? "Retained list · Advanced" : "Retained structured value · Advanced",
    advanced:preview.raw,limited:preview.limited,limitation:preview.limitation};
}

/** Compare the stated fields of these exact versions; never discover fields or calculate deltas. */
export function recordedFieldChanges(change:CompanyContextChange):RecordedFieldChange[] {
  if(!change || change.kind !== "CHANGED_VERSION" || !change.before || !change.after ||
    !uuid.test(change.resource_id) || change.before.resource_id !== change.resource_id || change.after.resource_id !== change.resource_id ||
    change.before.object_type !== change.after.object_type || change.before.version_id === change.after.version_id ||
    [change.before,change.after].some(node=>!uuid.test(node.version_id)||!hash.test(node.content_hash)||node.authority_state!=="APPROVED"||node.evidence_class==="REFERENCE_TEMPLATE") ||
    !Array.isArray(change.changed_fields) || change.changed_fields.length > MAX_FIELDS ||
    new Set(change.changed_fields).size !== change.changed_fields.length) throw unavailable();
  let rawBudget = 128 * 1024;
  const bounded = (value:RecordedChangeValue):RecordedChangeValue => {
    if(value.advanced === undefined) return value;
    if(value.advanced.length > rawBudget) return {...value,advanced:undefined,limited:true};
    rawBudget -= value.advanced.length;
    return value;
  };
  return change.changed_fields.map(pointer=>{
    const path = changePointer(pointer), before = read(change.before!,path), after = read(change.after!,path);
    if(!before.present && !after.present) throw unavailable();
    // Refuse an inconsistent declared scalar change, preserving type and absence distinctions.
    const unsafe = (value:unknown) => typeof value === "number" && Number.isInteger(value) && !Number.isSafeInteger(value);
    if(before.present === after.present && Object.is(before.value,after.value) && !unsafe(before.value)) throw unavailable();
    const label = reference.test(path.field) ? "Recorded field" : path.field.replaceAll("_"," ");
    return {pointer,label:label.length > 160 ? label.slice(0,160)+"…" : label || "Unnamed retained field",
      before:bounded(display(before,!path.attribute && technicalFields.has(path.field))),
      after:bounded(display(after,!path.attribute && technicalFields.has(path.field)))};
  });
}
