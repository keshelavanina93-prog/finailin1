import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {createRequire} from "node:module";
import vm from "node:vm";
import test from "node:test";
import ts from "typescript";
import {loadTypeScript} from "./load-typescript.mjs";

const require=createRequire(new URL("../package.json",import.meta.url));
const {financeLinkedSelection}=await loadTypeScript(new URL("../app/finance-discovery-state.ts",import.meta.url));
const {response:catalog}=JSON.parse(await readFile(new URL("./fixtures/company-financial-results-synthetic.json",import.meta.url),"utf8"));
const companyId=catalog.company.resource_id,result=catalog.results[0];
function Worksheet(){} function Calculation(){} function Empty(){} function Badge(){}
let states=[],stateIndex=0;
const source=await readFile(new URL("../app/finance-workspace.tsx",import.meta.url),"utf8");
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
const compiledModule={exports:{}};
// Execute the actual component's render with controlled hook snapshots. Effects
// are suppressed: this regression concerns the render gate, not API simulation.
vm.runInNewContext(compiled,{exports:compiledModule.exports,module:compiledModule,require(name){
 if(name==="react")return {useState:()=>[states[stateIndex++],()=>{}],useEffect:()=>{}};
 if(name==="react/jsx-runtime")return require(name);
 if(name.endsWith(".css"))return {};
 if(name==="./semantic-analysis-workspace")return {default:Worksheet};
 if(name==="./posted-movement-report")return {default:Calculation};
 if(name==="./source-review-navigation")return {useSourceReview:()=>()=>{}};
 if(name==="./g8-ui")return {Empty,Badge};
 if(name==="./finance-discovery-state")return {};
 if(name==="./metric-observation-state")return {sameMetricPin:()=>false};
 throw Error(`Unexpected render dependency: ${name}`);
}});
function render(data,error,selection,{company=companyId,selectionError=""}={}){
 const page={revision:0};states=[page,{key:JSON.stringify([company,page]),data,error},selection,selectionError,""];stateIndex=0;
 return compiledModule.exports.default({active:true,companyId:company,token:"synthetic-test-token",initialReport:null,context:null,onClearReport(){},onContext(){},onInspect(){},onTrace(){}});
}
function nodes(value){if(Array.isArray(value))return value.flatMap(nodes);if(!value||typeof value!=="object")return [];return [value,...nodes(value.props?.children)];}
function selections(){
 const base=new URL("https://g8.example/"),initial={companyId,invocationId:result.invocation_id,scopeId:"historical",documentId:"historical"};
 const reference=new URL(base);reference.searchParams.set("finance_result",JSON.stringify({companyId,invocationId:result.invocation_id,receiptHash:result.receipt_hash}));
 const view=new URL(base);view.searchParams.set("finance_analysis_view",JSON.stringify({version:1,request:{company_id:companyId,invocation_id:result.invocation_id,descriptor_sha256:"a".repeat(64),filters:[],contributor_index:0},receipt_hash:result.receipt_hash,valid_at:result.valid_at,known_at:result.known_at}));
 return [financeLinkedSelection(reference,companyId,null),financeLinkedSelection(view,companyId,null),financeLinkedSelection(base,companyId,initial)];
}
for(const [name,data,error] of [["loading",null,""],["failed",null,"Current catalog unavailable"],["empty",{...catalog,results:[],sources:[],capabilities:[]},""]]){
 test(`actual Finance render keeps each historical entry mounted while discovery is ${name}`,()=>{
  for(const selection of selections()){
   const tree=nodes(render(data,error,selection)),worksheet=tree.find(node=>node.type===Worksheet);
   assert.ok(worksheet,"historical worksheet must not depend on discovery");
   assert.equal(worksheet.props.companyId,companyId);assert.equal(worksheet.props.invocationId,result.invocation_id);
   assert.equal(worksheet.props.expectedReceiptHash,selection.receiptHash);assert.equal(worksheet.props.owner,"finance");assert.equal(worksheet.props.active,true);
   assert.equal(tree.some(node=>node.type===Calculation),false,"no replacement calculation");
   assert.equal(tree.some(node=>node.props?.role==="alert"),Boolean(error));
   assert.equal(tree.some(node=>node.props?.role==="status"),name==="loading");
  }
 });
}
test("invalid saved selection and absent company still refuse before mounting",()=>{
 for(const options of [{selectionError:"Wrong company reference"},{company:""}])assert.equal(nodes(render(null,"",selections()[0],options)).some(node=>node.type===Worksheet),false);
});
test("an explicitly unsupported historical projection does not mount a substitute worksheet",()=>{
 const data={...catalog,results:[{...result,reopen:"FUNCTION_HISTORY"}],capabilities:[]};
 const tree=nodes(render(data,"",selections()[0]));
 assert.equal(tree.some(node=>node.type===Worksheet||node.type===Calculation),false);
});
test("without a selected historical reference loading and failure remain distinct",()=>{
 for(const error of ["","Current catalog unavailable"]){const tree=nodes(render(null,error,null));assert.equal(tree.some(node=>node.type===Worksheet),false);assert.equal(tree.some(node=>node.props?.role==="alert"),Boolean(error));assert.equal(tree.some(node=>node.props?.role==="status"),!error);}
});
