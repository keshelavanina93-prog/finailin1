import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import ts from "typescript";
const helper=readFileSync(new URL("../app/definition-restoration-time.ts",import.meta.url),"utf8");
const source=readFileSync(new URL("../app/company-operating-view.ts",import.meta.url),"utf8").replace('import {restorationInstant} from "./definition-restoration-time";',helper);
const {parseOperatingView,operatingViewPage,operatingViewSelection,matchesOperatingGroup}=await import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText).toString("base64")}`);
const id="11111111-1111-4111-8111-111111111111",other="22222222-2222-4222-8222-222222222222",at="2026-09-08T12:00:00.123456Z",expected={companyId:id,validAt:at,knownAt:at};
const view={version:2,...expected,group:{key:id,versionId:other,contentHash:"a".repeat(64),definitionPins:[]},groupUnavailable:false,search:"Product",workSearch:"Review",workFilter:"PENDING_REVIEW",page:2,workPage:1,licencePage:3,selected:{resourceId:id,versionId:other,contentHash:"a".repeat(64)}};
test("operating view restores exact company and microsecond snapshot with equivalent aware offsets",()=>{
 assert.deepEqual(parseOperatingView(JSON.stringify(view),expected),view);
 assert.deepEqual(parseOperatingView(JSON.stringify({...view,knownAt:"2026-09-08T16:00:00.123456+04:00"}),expected),view);
 for(const change of [{companyId:other},{knownAt:"2026-09-08T12:00:00.123457Z"},{validAt:"2026-09-08T12:00:00"},{knownAt:"2026-02-30T12:00:00Z"},{version:3}])assert.equal(parseOperatingView(JSON.stringify({...view,...change}),expected),null);
});
test("preferences strip payloads and bound text, pages, group and work filters",()=>{
 assert.deepEqual(parseOperatingView(JSON.stringify({...view,token:"secret",rows:[{amount:900}],descriptor:{},selected:{...view.selected,amount:900}}),expected),view);
 const parsed=parseOperatingView(JSON.stringify({...view,group:"company-registry",workFilter:"APPROVED",search:"x".repeat(300),workSearch:42,page:Infinity,workPage:-2,licencePage:900,selected:{resourceId:"bad",versionId:other}}),expected);
 assert.equal(parsed.group,null);assert.equal(parsed.groupUnavailable,true);assert.equal(parsed.workFilter,"ALL");assert.equal(parsed.search.length,200);assert.equal(parsed.workSearch,"");assert.equal(parsed.page,0);assert.equal(parsed.workPage,0);assert.equal(parsed.licencePage,499);assert.equal(parsed.selected,null);
});
test("pagination clamps to filtered or reduced current returned counts",()=>{
 assert.equal(operatingViewPage(499,11,10),1);assert.equal(operatingViewPage(3,0,10),0);assert.equal(operatingViewPage(2,25,10),2);assert.equal(operatingViewPage(-3,25,10),0);
});
test("saved selection requires exact version in the returned group and verified connection target",()=>{
 const resource={resource_id:id,version_id:other,content_hash:"a".repeat(64)},connections=[{target:resource}];
 assert.equal(operatingViewSelection(view.selected,[resource],connections),resource);
 assert.equal(operatingViewSelection(view.selected,[],connections),null);
 assert.equal(operatingViewSelection(view.selected,[resource],[]),null);
 assert.equal(operatingViewSelection({...view.selected,versionId:id},[resource],connections),null);
 assert.equal(operatingViewSelection(view.selected,[resource],[{target:{...resource,content_hash:"b".repeat(64)}}]),null);
});

test("legacy fixed names never map to an invented canonical group",()=>{
 for(const group of ["assets","products","parties","contracts","unknown"]){const migrated=parseOperatingView(JSON.stringify({...view,version:1,group}),expected);assert.equal(migrated.group,null);assert.equal(migrated.groupUnavailable,true);assert.equal(migrated.selected,null);assert.equal(migrated.search,view.search);}
});
test("saved canonical identity and hashes survive independently of labels",()=>{
 const restored=parseOperatingView(JSON.stringify(view),expected);assert.deepEqual(restored.group,view.group);
 const resource={resource_id:id,version_id:other,content_hash:"b".repeat(64)};
 assert.equal(operatingViewSelection(view.selected,[resource],[{target:resource}]),null);
});

test("group restoration rejects changed definitions and dependencies without choosing another group",()=>{
 const pin={resource_id:other,version_id:id,content_hash:"b".repeat(64)},saved={...view.group,definitionPins:[pin]};
 const group={key:id,definition:{resource_id:id,version_id:other,content_hash:"a".repeat(64)},definition_pins:[pin]};
 assert.equal(matchesOperatingGroup(saved,group),true);
 assert.equal(matchesOperatingGroup(saved,{...group,key:other}),false);
 assert.equal(matchesOperatingGroup(saved,{...group,definition:{...group.definition,version_id:id}}),false);
 assert.equal(matchesOperatingGroup(saved,{...group,definition_pins:[{...pin,content_hash:"c".repeat(64)}]}),false);
 assert.equal(matchesOperatingGroup(null,group),false);
});
