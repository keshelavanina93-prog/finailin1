# Retained derived-property execution

NIN-6 continuation, 2026-09-06. Derived-property queries previously selected the current definition and returned an unretained response. They now resolve definition versions before reading objects, evaluate those exact versions, and retain the query, original object values/version IDs, definition bodies/schema pins and per-object results in the existing immutable calculation authority.

`POST /v1/ontology/model/derived/query` accepts `definitions` and an optional complete `definition_versions` UUID map. Time-bound queries require explicit versions. Duplicate definitions or incomplete/mismatched pin maps are rejected. Latest-time callers without pins retain the versions selected at invocation. Results have contract `ontology-derived-result/1`, runtime `ontology-derived/1` and coverage `QUERY_PAGE_ONLY`; pagination is not represented as a full-set financial total.

`GET /v1/ontology/model/fact-runs/{run_id}` verifies content integrity, exact scope/current access and the availability of object, definition and schema versions. Derived calculations reuse this persistence/readback authority; they do not introduce a second result store. Missing values remain null with MISSING_INPUT. Wrong object types return NOT_APPLICABLE; schema mismatch and arithmetic failures remain UNAVAILABLE. No result becomes an approved accounting fact through calculation alone.

Object Sets exposes published derived-property selection, calculation and reopening by retained ID. The browser sends the exact selected definition version and the Object Set's fixed query time.

## Authentic local use

Published `1C original account code and name`, definition `b9fbde64-2cc8-4c4e-bf44-fe8fbb38c13a`, version `bb8c0350-6299-511e-a8b5-7f331c13d280`, through existing separate review. This reusable text property concatenates the authentic SourceAccountDefinition's account_code and source_name. It preserves original Georgian/Russian wording and leading zeros; it adds no financial classification, mandatory-dimension rule or translated accounting authority.

- Retained five-object run: `fcr_dcb62ca07231b41ef39b2e0bbb162744181e7e91c51b9d5f38325e7950845846`.
- Browser 50-object page: `fcr_98ca43c5b24e238537482c08d3cea4ee630e9bee41c5581b5720c84597d61bda` over the 406 real source-account definitions.
- Browser reopened the earlier five-object result and verified its original source label.
- Local artifacts: `.finai/artifacts/derived-account-run.json`, `derived-account-browser.json`, `derived-account-browser.png`.
- Focused regression verifies exact definition use across input reads, null missing inputs, invalid pin rejection and explicit historical pin requirements. Frontend build, TypeScript and focused lint passed.

This advances ontology-derived execution, not NIN-47 completion. General executable code/dependency authority, scheduling/workers, broader engineering authoring, generated SDKs, full workflow/compensation and regulatory calculations remain open under their existing Linear owners. The label calculation is authentic local integration evidence, not financial certification or production acceptance.
