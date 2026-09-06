# Procurement analytical bindings

The retained Sakorggazi November TR source now binds all 246 accepted movements to
three explicit source classifications: Region, Budget Article New and Department.
The canonical inventory contains three CompanyDimension contexts, three shared
DimensionDefinition resources, 13 DimensionMembers and 738 SourceDimensionAssignments.
There are four region members, seven budget-article members and two department members.

CompanyDimension connects a legal entity, dimension definition and original header
cell. Each assignment connects an accepted movement, company dimension, member and
original value cell. All use shared canonical resource/version identities and the
existing proposal/review/promotion path. Assignment publication pins the exact input
movement version. Source observations and monetary amounts are not rewritten.

Canonical proposal validation rejects mismatched companies, dimensions, member codes,
source coordinates and evidence identities. Member code must equal the retained text
cell; missing cells remain unassigned. These are source classifications, not inferred
account-side subconto, mandatory account rules, geographic ownership or legal entities.
Company-scoped identity construction keeps coincident labels in other companies separate.

The source profile validates the explicit Y/Z/AA headers in TR. This profile does not
guess positional analytical meanings in SGP trial balances or other 1C layouts.
Cross-document company resolution and conformed budget/actual classifications require
their own reviewed bindings; there is no label-only merge across companies or sources.

Data → source/account inspection → Procurement analytical bindings supports inspection,
paged proposals, accepted-member visibility and member-to-movement drill-through.
The drill uses the shared Object Set engine and immutable reference dependencies. It
returns distinct SourceJournalMovement objects, not copies of an amount per dimension.
The original source currency and ledger remain unestablished, so this is not a financial
actual-vs-budget report or a journal-posting authority.

API: POST /v1/ontology/source-documents/{id}/dimensions/{inspect|proposal|query}.
The query accepts member_id, company_id, source document/sheet and offset. Definition
installation was reviewed in proposal 77278f5a-d0ca-4ec9-9b8a-ef2790f60fa5; first real
assignment publication was 3ac27c15-b40f-454b-8ede-4d77d7d17ca3. Each published page was
reopened and matched against canonical heads. Runtime evidence is retained in
.finai/artifacts/sog-analytical-publication.json.

The mounted browser displayed 30 accepted assignments on its first page and drilled
the selected region to 124 distinct source movements without page errors. An incompatible
member was rejected by actual canonical proposal validation before persistence.
Focused invariant checks, lint and the production web build passed. NIN-26/6/17 and
the SGG financial/regulatory product remain open beyond this implemented capability.
