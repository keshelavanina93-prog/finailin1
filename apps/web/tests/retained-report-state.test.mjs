import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";
import {loadTypeScript} from "./load-typescript.mjs";
const {reportSectionFromProjection,reportCompositionReferences,sameReportComposition,reportCellLabel,reportEvidenceTarget,assertReportPreview,verifyReportDownload}=await loadTypeScript(new URL("../app/retained-report-state.ts",import.meta.url));
const {projection:p}=JSON.parse(await readFile(new URL("./fixtures/retained-report-projection-synthetic.json",import.meta.url),"utf8"));
const realPreview=JSON.parse(await readFile(new URL("./fixtures/report-preview-real-synthetic.json",import.meta.url),"utf8"));
const company=p.descriptor.company.resource_id,id="11111111-1111-4111-8111-111111111111";
const section=reportSectionFromProjection(p,company,id);
const composition={company_id:company,valid_at:"2026-09-09T00:00:00Z",known_at:"2026-09-09T00:00:00Z",title:"Retained financial review",commentary:"Operator commentary",sections:[section]};
test("report composition retains exact original result pins independently of report snapshot time",()=>{
 assert.equal(section.invocation_id,p.descriptor.invocation_id);assert.equal(section.receipt_hash,p.descriptor.receipt_hash);assert.equal(section.descriptor_sha256,p.descriptor_sha256);
 const retained=reportCompositionReferences({...composition,rows:p.rows,token:"not retained",sections:[{...section,rows:p.rows}]});
 assert.equal(JSON.stringify(retained).includes("not retained"),false);assert.equal(JSON.stringify(retained).includes('"rows"'),false);
 assert.equal(retained.valid_at,composition.valid_at);assert.equal(retained.sections[0].receipt_hash,p.descriptor.receipt_hash);
 assert.deepEqual(retained.sections[0].columns,section.columns);
});
test("composition bounds and duplicate section or column identity refuse",()=>{
 for(const sections of [[],Array(9).fill(section),[section,section],[{...section,columns:[]}],[{...section,columns:["a","a"]}],[{...section,columns:Array.from({length:33},(_,i)=>String(i))}],[{...section,receipt_hash:"changed"}]])assert.throws(()=>reportCompositionReferences({...composition,sections}));
 assert.throws(()=>reportSectionFromProjection(p,id,id));
});
test("column order and canonical filter changes invalidate preview composition without changing values",()=>{
 assert.ok(sameReportComposition(composition,structuredClone(composition)));
 assert.equal(sameReportComposition(composition,{...composition,title:"Revised title"}),false);
 assert.equal(sameReportComposition(composition,{...composition,sections:[{...section,columns:[...section.columns].reverse()}]}),false);
 assert.equal(sameReportComposition(composition,{...composition,sections:[{...section,filters:[{field:section.columns[0],state:"MISSING",value:null}]}]}),false);
});
test("report evidence drills reuse exact shared revision and original row identities",()=>{
 const target=reportEvidenceTarget(p,company,p.rows[0].key);
 assert.equal(target.invocationId,p.descriptor.invocation_id);assert.equal(target.view.request.selected_row,p.rows[0].key);assert.equal(target.view.receipt_hash,p.descriptor.receipt_hash);
 assert.throws(()=>reportEvidenceTarget(p,company,"row_"+"0".repeat(64)));
 assert.throws(()=>reportEvidenceTarget(p,id,p.rows[0].key));
});
test("report display preserves missing, null, empty text, false and literal decimals",()=>{
 const field={kind:"text",role:"ATTRIBUTE"};
 for(const [value,expected] of [[{state:"MISSING",value:null,label:null},"Not recorded"],[{state:"NULL",value:null,label:null},"Recorded null"],[{state:"VALUE",value:"",label:null},"Empty text"],[{state:"VALUE",value:false,label:null},"false"],[{state:"VALUE",value:"731.9700",label:null},"731.9700"]])assert.equal(reportCellLabel(value,field),expected);
});
test("resolver-produced retained preview carries exact sections, rows and contributor ownership",()=>{
 assert.doesNotThrow(()=>reportCompositionReferences(realPreview.snapshot.composition));
 assert.doesNotThrow(()=>assertReportPreview(realPreview,realPreview.snapshot.composition));
 assert.equal(realPreview.snapshot.sections.length,1);
 assert.equal(realPreview.snapshot.sections[0].projection.rows.length,2);
 assert.equal(Object.keys(realPreview.snapshot.sections[0].contributors).length,2);
});
test("export bytes require the saved artifact, proposal identity, media type, length and digest",async()=>{
 const bytes=new TextEncoder().encode("<html>retained report</html>");
 const digest=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",bytes)),value=>value.toString(16).padStart(2,"0")).join("");
 const artifact={media_type:"text/html",filename:"retained-report.html",size_bytes:bytes.byteLength,sha256:digest};
 const reference={report_id:id,proposal_id:"22222222-2222-4222-8222-222222222222",content_hash:"b".repeat(64)};
 const headers=new Headers({"content-type":"text/html; charset=utf-8","content-length":String(bytes.byteLength),"x-content-sha256":digest,"x-report-content-hash":reference.content_hash,"x-report-proposal-id":reference.proposal_id});
 await verifyReportDownload(bytes.buffer,headers,artifact,reference);
 await assert.rejects(()=>verifyReportDownload(bytes.buffer,new Headers(headers),{...artifact,sha256:"0".repeat(64)},reference));
});
