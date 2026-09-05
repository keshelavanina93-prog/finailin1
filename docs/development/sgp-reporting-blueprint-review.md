# SGP reporting blueprint — source reconciliation and required corrections

Status: user-specified SGP presentation, not an activated accounting policy.
Reviewed 2026-09-06 against the four newly supplied ontology/operations notes,
the retained January report and the retained 1C account configuration.
SGP means SOCAR Georgia Petroleum. Gas-utility rules belong to a separate
company/domain configuration and must not inherit SGP account routing.

## Verified source structure and blocking company discrepancy

The retained `Report- January 2025.xlsx` has SHA-256
`d7c7e67c093b40b6f9209b301ca8fab7e4febc85c27d735babb95fa2028a8f0a`.
Its sheets and headers match the requested extraction:

| Sheet | Keys / amounts | Source control |
| --- | --- | --- |
| Revenue Breakdown | A: Product; D: Net Revenue | A36: Итог |
| COGS Breakdown | A: Субконто; K: 6; L: 7310; O: 8230 | A27: Итого |
| Base | D: Организация; E: Account Dr; L: Account Cr; S: Сумма | Entity and journal-line scope required |

Every one of the 596 nonblank organization values inspected in Base says
`სოკარ ენერჯი ჯორჯია // Сокар Энерджи Джорджия` (SOCAR Energy Georgia).
This is not evidence of an SGP ledger. The user has specified the target report
as SGP, but that does not rewrite this source entity. An explicit source correction,
SGP source, or evidenced allocation/intercompany contract is required before
using these Base amounts in an SGP result. The summarized revenue/COGS sheets
also need entity/period and source-population reconciliation; product labels
containing SGP do not establish ownership of every row.

Detailed observed headers, labels, organization counts and receipt identity are
retained privately in `.finai/artifacts/sgp-blueprint-source-audit.json`.
No financial totals were certified by this review.

## Preserve the requested English presentation

Use canonical product identities and separate, source-specific aliases. Original
Georgian/Russian text remains available. Display translations are not identity
proof. Keep quantity units separate from product identity; a sale's channel is a
transaction/reporting dimension, not an immutable property of its product.

| Reporting category | Revenue aliases supplied by user | COGS aliases supplied by user |
| --- | --- | --- |
| Wholesale Petrol | Euro Regular (Import), kg; Premium (Re-export), kg; Super (Re-export), kg | Euro Regular (Import); Premium (Re-export); Super (Re-export); Euro Regular (Wholesale) |
| Wholesale Diesel | Diesel (Wholesale), L; Eurodiesel (Export), kg | Diesel (Wholesale); Eurodiesel (Export) |
| Wholesale Bitumen | Bitumen (Wholesale), kg | Bitumen (Wholesale) |
| Retail Petrol | Euro Regular, L; Premium, L; Super, L | Euro Regular; Premium; Super |
| Retail Diesel | Diesel, L; Euro Diesel, L | Diesel; Euro Diesel |
| Retail CNG | Natural Gas, m3; Natural Gas (Wholesale), m3 | Natural Gas; Natural Gas (Wholesale) |
| Retail LPG | Liquid Gas (Only SGP), L | Liquid Gas (Only SGP) |

The Natural Gas (Wholesale) → Retail CNG assignment is the user's explicit
management-report choice, not a deduction from its name. Retain the original
channel descriptor and make the reporting reclassification visible.

Other revenue and cost use the union of unmatched economic items, not only the
items with revenue. Missing costs/revenue remain unknown; absence is not zero.
Exclude source total rows before mapping. New products become unmapped findings
first; product names alone cannot establish wholesale channel. A verified new
wholesale product can be given a dynamic named subline under Wholesale.

Some COGS aliases have no explicitly matching revenue alias (for example Euro
Regular (Wholesale)); the source also contains additional import/export/wholesale
products. Record asymmetry rather than dropping costs or silently cross-matching.

## Correct totals and expense semantics

```text
Total revenue = Wholesale revenue + Retail revenue + Other revenue
Total cost of sales = Wholesale cost of sales + Retail cost of sales + Other cost
Gross profit = Total revenue - Total cost of sales
Gross margin % = Gross profit / Total revenue × 100  [undefined when revenue = 0]
```

If the user's subtotal excluding Other is retained, label it Wholesale and Retail
Revenue (and the corresponding cost subtotal), rather than Total Revenue.
The requested gross-profit reconciliation is arithmetically correct when these
subtotals are defined explicitly and categories are exhaustive and disjoint.

`K + L + O` is a proposed SGP management cost-of-sales convention tied to this
source layout, not a universal ledger or IFRS COGS rule. In the account workbook:

| Account | Observed designation | Implication |
| --- | --- | --- |
| 7310.02.1 | Commercial expenses in manufacturing organizations | Separate selling costs from administration; check allocation already included in COGS L |
| 7410 / 7410.01 | General administrative expenses; 7410.01 has a source-specific qualification | Preserve hierarchy and exact posting-account matching; do not add parent control totals to children |
| 8220.01.1 | Other non-operating expenses | Cannot blanket-classify as G&A or automatically deduct in operating EBITDA |
| 9210 | Other profit-and-loss account | Review underlying transactions, including clearing/closing entries |
| 8230 | Shortages and losses from damage to valuables | Explicit loss classification, allocation and valuation required |
| 2230 | Accumulated depreciation designation for fixed assets | Inspect full debit/credit posting; this is not proof of a daily depreciation expense event |

Do not count an expense in both product COGS and Base overhead. Reconcile the
breakdown to the same underlying journal population using stable journal-line
identities and allocation versions. Net reversals and corrections appropriately;
identify closing transfers rather than blindly summing all debit or credit rows.

EBITDA is not cash generated. A standard reconciliation starts with net income,
adds interest expense, income-tax expense, depreciation and amortization, with
the precise policy disclosed. An operating-profit bridge needs explicit treatment
of other income/expense and financing classifications. For an SGP management
bridge, remove D&A wherever already included (COGS or overhead), exactly once.
`Gross profit - selected debit accounts` is not sufficient evidence of EBITDA.
Additional exclusions require a separately defined adjusted measure. Depreciation
is systematic allocation of depreciable amount over useful life, not necessarily
straight-line, daily, or a measure of physical wear. It may initially enter
inventory costs before recognition as expense.

## Corrections to the operational and gas attachments

| Proposed rule | Required implementation boundary |
| --- | --- |
| Ambient volume minus volume at 15 C is evaporation | This is a temperature-normalization difference, not evidence of lost mass. Retain original and standardized measurements, density, reference conditions and correction method; estimate actual evaporation separately. |
| Dispatch minus receipt always equals loss | Compare compatible custody boundaries, times, mass/standard volume, transfers and uncertainty. A residual is a variance to investigate, not automatically theft, leakage or financial expense. |
| Tank drop minus POS volume proves calibration drift | Receipts, internal withdrawals, temperature, timing, tank calibration and other losses also affect the balance. Meter calibration requires independent evidence. |
| Default 0.5% tolerance creates a receivable | No source establishes this threshold. Use an effective contract/product/site tolerance with units and denominator. A claim investigation is not a recognized receivable merely because a threshold is exceeded. |
| Product downgrading mutates the product and posts market-price difference | Preserve the original lot, quality event and reclassification history. Inventory write-down considers carrying cost versus net realizable value, not just two selling prices. |
| FX rate update automatically posts and all FX bypasses EBITDA | Keep analytics distinct from settlement/cutoff revaluation. Preserve rate direction, currency, asset/liability sign and last carrying amount; do not use absolute differences. Financial presentation follows the disclosed policy, not a universal 8220 route. |
| Internal fuel always debits 7310 and forces margin to zero | Same-entity internal consumption is not external revenue. Route its cost by evidenced use; intercompany supply, tax and eliminations are separate. Missing margin is not a fabricated zero-margin sale. |
| SGP and Liquid Gas are the same product | SGP is a company; LPG is a product. Keep separate identity types and links. |
| Gas inflow minus billing is technical loss | Align measurement periods and reference conditions; include opening/closing linepack, operational use, exports/transfers and estimated unbilled delivery. Billing lag is not physical loss. |
| Gas entering the network creates unbilled revenue | Recognize revenue based on supported delivery/performance, not merely network entry. Separate measured delivery, billing and accrual estimates. |
| All standard gas volume uses 20 C and 1 atm | Reference temperature, absolute pressure, compressibility and energy basis come from the applicable contract/metrology rules. Do not hard-code these as universal. |
| Rising pressure creates inventory and a balancing gain | Linepack is part of the reconciled mass balance; identify ownership and actual inflow/outflow first. Pressure changes alone do not establish newly acquired inventory or income. |
| Telemetry can immediately mutate financial truth | Retain an observation, assess/reconcile, produce a version-bound proposal, then use the existing authorized action/review/effect lifecycle. No direct posting from these notes. |
| Float for money and settlement arithmetic | Use explicit decimal precision and rounding; retain measurement precision/uncertainty separately. |

Gas network operators may use storage and other assets as well as linepack; the
attachment's statement that a gas utility has no warehouse is not universal.
Customer segments and tariff rates must come from actual contracts/regulatory
evidence, not the illustrative high/medium/low margin labels in the notes.

## Primary references used in this review

- [SEC financial reporting manual, non-GAAP measures](https://www.sec.gov/about/divisions-offices/division-corporation-finance/financial-reporting-manual/frm-topic-8)
- [IAS 2 Inventories](https://www.ifrs.org/issued-standards/list-of-standards/ias-2-inventories/)
- [IFRS interpretations: FX settlement and period-end differences](https://media.ifrs.org/2015/IFRIC/May/IFRIC%20Update%20May%202015.html)
- [IAS 37, contingent asset recognition](https://www.ifrs.org/content/dam/ifrs/publications/pdf-standards/english/2022/issued/part-a/ias-37-provisions-contingent-liabilities-and-contingent-assets.pdf)
- [NIST, thermal expansion and temperature-compensated petroleum volumes](https://www.nist.gov/speech-testimony/hot-fuels-impact-commercial-transactions-thermal-expansion-gasoline)
- [EPA, storage-tank evaporation estimation](https://www.epa.gov/air-emissions-factors-and-quantification/ap-42-chapter-7-tanks-software-frequent-questions)
- [National Gas, UAG reconciliation](https://www.nationalgas.com/our-businesses/system-operation/unaccounted-gas-uag)

These references inform the conceptual corrections; they do not establish SGP's
actual account policy, Georgian regulatory tolerances, gas standard conditions or
the source workbook's company binding.
