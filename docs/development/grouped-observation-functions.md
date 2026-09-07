# Grouped observation Functions — NIN-47

A reviewed ontology Function can now declare `group_count: {schema_id, fields}`. It uses the same Object Set, invocation identity, retained-input contract and Transformation executor as other ontology analyses. Its output counts canonical source observations by exact stored scalar values; it does not count economic transactions or sum financial amounts.

The grouping schema is an exact canonical dependency (`FUNCTION_GROUP_SCHEMA`). Each contributing object's schema version must match it. Keys distinguish missing, null and present values. Every group retains its contributing resource/version/content-hash references, and the original source objects remain available for inspection. One to four scalar fields are supported; structured amounts, quantities and geometry are not scalar grouping fields.

Grouping requires the complete selected set within the existing 200-object execution bound: offset zero, no next page, and total equal to the number of retained objects. Incomplete pages fail rather than yielding apparently complete group counts. The same rule applies when a Transformation passes an earlier Function's retained result. Equality of decimal representations or timezone-normalized instants is not inferred: grouping uses exact typed stored values.

Migration 050 binds the declared grouping and exact schema to the invocation. Before accepting a successful result, it checks every source object against its canonical version, recomputes the group keys and counts, and requires the groups to partition those exact contributors. No module-local identities, financial authorization or new storage authority are introduced.

The existing G8 Saved Analyses inspector renders grouped source-observation counts ahead of the source rows, with grouping-schema provenance and contributor inspection. Other Function outputs retain their existing rendering.

## Verification

Focused native checks passed for complete grouped results, incomplete-set refusal, immutable replay and SQL rejection of forged counts. Missing/null/value grouping was checked directly. The existing retained-input regression passed against the final frozen package after an earlier concurrent metadata update correctly triggered the runtime's package-change guard. Ruff, targeted mypy, frontend lint/TypeScript and the production build passed.

Actual Transformation `682fca79-0950-5505-948b-385fabff06c1` / version `c01faa87-4753-5307-b34a-ac227e6fa9df`, request `bf61ac13-efdf-45d4-902c-4a126aa30245`, completed source-query → retained-input grouped-count execution. Upstream invocation `7de4e519-e352-53d0-93b7-42f6ef279893` supplied the exact two November 3 SOG procurement observations. Downstream invocation `ecef46c3-a4ac-545a-aed6-4eea96565672` retained receipt `3a3584d8b92c19f8cc59067115f654f05b573ed50d6f37352ccba37a41ed686c` and run `fcr_e17ccdc6ee368e0a5894fc433e944dfaaade7066008720f4609c9c6543d46721`.

The group count is 2 for posting date `2025-11-03` and unit status `UNESTABLISHED`. Contributor identity/version/hash references exactly partition the source rows; exact SourceEvidence dependencies retain workbook SHA-256 `45011b3a149ecfd09a21c7d90c6119830fac1f04352a089c5c5fbe28e3691e1d`. Same-request build replay returned identical outputs and receipts. Evidence: `evidence/nin6-grouped-observations-runtime.json`; helper: `scripts/verify-grouped-observations-runtime.py`.

Authenticated browser verification followed Workflows & Actions → retained build in Data → downstream analysis → grouped contributors → exact `TR!row:5` context in the persistent NYX rail. Visually inspected screenshots: `.finai/browser-verification/screenshots/g8-grouped-observations.png` and `g8-grouped-observation-contributor.png`.

This capability does not establish financial aggregation, complete NIN-47 or NIN-25 acceptance.
