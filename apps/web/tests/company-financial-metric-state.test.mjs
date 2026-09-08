import assert from "node:assert/strict";
import test from "node:test";
import {readFileSync} from "node:fs";
import {loadTypeScript} from "./load-typescript.mjs";

const {assertHomeFinancialMetrics}=await loadTypeScript(new URL("../app/company-financial-metric-state.ts",import.meta.url));
const {restorationInstant}=await loadTypeScript(new URL("../app/definition-restoration-time.ts",import.meta.url));
const {assertProjection}=await loadTypeScript(new URL("../app/semantic-analysis-state.ts",import.meta.url));
const {assertProjectionTransport}=await loadTypeScript(new URL("../app/analysis-projection-identity.ts",import.meta.url));
const {homeAnalysisRowTarget}=await loadTypeScript(new URL("../app/home-analysis-row.ts",import.meta.url));
const {sourceReviewUrl,sourceReviewTarget}=await loadTypeScript(new URL("../app/source-review-route.ts",import.meta.url));
const id=n=>`${n.toString(16).padStart(8,"0")}-aaaa-4aaa-8aaa-aaaaaaaaaaaa`;
const pin=n=>({resource_id:id(n),version_id:id(n+100),content_hash:"a".repeat(64)});
const keys=["debit_movement","credit_movement","net_movement"];
const sourceTime="2025-01-31T00:00:00.123456Z",snapshot="2026-09-08T12:00:00.654321Z";
const metricValues=values=>Object.fromEntries(keys.map((key,index)=>[key,{state:"VALUE",value:values[index]}]));

// Isolated fixture: one balanced retained journal, two contributing local accounts.
// The decimal literals mirror C's supported 731.97 movement example, not a live result.
function fixture(){
 const company=pin(1),invocation=id(2),accountA=pin(10),accountB=pin(11),sourceFunction=pin(30),currency=pin(40);
 const rowKeys=["row_"+"b".repeat(64),"row_"+"c".repeat(64)];
 const fields=[{key:"account_code",kind:"identifier",role:"ATTRIBUTE"},{key:"account",kind:"reference",role:"DIMENSION"},...keys.map(key=>({key,kind:"decimal",role:"ATTRIBUTE"}))].map(field=>({...field,label:field.key,aggregation:"NONE",definition:sourceFunction,filterable:false,groupable:false,options:[]}));
 const rows=[{account:accountA,code:"7310.02.1",label:"ხარჯი · Расход · Expense",values:["731.97","0.00","731.97"]},{account:accountB,code:"3110",label:"მომწოდებელი · Поставщик · Supplier",values:["0.00","731.97","-731.97"]}].map((item,index)=>({key:rowKeys[index],label:item.label,trace:item.account,contributor_count:1,values:{account_code:{state:"VALUE",value:item.code,label:null,reference:null},account:{state:"VALUE",value:item.account.resource_id,label:item.label,reference:item.account},...Object.fromEntries(keys.map((key,i)=>[key,{state:"VALUE",value:item.values[i],label:null,reference:null}]))}}));
 const projection={descriptor:{contract:"semantic-analysis/2",row_noun:"objects",invocation_id:invocation,company,company_label:"Fixture company",function:sourceFunction,receipt_hash:"d".repeat(64),valid_at:sourceTime,known_at:sourceTime,recorded_at:sourceTime,current_use_authorized:false,business_effect_authorized:false,visual:"NONE",measure:null,filtering:"RETAINED_GROUP_SELECTION",grouping:"RETAINED_ROWS_WITHOUT_AGGREGATION",fields,coverage:[{label:"Snapshot",value:snapshot}]},descriptor_sha256:"e".repeat(64),request:{company_id:company.resource_id,invocation_id:invocation,descriptor_sha256:"e".repeat(64)},total_rows:2,rows,sections:[{label:"Accepted account movements",row_keys:rowKeys}],selection:null};
 const selection={legal_entity_id:company,ledger_id:pin(41),book_id:pin(42),period_id:pin(43),chart_id:pin(44),currency_id:currency,calendar_id:pin(45)};
 const journal={journal:pin(50),lines:[pin(51),pin(52)],dimension_policies:[pin(53)],source_coordinate:"Base!S2"};
 const nodes=[{key:"company",parent_key:null,kind:"COMPANY_MOVEMENTS",label:"Fixture company",account_code:null,subject:company,metrics:metricValues(["731.97","731.97","0.00"]),source_coordinates:["Base!S2"],journal_keys:[journal.journal.resource_id],analysis_row_key:null},...rows.map((row,index)=>({key:`account-${index}`,parent_key:"company",kind:"ACCOUNT_MOVEMENTS",label:row.label,account_code:row.values.account_code.value,subject:row.trace,metrics:metricValues(keys.map(key=>row.values[key].value)),source_coordinates:["Base!S2"],journal_keys:[journal.journal.resource_id],analysis_row_key:row.key}))];
 const result={contract:"company-financial-metrics/1",company_id:company.resource_id,invocation_id:invocation,snapshot_at:snapshot,selection,binding:pin(60),source_function:sourceFunction,source_sha256:"f".repeat(64),source_receipt_hash:"1".repeat(64),reconciliation_receipt_hash:projection.descriptor.receipt_hash,implementation_sha256:"2".repeat(64),result_sha256:"3".repeat(64),definitions:keys.map((code,index)=>({code,label:["Accepted debit movements","Accepted credit movements","Accepted net movements"][index],function_reference:"finance.accepted-journal-movements/v1",definition_authority:"CODE_DEFINED_NOT_PUBLISHED",operation:["ACCEPTED_DEBIT","ACCEPTED_CREDIT","DEBIT_MINUS_CREDIT"][index],unit:currency,unit_label:"GEL"})),nodes,journals:[journal],coverage:{state:"RECONCILED",source_rows:1,literal_source_rows:1,accepted_journals:1,unmatched_source_rows:0,excluded_source_rows:0,rejected_journals:0,missing_coordinates:[],excluded_rows:[],rejected:[],ledger_completeness:"UNESTABLISHED"},hierarchy_basis:"COMPANY_AND_EXACT_LOCAL_ACCOUNT",aggregation:"SERVER_OWNED_VALUES_DO_NOT_SUM_HIERARCHY",unavailable:["OPENING_BALANCE","CLOSING_BALANCE","FINANCIAL_STATEMENTS"],current_use_authorized:false,business_effect_authorized:false};
 const request={company_id:company.resource_id,invocation_id:invocation,snapshot_at:snapshot,expected_reconciliation_sha256:result.reconciliation_receipt_hash,expected_result_sha256:result.result_sha256};
 const reference={kind:"EXACT",invocationId:invocation,journalSnapshot:snapshot,revision:{descriptorSha256:projection.descriptor_sha256,receiptHash:projection.descriptor.receipt_hash,validAt:sourceTime,knownAt:sourceTime}};
 return {result,request,projection,reference};
}

test("valid company and two-account fixture passes independent projection and metric guards unchanged",()=>{
 const {result,request,projection}=fixture(),before=structuredClone({result,projection});
 assertProjection(projection,projection.request);assertProjectionTransport(projection,request.snapshot_at);assertHomeFinancialMetrics(result,request,projection);
 assert.deepEqual({result,projection},before);
 assert.equal(result.nodes[0].metrics.net_movement.value,"0.00");
});
for(const [name,change] of [
 ["wrong company",r=>{r.company_id=id(99);}],
 ["wrong invocation",r=>{r.invocation_id=id(99);}],
 ["different microsecond snapshot",r=>{r.snapshot_at="2026-09-08T12:00:00.654322Z";}],
 ["unaware snapshot",r=>{r.snapshot_at="2026-09-08T12:00:00";}],
 ["source Function identity",r=>{r.source_function={...r.source_function,resource_id:id(99)};}],
 ["source Function version",r=>{r.source_function={...r.source_function,version_id:id(99)};}],
 ["source Function hash",r=>{r.source_function={...r.source_function,content_hash:"9".repeat(64)};}],
 ["reconciliation receipt",r=>{r.reconciliation_receipt_hash="9".repeat(64);}],
 ["pinned result hash",r=>{r.result_sha256="9".repeat(64);}],
 ["malformed source receipt",r=>{r.source_receipt_hash="missing";}],
 ["foreign account row",r=>{r.nodes[1].subject={...r.nodes[1].subject,resource_id:id(99)};}],
 ["account row version",r=>{r.nodes[1].subject={...r.nodes[1].subject,version_id:id(99)};}],
 ["account row hash",r=>{r.nodes[1].subject={...r.nodes[1].subject,content_hash:"9".repeat(64)};}],
 ["unlisted account row",r=>{r.nodes[1].analysis_row_key="row_"+"9".repeat(64);}],
 ["mismatched account amount",r=>{r.nodes[1].metrics.debit_movement.value="731.98";}],
 ["rewritten decimal literal",r=>{r.nodes[1].metrics.debit_movement.value="731.970";}],
 ["numeric amount instead of retained decimal string",r=>{r.nodes[1].metrics.debit_movement.value=731.97;}],
 ["invented whole-ledger completeness",r=>{r.coverage.ledger_completeness="COMPLETE";}],
 ["unlinked journal",r=>{r.nodes[1].journal_keys=[id(99)];}],
 ["foreign source coordinate",r=>{r.nodes[1].source_coordinates=["Base!S99"];}],
])test(`financial guard refuses ${name}`,()=>{const {result,request,projection}=fixture();change(result);assert.throws(()=>assertHomeFinancialMetrics(result,request,projection));});

test("equivalent aware snapshot offset preserves the exact instant",()=>{const {result,request,projection}=fixture();result.snapshot_at="2026-09-08T16:00:00.654321+04:00";assertHomeFinancialMetrics(result,request,projection);});
test("unavailable company movements stay null and never become real zero",()=>{
 const {result,request,projection}=fixture();result.nodes=[result.nodes[0]];result.nodes[0].metrics=Object.fromEntries(keys.map(key=>[key,{state:"UNAVAILABLE",value:null}]));result.nodes[0].journal_keys=[];result.nodes[0].source_coordinates=[];result.journals=[];result.coverage={...result.coverage,state:"UNAVAILABLE",accepted_journals:0,unmatched_source_rows:1,missing_coordinates:["Base!S2"]};
 const emptyProjection={...projection,total_rows:0,rows:[],sections:[]};assertProjection(emptyProjection,emptyProjection.request);assertHomeFinancialMetrics(result,request,emptyProjection);
 for(const metric of [{state:"UNAVAILABLE",value:"0.00"},{state:"VALUE",value:null},{state:"VALUE",value:"0.00"}]){const changed=structuredClone(result);changed.nodes[0].metrics.net_movement=metric;assert.throws(()=>assertHomeFinancialMetrics(changed,request,emptyProjection));}
});
test("exact account drill retains journal snapshot, evidence selection and pins without copying financial values",()=>{
 const {result,request,projection,reference}=fixture();assertHomeFinancialMetrics(result,request,projection);
 const rowKey=result.nodes[1].analysis_row_key,target=homeAnalysisRowTarget(projection,reference,request.company_id,rowKey);
 assert.equal(target.view.request.selected_row,rowKey);assert.equal(target.view.request.contributor_index,0);assert.equal(target.journalSnapshot,snapshot);assert.equal(target.view.receipt_hash,result.reconciliation_receipt_hash);assert.equal(target.view.request.descriptor_sha256,projection.descriptor_sha256);assert.equal(target.view.pane,"evidence");assert.deepEqual(target.view.workspace.grid.focus,{row:rowKey,column:"account_code"});
 const url=sourceReviewUrl(target,new URL("https://fixture.invalid/"));assert.equal(sourceReviewTarget(url.pathname).invocationId,request.invocation_id);assert.equal(url.toString().includes("731.97"),false);
 assert.throws(()=>homeAnalysisRowTarget(projection,reference,id(99),rowKey));assert.throws(()=>homeAnalysisRowTarget(projection,{...reference,journalSnapshot:"2026-09-08T12:00:00.654322Z"},request.company_id,rowKey));
 projection.rows[0].contributor_count=0;assert.equal(homeAnalysisRowTarget(projection,reference,request.company_id,rowKey),null);
});
test("company selection version must equal the exact projected company version",()=>{const {result,request,projection}=fixture();result.selection.legal_entity_id={...result.selection.legal_entity_id,version_id:id(99)};assert.throws(()=>assertHomeFinancialMetrics(result,request,projection));});
test("one projected account cannot appear twice under different hierarchy keys",()=>{const {result,request,projection}=fixture();result.nodes.push({...structuredClone(result.nodes[1]),key:"duplicate-account"});assert.throws(()=>assertHomeFinancialMetrics(result,request,projection));});
test("fresh unpinned projection can drill using the exact revision learned from that response",()=>{
 const {result,request,projection,reference}=fixture();projection.request.descriptor_sha256=null;
 assertProjection(projection,projection.request);assertHomeFinancialMetrics(result,request,projection);
 const target=homeAnalysisRowTarget(projection,reference,request.company_id,result.nodes[1].analysis_row_key);
 assert.equal(target.view.request.descriptor_sha256,projection.descriptor_sha256);assert.equal(target.view.receipt_hash,projection.descriptor.receipt_hash);assert.equal(target.journalSnapshot,snapshot);
});

test("provided offline metric/projection pair passes exact guards and every account drill",{skip:!process.env.G8_FINANCIAL_METRIC_FIXTURE},()=>{
 const paired=JSON.parse(readFileSync(process.env.G8_FINANCIAL_METRIC_FIXTURE,"utf8")),result=paired.metric,projection=paired.projection;
 const request={company_id:result.company_id,invocation_id:result.invocation_id,snapshot_at:paired.snapshot_at,expected_reconciliation_sha256:result.reconciliation_receipt_hash,expected_result_sha256:result.result_sha256};
 assert.equal(restorationInstant(result.snapshot_at),restorationInstant(paired.snapshot_at));assertProjection(projection,projection.request);assertProjectionTransport(projection,request.snapshot_at);assertHomeFinancialMetrics(result,request,projection);
 const d=projection.descriptor,reference={kind:"EXACT",invocationId:result.invocation_id,journalSnapshot:result.snapshot_at,revision:{descriptorSha256:projection.descriptor_sha256,receiptHash:d.receipt_hash,validAt:d.valid_at,knownAt:d.known_at}};
 for(const account of result.nodes.filter(node=>node.kind==="ACCOUNT_MOVEMENTS")){const row=projection.rows.find(row=>row.key===account.analysis_row_key),target=homeAnalysisRowTarget(projection,reference,result.company_id,account.analysis_row_key);if(row.contributor_count===0)assert.equal(target,null);else{assert.equal(target.view.request.selected_row,account.analysis_row_key);assert.equal(target.view.receipt_hash,result.reconciliation_receipt_hash);assert.equal(target.journalSnapshot,result.snapshot_at);}}
});
