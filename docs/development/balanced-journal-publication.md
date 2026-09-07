# Canonical balanced journal publication

Journal publication uses the existing canonical resource proposal and independent
review transaction. It does not create another journal identity store or a posting
shortcut. New journal changes require a complete entry and its declared line set
in one proposal. Every line has an explicit `DEBIT` or `CREDIT` side and a strictly
positive decimal string; the server requires equal totals in one canonical
currency without rounding away a difference.

The entry carries `definition: {contract: "balanced-journal/1", line_ids: [...]}`.
The manifest is bounded by the existing 100-mutation proposal limit. It declares
membership without adding a reverse dependency cycle. Existing attached editing
heads, including future-effective versions, require their exact expected versions.
Line-only changes, omitted members, reparenting and revocation are refused by this
initial contract. Entry and lines share their effective interval and accepted
source-accounting binding.

Amounts allow up to 20 integer and six fractional digits, with no floats,
exponents, non-finite values or negative signs. This is the explicit storage and
calculation bound, not an inferred currency rounding policy. Debit and credit
totals are calculated with sufficient decimal precision on the server.

Existing accounting authority checks still require reviewed source interpretation,
company, ledger, period, chart/account, currency and original source provenance.
The currently supported source contract is explicitly `SOURCE_ROW` granularity
and the existing `1c_journal` profile; trial-balance and expense summary profiles
are refused. This does not claim a universal manual or external journal adapter.
Summary balances cannot be promoted into fabricated journals. A balanced bundle
alone does not establish authentic source interpretation or financial certification.

The proposal review displays the submitted lines and retained server totals via
the existing review component. It performs no browser-side accounting sum and adds
no approval endpoint. Old proposals without a balance summary show no inferred
balance status.

Schema evolution is additive: optional `definition` and `side` fields preserve
historical schema compatibility, while new journal publication requires them in
the runtime contract. The two schema changes were independently reviewed in local
proposal `e17021ba-f45d-461a-9c93-9f494299130a`.

The current visible tenant has no accepted journal versions or retained journal
proposals. No SOCAR journal was created for this implementation. Actual journal
publication and authenticated review acceptance require a valid source-accounting
interpretation and complete transaction evidence; NIN-17 remains open.

Focused verification: 37 checks passed, with Ruff and targeted typing checks.
Native coverage reads the real bundle lookup with synthetic in-memory amounts and
proves the complete proposal path refuses a missing accepted source binding with
zero versions published for that batch. Unit fixtures cover exact small imbalance,
invalid decimal representations, currency/binding/interval differences, incomplete
membership, future editing-head CAS, reparenting and revocation. These checks do
not establish successful accepted journal publication or a live stale-approval
race. The shared validator runs again during promotion under the existing canonical
transaction lock; direct database-writer enforcement is not claimed.

The journal review component passed focused lint, TypeScript and the production
web build; web3062 and API8062 were restarted through the managed D: runtime. There is
no authenticated positive journal browser proof because no authentic eligible
journal proposal exists. The component's presence does not close NIN-25 or NIN-17.
