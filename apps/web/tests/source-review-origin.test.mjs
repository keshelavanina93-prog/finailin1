import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import ts from "typescript";
const source=readFileSync(new URL("../app/source-review-origin.ts",import.meta.url),"utf8");
const {parseSourceReviewOrigin,sourceReviewViews}=await import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText).toString("base64")}`);
const id=n=>`${String(n).repeat(8)}-${String(n).repeat(4)}-4${String(n).repeat(3)}-8${String(n).repeat(3)}-${String(n).repeat(12)}`;
const sessionId=id(1),target={companyId:id(2),invocationId:id(3)};
const origin={version:1,sessionId,entryId:id(4),...target,view:"companies",scroll:842};
test("all real G8 entry surfaces retain exact company, source and scroll references",()=>{
 for(const view of sourceReviewViews)assert.deepEqual(parseSourceReviewOrigin({...origin,view},sessionId,target),{...origin,view});
 assert.equal(parseSourceReviewOrigin(origin,sessionId).view,"companies");
});
test("direct links, other sessions and mixed source/company entries have no return authority",()=>{
 for(const value of [undefined,null,[],{}, {...origin,sessionId:id(5)},{...origin,companyId:id(5)},{...origin,invocationId:id(5)},{...origin,entryId:""},{...origin,view:"https://example.com"},{...origin,version:2}])assert.equal(parseSourceReviewOrigin(value,sessionId,target),null);
});
test("return references bound scroll and strip arbitrary URLs, tokens and business values",()=>{
 for(const scroll of [NaN,Infinity,-1,10000001,"40"])assert.equal(parseSourceReviewOrigin({...origin,scroll},sessionId),null);
 assert.deepEqual(parseSourceReviewOrigin({...origin,url:"https://example.com",token:"secret",amount:500},sessionId,target),origin);
});
