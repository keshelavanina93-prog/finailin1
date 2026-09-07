# Source-bound accounting structure setup

NIN-17 now lets a user propose the accounting structure missing from a reviewed company/source context. The API, canonical proposal store and G8 source workspace share the existing LegalEntity and LocalChartOfAccounts identities. It proposes a Ledger, AccountingBook and, when explicitly requested, FiscalCalendar, FiscalPeriod and Currency. Independent review remains the only publication path.

The user supplies codes, labels, currency and calendar choices. None are inferred from a credential scope, filename, company name or observed amount. New resources are USER_ASSERTED. A period must contain the observed source dates; that check does not establish complete period coverage. Existing resources may be reused only when their accepted versions and relationships are compatible. Scheduled, revoked, cross-company and incompatible chart/calendar inputs are refused.

The setup endpoint is `POST /v1/ontology/source-documents/{document_id}/accounting-context/setup-proposal`, with the corresponding authenticated web proxy. Both retained document and intake receipt identifiers are supported. The body contains the existing source selection and a `setup` object with a caller-generated request UUID, ledger/book names and codes, one currency reference or explicit three-letter code, one calendar selection, one period selection and a rationale. Codes and date bounds are validated before proposal creation.

The request UUID is the canonical proposal UUID. An additive `source-accounting-setup/1` request binding hashes the normalized request and exact authorization scope. A retry returns the same retained proposal and its current decision; reuse with different content is refused. This binding is absent from legacy proposal serialization, preserving existing payload hashes. No database migration or new publication authority is introduced.

Each proposed resource pins the exact accepted company, chart, source evidence and reused inputs. Promotion revalidates those pins. Source evidence establishes the context for the proposal, not the asserted currency or accounting policy. Setup itself does not publish transactions, activate a source binding, convert amounts, create journals, establish mapping completeness or certify financial statements.

The G8 form starts with explicit empty choices, preserves a draft when its disclosure is closed and reopened, freezes the exact submitted request for uncertain retries, and shows a retained receipt. Source proposals open Workflows & Actions using their canonical proposal identity, with return navigation to the originating workspace. Review displays the accounting choices before the existing independent decision action.

## Verification and remaining gates

Focused native database checks exercise strict choices, canonical creation and independent approval, replay after review, different-body refusal, exact source pins, changed/scheduled input rejection and company/chart/calendar/period separation. The positive financial structure fixture uses synthetic source parsing; it is not authentic accounting acceptance.

The integrated browser check uses the retained SGP.xls document, TDSheet, company `dc706c30-a8fb-57dc-b098-8a6bf2c2309d` and chart `53a371be-fd80-5ac8-a8ef-ef4492bbdfa6`. The actual source has no established ledger, currency or fiscal calendar. Proposal `0d5a9a34-997b-4c7f-bbd5-dff419d8cf39` is explicitly marked verification-only, with test currency XTS and structure labels requesting rejection. It must not be approved as company configuration. The live replay returned the same proposal, a changed rationale was refused, and all five proposed resources remained unpublished with the source accounting binding unchanged.

The independent reviewer rejected this verification draft in Workflows & Actions. A subsequent exact HTTP retry returned the retained REJECTED decision with review_required=false. All five planned resources remained unpublished, and the source binding remained unchanged. Return navigation preserved the selected SGP company. The production build passed after the owned standalone web process was stopped to release its Windows directory lock.

Acceptance evidence is recorded in `evidence/nin17-source-accounting-setup.json`. NIN-17, NIN-25 and release acceptance remain open. Real accounting activation still requires explicit, reviewed business configuration, mappings and source meaning; this implementation does not supply those missing facts.
