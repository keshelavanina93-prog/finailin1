import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import ts from "typescript";
const helper=readFileSync(new URL("../app/definition-restoration-time.ts",import.meta.url),"utf8");
const source=readFileSync(new URL("../app/company-operating-state.ts",import.meta.url),"utf8").replace('import {restorationInstant} from "./definition-restoration-time";',helper);
const {assertCompanyCondition,rankCompanyWork}=await import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText).toString("base64")}`);
const company={resource_id:"11111111-1111-4111-8111-111111111111",version_id:"22222222-2222-4222-8222-222222222222",content_hash:"a".repeat(64),object_type:"LegalEntity",display_name:"Test company",authority_state:"APPROVED",evidence_class:"AUTHENTIC_SOURCE"};
const asset={...company,resource_id:"33333333-3333-4333-8333-333333333333",object_type:"Facility",display_name:"Test facility"};
function connection(source=company,target=asset){const relation={...company,resource_id:"44444444-4444-4444-8444-444444444444",object_type:"LinkType"};return {source,target,relation,record:{...company,resource_id:"55555555-5555-4555-8555-555555555555",object_type:"Relationship",attributes:{source_id:source.resource_id,target_id:target.resource_id,relation_id:relation.resource_id}}};}
const at="2026-09-08T01:00:00.123456Z",expected={companyId:company.resource_id,validAt:at,knownAt:at};
const empty={state:"EMPTY",resources:[],coverage:"EXPLICIT_CONNECTED_RESOURCE_SNAPSHOT",reason:"No explicit connections returned."};
const fixture=()=>({contract:"g8-company-condition/1",company,valid_at:at,known_at:at,connection_depth:2,connections:[],assets:empty,parties:empty,contracts:empty,products:empty,licence_evidence:[],work:{state:"AVAILABLE",reason:null,observed_at:"2026-09-09T12:00:00Z",authority:"CURRENT_RETAINED_WORK",items:[],truncated:false,limit:25},unavailable:[{key:"findings",label:"Findings",reason:"No shared finding type is available."}],current_use_authorized:false,business_effect_authorized:false});
test("company operating context binds exact company, microsecond snapshot and read-only authority",()=>{
 assert.doesNotThrow(()=>assertCompanyCondition(fixture(),expected));
 assert.doesNotThrow(()=>assertCompanyCondition({...fixture(),known_at:"2026-09-08T05:00:00.123456+04:00"},expected));
 for(const change of [{company:{...company,resource_id:asset.resource_id}},{known_at:"2026-09-08T01:00:00.123457Z"},{valid_at:"2026-09-08T01:00:00"},{business_effect_authorized:true},{connection_depth:3},{company:{...company,evidence_class:"REFERENCE_TEMPLATE"}}])assert.throws(()=>assertCompanyCondition({...fixture(),...change},expected));
});
test("resource groups preserve explicit coverage and accepted exact pins",()=>{
 const group={...empty,state:"AVAILABLE",resources:[asset]};
 assert.doesNotThrow(()=>assertCompanyCondition({...fixture(),connections:[connection()],assets:group},expected));
 assert.throws(()=>assertCompanyCondition({...fixture(),assets:group},expected));
 for(const change of [{state:"EMPTY"},{coverage:"WHOLE_COMPANY_COMPLETE"},{resources:[{...asset,authority_state:"PENDING"}]},{resources:[asset,asset]},{resources:[{...asset,content_hash:"missing"}]}])assert.throws(()=>assertCompanyCondition({...fixture(),connections:[connection()],assets:{...group,...change}},expected));
});
test("current work is separate from historical resources and requires explicit company provenance",()=>{
 const work={...fixture().work,items:[{workflow_id:"reviewed-source:test",proposal_id:null,company_id:company.resource_id,title:"Review source",state:"PREPARED",created_at:"2026-09-09T11:00:00Z",reason:"Retained company source intent",basis:"EXPLICIT_INVOCATION"}],truncated:true};
 assert.doesNotThrow(()=>assertCompanyCondition({...fixture(),work},expected));
 for(const change of [{authority:"HISTORICAL_COMPANY_SNAPSHOT"},{observed_at:"2026-09-09T12:00:00"},{items:[{...work.items[0],company_id:asset.resource_id}]},{items:[{...work.items[0],basis:"INFERRED"}]},{items:[work.items[0],work.items[0]]},{limit:100}])assert.throws(()=>assertCompanyCondition({...fixture(),work:{...work,...change}},expected));
});
test("licence evidence can retain unavailable dependencies without claiming compliance",()=>{
 const binding={...asset,object_type:"LicenceNoticeBinding",attributes:{company_id:company.resource_id}};
 assert.doesNotThrow(()=>assertCompanyCondition({...fixture(),licence_evidence:[{binding,notice:null,licence:null}]},expected));
 assert.throws(()=>assertCompanyCondition({...fixture(),licence_evidence:[{binding:{...binding,attributes:{company_id:asset.resource_id}},notice:null,licence:null}]},expected));
 assert.throws(()=>assertCompanyCondition({...fixture(),licence_evidence:[{binding:{...asset,authority_state:"REJECTED"},notice:null,licence:null}]},expected));
 assert.throws(()=>assertCompanyCondition({...fixture(),unavailable:[{key:"fabricated_capability",label:"Metric",reason:"Unknown"}]},expected));
});
test("connection targets reject foreign roots, stale typed references and extra traversal",()=>{
 const unit={...asset,object_type:"BusinessUnit"},target={...company,resource_id:"66666666-6666-4666-8666-666666666666",object_type:"Contract"};
 assert.doesNotThrow(()=>assertCompanyCondition({...fixture(),connections:[connection(company,unit),connection(unit,target)]},expected));
 for(const connections of [[connection(asset,target)],[connection(company,asset),connection(asset,target)],[{...connection(),record:{...connection().record,attributes:{...connection().record.attributes,source_id:asset.resource_id}}}],[{...connection(),relation:{...connection().relation,object_type:"LegalEntity"}}]])assert.throws(()=>assertCompanyCondition({...fixture(),connections},expected));
});
test("unavailable current work does not erase valid company resources or become empty work",()=>{
 const unavailable={...fixture().work,state:"UNAVAILABLE",reason:"Work storage timed out."};
 assert.doesNotThrow(()=>assertCompanyCondition({...fixture(),work:unavailable,connections:[connection()],assets:{...empty,state:"AVAILABLE",resources:[asset]}},expected));
 assert.throws(()=>assertCompanyCondition({...fixture(),work:{...unavailable,reason:null}},expected));
});
test("returned work priority is deterministic and filtered without inventing materiality",()=>{
 const items=["PUBLISHED","REJECTED","PREPARED","PENDING_REVIEW"].map((state,index)=>({state,workflow_id:String(index),created_at:at,title:`Work ${index}`,reason:"Retained reason"}));
 assert.deepEqual(rankCompanyWork(items).map(item=>item.state),["PENDING_REVIEW","PREPARED","REJECTED","PUBLISHED"]);
 assert.equal(items[0].state,"PUBLISHED");
 assert.deepEqual(rankCompanyWork(items,"PREPARED").map(item=>item.state),["PREPARED"]);
 assert.equal(rankCompanyWork(items,"ALL","Work 3")[0].state,"PENDING_REVIEW");
});
test("Products require explicit capability and exact connected canonical Product references",()=>{
 const product={...asset,object_type:"Product"},group={...empty,state:"AVAILABLE",resources:[product]};
 assert.doesNotThrow(()=>assertCompanyCondition({...fixture(),connections:[connection(company,product)],products:group},expected));
 assert.throws(()=>assertCompanyCondition({...fixture(),products:undefined},expected),/Products contract/);
 assert.throws(()=>assertCompanyCondition({...fixture(),products:group},expected));
 for(const resource of [{...product,version_id:company.version_id.replace("2222","7777")},{...product,content_hash:"b".repeat(64)},{...product,object_type:"ProductFamily"},{...product,authority_state:"REVOKED"}])assert.throws(()=>assertCompanyCondition({...fixture(),connections:[connection(company,product)],products:{...group,resources:[resource]}},expected));
 assert.throws(()=>assertCompanyCondition({...fixture(),connections:[connection()],products:group},expected));
});
test("Products preserve company-unit scope and reject foreign or product bridges and mixed link references",()=>{
 const unit={...asset,object_type:"BusinessUnit"},product={...asset,resource_id:"66666666-6666-4666-8666-666666666666",object_type:"Product"},group={...empty,state:"AVAILABLE",resources:[product]};
 assert.doesNotThrow(()=>assertCompanyCondition({...fixture(),connections:[connection(company,unit),connection(unit,product)],products:group},expected));
 for(const bridge of [{...unit,object_type:"LegalEntity"},{...unit,object_type:"Supplier"},{...unit,object_type:"Product"}])assert.throws(()=>assertCompanyCondition({...fixture(),connections:[connection(company,bridge),connection(bridge,product)],products:group},expected));
 for(const field of ["source_id","target_id","relation_id"]){const edge=connection(company,product);edge.record.attributes[field]=unit.resource_id;assert.throws(()=>assertCompanyCondition({...fixture(),connections:[edge],products:group},expected));}
});
