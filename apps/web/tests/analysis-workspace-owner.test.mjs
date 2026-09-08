import assert from "node:assert/strict";
import test from "node:test";
import {loadTypeScript} from "./load-typescript.mjs";
const {analysisViewParameter,ownsAnalysisHistory}=await loadTypeScript(new URL("../app/analysis-workspace-owner.ts",import.meta.url));
const scope={companyId:"11111111-1111-4111-8111-111111111111",invocationId:"22222222-2222-4222-8222-222222222222"};
const home=new URL("https://g8.example/");
const review=new URL(`/source-review/${scope.companyId}/${scope.invocationId}`,home);
test("Finance and source review store separate reference-only view parameters",()=>{
 assert.equal(analysisViewParameter("finance"),"finance_analysis_view");
 assert.equal(analysisViewParameter("source-review"),"analysis_view");
});
test("inactive Finance cannot capture root, review, or another route",()=>{
 for(const url of [home,review,new URL("/other",home)])assert.equal(ownsAnalysisHistory(url,scope,"finance",false),false);
 assert.equal(ownsAnalysisHistory(home,scope,"finance",true),true);
 assert.equal(ownsAnalysisHistory(review,scope,"finance",true),false);
});
test("source review ownership retains exact company, invocation and snapshot checks",()=>{
 assert.equal(ownsAnalysisHistory(review,scope,"source-review",true),true);
 assert.equal(ownsAnalysisHistory(review,scope,"source-review",false),false);
 for(const changed of [{...scope,companyId:scope.invocationId},{...scope,invocationId:scope.companyId},{...scope,journalSnapshot:"2026-09-08T00:00:00Z"}])assert.equal(ownsAnalysisHistory(review,changed,"source-review",true),false);
 assert.equal(ownsAnalysisHistory(home,scope,"source-review",true),false);
});
