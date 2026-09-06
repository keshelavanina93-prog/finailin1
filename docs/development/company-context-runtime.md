# Canonical company context, 2026-09-06

The former flat LegalEntity directory and SOURCE_BOUND-only company eligibility
filter are replaced by an explicit CompanyWorkspace configuration over canonical
company, enterprise and domain-pack identities. This is application configuration;
it does not establish corporate ownership or consolidation membership.

Published configuration proposal: `0507670b-6ead-417f-98cd-aa9c3df56343`.
Primary entries are SOCAR Georgia Petroleum and SOCAR Georgia Gas. Existing
company IDs are reused. Source-bound company contexts such as Sakorggazi remain
separately accessible, without inventing an SGG legal ownership edge.

`GET /v1/ontology/company-context` supplies the workspace index.
Adding `company_id` resolves its canonical context. Optional `valid_at` and
`known_at` select the ontology snapshot; `ledger_id`, `book_id`, `period_id`
request an explicitly validated accounting context with exact version references.

The resolver reads an authorized, bounded snapshot under the registry shared lock.
It follows retained field dependency versions and excludes templates/revocations.
It distinguishes typed legal/operating/consolidation relationships from reported
disclosures. Ledger ownership, calendar, chart, currency, books and periods resolve
through the same pins. Incompatible or partial accounting selection is rejected.
No selected company can inherit another entity's ledger through its label.

The Companies workspace renders these relationships, accounting scopes,
dimensions, licence evidence and historical reports. Root company navigation uses
configured workspaces; related/source company navigation reuses canonical IDs.
Data's retained-source selector uses document identities returned for the selected
company. NYX's context summary uses the same resolver. Existing Maps and Regulation
continue receiving the same selected company ID. Legacy intake receipt scope stays
separate; the resolver does not mutate credentials or attribute those receipts to
a newly selected company.

## Authentic local results

- SGP: one accounting source scope and five corporate disclosure references.
- SGG: 22 corporate disclosure references and one licence notice binding; it does
  not inherit Sakorggazi procurement scope.
- Sakorggazi: one accounting scope, three analytical dimensions, one corporate
  disclosure reference and one licence notice binding.
- None of these three has a non-template accepted ledger resolving to the selected
  company version. The runtime reports missing accounting configuration.
- No effective ownership/operating/consolidation relationships were fabricated
  from the historical disclosure tables.

The authenticated browser exercised root company switching and Sakorggazi source /
dimension / licence context. Focused checks protect cross-company ledger/book
selection, stale version pins and disclosure-versus-ownership separation.

## Open completion boundary

This is executable company-context infrastructure, not full NIN-26/NIN-17 completion.
Authoritative current structural links, accepted ledgers/books and downstream
financial/reporting execution still require their specific configuration/evidence.
Domain-pack assignment records semantic configuration, not proof that every
industry capability is implemented. Historical disclosure drill does not establish
current legal ownership. A valid accounting selector does not certify source facts.
