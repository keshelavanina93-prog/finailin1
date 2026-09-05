# G8 shared account binding and temporal identity

NIN-26 intake now pins each exact source account code to an accepted LocalAccount version in the context ledger's pinned chart. Company, period, currency and chart relationships are validated by the shared registry under its tenant lock. No canonical account is manufactured from a source row. Source-only intake remains explicitly labeled.

The request hash includes the account version selections. Candidates, approved object observations and JSON evidence bundles retain the same canonical references. Approval revalidates dependencies in its transaction, preventing an intervening revocation or version change from being promoted. Earlier approved evidence remains unchanged. Receipt-local object IDs locate observations; they are not new canonical account identities.

The intake preparation surface reads source codes through the server parser, presents accepted exact-code choices and submits immutable version selections. Missing accounts require governed master-data review. Alias-based source-code transformation remains a separate semantic mapping capability.

NIN-27 identity resolution accepts independent `valid_at` and `known_at` timestamps. It reconstructs corrections and reviewed merge/split relationships from retained versions under RLS. The in-context history inspector exposes both dates and the resulting canonical/version IDs. This does not complete universal authority transitions, derived sensitivity policy, streaming time or retention enforcement.

## Verification

- 33 focused binding/compiler tests passed, including a native PostgreSQL proposal, independent review, retained ingestion, idempotent replay, approval, object/export preservation, cross-entity denial and revocation preventing subsequent approval.
- Two native PostgreSQL temporal tests passed for backdated correction and merge/split history using independent knowledge and business timestamps.
- Backend mypy and affected Ruff checks passed. Frontend production build and ESLint passed.
- Mounted runtime exposes source preparation/account choices and both temporal query parameters. G8 login was inspected in the browser; authenticated browser acceptance remains open.
- Synthetic fixtures prove local behavior only. NIN-26/NIN-27 and full-system acceptance remain open.

Run persistent checks with the existing D-only environment loaded and `G8_BINDING_DB_TEST=1`; use `test_ingest_binding_persistence.py` and `test_identity_history.py`. These create isolated synthetic resources and entity scopes in the local PostgreSQL store.
