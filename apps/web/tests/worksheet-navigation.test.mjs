import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import ts from "typescript";
const source=readFileSync(new URL("../app/worksheet-navigation.ts",import.meta.url),"utf8");
const {worksheetReveal,worksheetFocusScheduler}=await import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText).toString("base64")}`);
const base={left:300,top:100,width:700,height:400,stickyWidth:220,headerHeight:42,cellLeft:400,cellTop:200,cellWidth:160,cellHeight:36,pinned:false};
test("ArrowLeft reveals a cell covered by the sticky row header",()=>{assert.deepEqual(worksheetReveal(base),{left:180,top:100});});
test("additional frozen fields are included and a wide cell aligns after them",()=>{
 assert.equal(worksheetReveal({...base,stickyWidth:420,cellLeft:600}).left,180);
 assert.equal(worksheetReveal({...base,stickyWidth:420,cellLeft:1000,cellWidth:400}).left,580);
});
test("right edge and reduced canvas reveal use only the worksheet viewport",()=>{
 assert.equal(worksheetReveal({...base,cellLeft:950}).left,410);
 assert.equal(worksheetReveal({...base,width:500,cellLeft:700}).left,360);
 assert.deepEqual(worksheetReveal({...base,cellLeft:600}),{left:300,top:100});
});
test("frozen cells retain horizontal position and header-covered rows become visible",()=>{
 assert.deepEqual(worksheetReveal({...base,pinned:true,cellTop:110}),{left:300,top:68});
 assert.deepEqual(worksheetReveal({...base,pinned:true,cellTop:490}),{left:300,top:126});
});
test("no drawable area or negative initial coordinate cannot cause invalid scrolling",()=>{
 assert.deepEqual(worksheetReveal({...base,width:100,height:20}),{left:300,top:100});
 assert.deepEqual(worksheetReveal({...base,left:0,top:0,cellLeft:0,cellTop:0}),{left:0,top:0});
});
function scheduler(){let id=0;const callbacks=new Map(),canceled=[];const api=worksheetFocusScheduler(callback=>{callbacks.set(++id,callback);return id;},frame=>canceled.push(frame));return {api,callbacks,canceled};}
test("new keyboard navigation cancels the older focus target even if its frame arrives",()=>{
 const {api,callbacks,canceled}=scheduler(),calls=[];api.schedule(()=>calls.push("old"));api.schedule(()=>calls.push("new"));callbacks.get(1)();callbacks.get(2)();assert.deepEqual(calls,["new"]);assert.deepEqual(canceled,[1]);
});
test("Find, column changes or unmount cancellation prevent stale focus delivery",()=>{
 for(const event of ["Find","columns","unmount"]){const {api,callbacks,canceled}=scheduler(),calls=[];api.schedule(()=>calls.push(event));api.cancel();callbacks.get(1)();assert.deepEqual(calls,[]);assert.deepEqual(canceled,[1]);}
});
test("a completed frame is not canceled again and later navigation still works",()=>{
 const {api,callbacks,canceled}=scheduler(),calls=[];api.schedule(()=>calls.push(1));callbacks.get(1)();api.cancel();api.schedule(()=>calls.push(2));callbacks.get(2)();assert.deepEqual(calls,[1,2]);assert.deepEqual(canceled,[]);
});
