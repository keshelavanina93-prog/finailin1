import assert from "node:assert/strict";
import test from "node:test";
import {loadTypeScript} from "./load-typescript.mjs";

const {recordedFieldChanges,changePointer}=await loadTypeScript(new URL("../app/company-change-values.ts",import.meta.url));
const id="11111111-1111-4111-8111-111111111111",version="22222222-2222-4222-8222-222222222222",next="33333333-3333-4333-8333-333333333333";
function fixture(before={},after={},fields=[...new Set([...Object.keys(before),...Object.keys(after)])].map(key=>`/attributes/${key.replaceAll("~","~0").replaceAll("/","~1")}`)){
 const resource={resource_id:id,version_id:version,content_hash:"a".repeat(64),object_type:"Contract",display_name:"Retained agreement",authority_state:"APPROVED",evidence_class:"SOURCE_BOUND",attributes:before};
 return {resource_id:id,kind:"CHANGED_VERSION",before:resource,after:{...resource,version_id:next,content_hash:"b".repeat(64),attributes:after},changed_fields:fields};
}

test("only server-declared fields appear, preserving multilingual labels and literal numeric strings",()=>{
 const input=fixture({account_code:"00012",description:"ძველი ხელშეკრულება",unlisted:12},{account_code:"00013",description:"განახლებული ხელშეკრულება",unlisted:98},["/attributes/account_code","/attributes/description"]),before=structuredClone(input);
 const rows=recordedFieldChanges(input);
 assert.equal(rows.length,2);assert.equal(rows[0].label,"account code");
 assert.deepEqual(rows[0].before,{state:"VALUE",kind:"text",text:"00012"});
 assert.equal(rows[1].after.text,"განახლებული ხელშეკრულება");
 assert.deepEqual(input,before);assert.equal(JSON.stringify(rows).includes("unlisted"),false);
});

test("absent, explicit null, empty text, false and zero stay distinct",()=>{
 const rows=recordedFieldChanges(fixture({deleted:null,empty:"",flag:false,count:0},{added:null,empty:"new",flag:true,count:1}));
 const values=Object.fromEntries(rows.map(row=>[row.label,row]));
 assert.equal(values.deleted.before.state,"NULL");assert.equal(values.deleted.after.state,"ABSENT");
 assert.equal(values.added.before.state,"ABSENT");assert.equal(values.added.after.state,"NULL");
 assert.equal(values.empty.before.text,"Empty text");assert.equal(values.empty.before.kind,"text");
 assert.equal(values.flag.before.text,"False");assert.equal(values.flag.before.kind,"boolean");
 assert.equal(values.count.before.text,"0");assert.equal(values.count.before.kind,"number");
});

test("JSON Pointer escaping reads a literal top-level key without nested traversal or prototype fallback",()=>{
 assert.deepEqual(changePointer("/attributes/a~1b~0c"),{field:"a/b~c",attribute:true});
 assert.deepEqual(changePointer("/attributes/~01"),{field:"~1",attribute:true});
 const before=JSON.parse('{"a/b~c":"before","__proto__":"retained old"}');
 const after=JSON.parse('{"a/b~c":"after","__proto__":"retained new"}');
 const rows=recordedFieldChanges(fixture(before,after));
 assert.equal(rows[0].after.text,"after");assert.equal(rows[1].before.text,"retained old");
 assert.throws(()=>recordedFieldChanges(fixture({}, {}, ["/attributes/toString"])));
 for(const pointer of ["attributes/name","/attributes/a/b","/attributes/a~2b","/content_hash","/constructor","/attributes","/attributes/name/"])
  assert.throws(()=>changePointer(pointer));
});

test("technical references and retained structures are only in Advanced values",()=>{
 const rows=recordedFieldChanges(fixture({reference:id,config:{order:1},array:["a"]},{reference:next,config:{order:2},array:["b"]}));
 assert.equal(rows[0].before.kind,"technical");assert.equal(rows[0].before.advanced,id);
 assert.equal(rows[0].before.text.includes(id),false);
 assert.equal(rows[1].before.kind,"structured");assert.deepEqual(JSON.parse(rows[1].before.advanced),{order:1});
 const metadata=fixture();metadata.before.access_entity="private_scope";metadata.after.access_entity="other_scope";metadata.changed_fields=["/access_entity"];
 assert.equal(recordedFieldChanges(metadata)[0].before.kind,"technical");
});

test("typed scalar changes never coerce strings, numbers or booleans",()=>{
 const [row]=recordedFieldChanges(fixture({value:1},{value:"1"}));
 assert.equal(row.before.kind,"number");assert.equal(row.after.kind,"text");
 const [negative]=recordedFieldChanges(fixture({value:-0},{value:0}));
 assert.equal(negative.before.text,"-0");assert.equal(negative.after.text,"0");
 const [boolean]=recordedFieldChanges(fixture({value:false},{value:0}));
 assert.equal(boolean.before.kind,"boolean");assert.equal(boolean.after.kind,"number");
});

test("unsafe parsed integers withhold values while exact numeric strings remain available",()=>{
 const [row]=recordedFieldChanges(fixture({value:Number.MAX_SAFE_INTEGER+1},{value:"9007199254740993"}));
 assert.equal(row.before.kind,"unavailable");assert.match(row.before.text,/precision unavailable/i);
 assert.equal(row.before.advanced,undefined);assert.equal(row.after.text,"9007199254740993");
 const [aliased]=recordedFieldChanges(fixture({value:Number.MAX_SAFE_INTEGER+1},{value:Number.MAX_SAFE_INTEGER+2}));
 assert.equal(aliased.before.kind,"unavailable");assert.equal(aliased.after.kind,"unavailable");
 for(const value of [NaN,Infinity,undefined])assert.throws(()=>recordedFieldChanges(fixture({value},{value:1})));
});

test("wide text and structured values have explicit bounded display without invented summaries",()=>{
 const text="ქართული ტექსტი ".repeat(2000);
 const [row]=recordedFieldChanges(fixture({value:"prior"},{value:text}));
 assert.equal(row.after.text.length,241);assert.equal(row.after.advanced.length,8192);assert.equal(row.after.limited,true);
 assert.equal(row.after.advanced,text.slice(0,8192));
 const [list]=recordedFieldChanges(fixture({value:[]},{value:Array.from({length:2000},()=>"retained")}));
 assert.equal(list.after.kind,"structured");assert.equal(list.after.limited,true);assert.equal(list.after.advanced,undefined);
 const before=Object.fromEntries(Array.from({length:30},(_,i)=>["field"+i,"a".repeat(8000)]));
 const after=Object.fromEntries(Array.from({length:30},(_,i)=>["field"+i,"b".repeat(8000)]));
 const rows=recordedFieldChanges(fixture(before,after));
 assert.ok(rows.flatMap(row=>[row.before,row.after]).reduce((total,value)=>total+(value.advanced?.length??0),0)<=128*1024);
 assert.ok(rows.some(row=>row.after.limited));
});

test("structured previews withhold nested negative zero and unsafe integers instead of normalizing",()=>{
 for(const value of [[-0],{nested:{value:-0}},[Number.MAX_SAFE_INTEGER+1]]) {
  const [row]=recordedFieldChanges(fixture({value},{value:[0]}));
  assert.equal(row.before.kind,"structured");assert.equal(row.before.advanced,undefined);
  assert.equal(row.before.limited,true);assert.match(row.before.limitation,/exact numeric representation is unavailable/i);
 }
});

test("foreign identities, reused versions, template evidence and malformed declared fields refuse",()=>{
 const valid=fixture({value:1},{value:2});
 for(const change of [
  {...valid,resource_id:next}, {...valid,kind:"ADDED_TO_CONTEXT"}, {...valid,before:null},
  {...valid,after:{...valid.after,version_id:version}},
  {...valid,after:{...valid.after,content_hash:"invalid"}},
  {...valid,after:{...valid.after,evidence_class:"REFERENCE_TEMPLATE"}},
  {...valid,after:{...valid.after,object_type:"LegalEntity"}},
  {...valid,changed_fields:["/attributes/value","/attributes/value"]},
  {...valid,changed_fields:Array.from({length:1001},(_,i)=>`/attributes/${i}`)},
  {...valid,changed_fields:["/attributes/missing"]},
 ])assert.throws(()=>recordedFieldChanges(change));
 assert.throws(()=>recordedFieldChanges(fixture({value:1},{value:1})));
 assert.deepEqual(recordedFieldChanges({...valid,changed_fields:[]}),[]);
});
