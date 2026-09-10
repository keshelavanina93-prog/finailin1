import assert from "node:assert/strict";
import test from "node:test";
import {readFile} from "node:fs/promises";
import {loadTypeScript} from "./load-typescript.mjs";
const {companyDirectory,selectableCompanies}=await loadTypeScript(new URL("../app/company-directory.ts",import.meta.url));
const id=n=>`00000000-0000-4000-8000-${String(n).padStart(12,"0")}`;
const node=(n,evidence_class="USER_ASSERTED")=>({resource_id:id(n),version_id:id(n+100),content_hash:"a".repeat(64),display_name:`Identity ${n}`,object_type:"LegalEntity",attributes:{},authority_state:"APPROVED",evidence_class});
const empty=()=>({contract:"company-directory/1",companies:[],source_identities:[],reported_parties:[],unclassified_identities:[]});
function fixture(){return {company_directory:{...empty(),companies:[{company:node(1),basis:"EXPLICIT_COMPANY_DECLARATION",workspace_ids:[]},{company:node(2,"SOURCE_BOUND"),basis:"CONFIGURED_WORKSPACE",workspace_ids:[id(50)]}],source_identities:[node(3,"SOURCE_BOUND")],reported_parties:[node(4,"SOURCE_BOUND")],unclassified_identities:[node(5,"SOURCE_BOUND")]}};}
test("only declared and explicitly configured company entries are selectable",()=>{const input=fixture();assert.deepEqual(selectableCompanies(input).map(n=>n.resource_id),[id(1),id(2)]);assert.equal(companyDirectory(input),input.company_directory);});
test("legacy mixed directory fails closed, even with workspace and source ownership",()=>{const old={workspaces:[{company:node(1)}],source_companies:[node(2)],reported_groups:[{reporter:node(3),members:[{company:node(4)}]}]};assert.equal(companyDirectory(old),null);assert.deepEqual(selectableCompanies(old),[]);});
test("valid empty directory differs from missing or unsupported contract",()=>{assert.ok(companyDirectory({company_directory:empty()}));assert.equal(companyDirectory(null),null);assert.equal(companyDirectory({company_directory:{...empty(),contract:"company-directory/2"}}),null);});
test("names, region labels and registration codes never grant company selection",()=>{const input=fixture();input.company_directory.source_identities[0].display_name="Tbilisi";input.company_directory.source_identities[0].attributes.registration_code="123456789";input.company_directory.reported_parties[0].display_name="Operating Company Limited";input.company_directory.unclassified_identities[0].display_name="Georgia";assert.deepEqual(selectableCompanies(input).map(n=>n.resource_id),[id(1),id(2)]);input.company_directory.companies[0].company.display_name="Region-shaped name";assert.equal(selectableCompanies(input)[0].display_name,"Region-shaped name");});
for(const [label,mutate] of [
 ["unapproved declaration",d=>d.companies[0].company.authority_state="REVOKED"],
 ["template company",d=>d.companies[0].company.evidence_class="REFERENCE_TEMPLATE"],
 ["source label posing as declaration",d=>d.companies[0].company.evidence_class="SOURCE_BOUND"],
 ["unconfigured workspace",d=>d.companies[1].workspace_ids=[]],
 ["wrong resource type",d=>d.companies[0].company.object_type="Region"],
 ["unknown basis",d=>d.companies[0].basis="SOURCE_OWNERSHIP"],
 ["ambiguous selectable identity",d=>d.companies.push(d.companies[0])],
 ["invalid exact version",d=>d.companies[0].company.version_id="latest"],
 ["missing review collection",d=>delete d.reported_parties],
])test(`directory refuses ${label}`,()=>{const input=fixture();mutate(input.company_directory);assert.equal(companyDirectory(input),null);assert.deepEqual(selectableCompanies(input),[]);});
test("picker and company workspace share one classification consumer",async()=>{const [picker,workspace]=await Promise.all([readFile(new URL("../app/company-picker.tsx",import.meta.url),"utf8"),readFile(new URL("../app/company-workspace.tsx",import.meta.url),"utf8")]);for(const code of [picker,workspace]){assert.match(code,/from "\.\/company-directory"/);assert.match(code,/selectableCompanies\(index\)/);}assert.doesNotMatch(picker,/index\?\.source_companies|index\?\.reported_groups/);assert.doesNotMatch(workspace,/directoryOpen|directoryCollapsed|Switch company|Hide company navigator/);});

test("one retained identity may appear in both source and filing review roles",()=>{const input=fixture();input.company_directory.reported_parties.push(input.company_directory.source_identities[0]);assert.ok(companyDirectory(input));assert.equal(selectableCompanies(input).length,2);});
test("review identity cannot also be selectable or unclassified",()=>{const input=fixture();input.company_directory.source_identities.push(input.company_directory.companies[0].company);assert.equal(companyDirectory(input),null);const other=fixture();other.company_directory.unclassified_identities.push(other.company_directory.reported_parties[0]);assert.equal(companyDirectory(other),null);});
