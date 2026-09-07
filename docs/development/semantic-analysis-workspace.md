# Semantic analysis over retained shared results

NIN-44/57/59 research-reconciled candidate, based on integrated commit 98011c5.
This extends the existing Function, resource-version, source-evidence and query
authorities. A descriptor is a derived response, not an authority registry or a
new report identity.

`POST /v1/ontology/analysis/project` accepts an existing invocation and canonical
company. The existing history reader verifies receipt/result hashes, ExactScope,
read capabilities and referenced-version access. The projection then checks the
original execution plan and reads exact historical definitions. It does not
require the historical Function to match today's installed execution manifest.

The posted-movement recipe preserves each original account/side/currency amount,
the reviewed accounting interpretation, contributor cells and explicit exclusions.
It performs no new accounting calculation. The grouped-observation recipe derives
fields from the exact schema and Function grouping declaration. Counts are copied
from the retained result after contributor-partition verification. A numeric
source field does not become an additive measure.

One typed descriptor supplies field identities, human labels, kinds, dimensions,
measure units, definition pins, grain, partitions, source coverage, query times,
available operations and unavailable capabilities. The revision hashes the full
unfiltered descriptor and its original rows. Subsequent filters, row arrangement
and contributor selection require this revision. Filters select retained groups;
arrangement partitions rows without calculating new group totals. Unknown fields,
arbitrary expressions, joins, company mismatches and stale revisions are refused.

Original XLS evidence is resolved from an authorized exact source hash and scope,
then read through the existing integrity-verifying document preview. No document
ID is inferred. A missing original is explicitly unavailable; canonical attributes
are not substituted for original cells. The existing XLS reader exposes stored
cell values, not formula expressions; a null formula field does not establish that
the original XLS cell had no formula.

The product consumer uses one grid, magnitude visual, evidence/trace pane and
reference-only saved preferences for different descriptors. Local preferences are
device-specific, isolated by identity fingerprint and company, and contain no
credentials or copied report values. Reopening rechecks access and the exact
descriptor/result/time references. Cross-device server view storage remains open.

## Candidate evidence and remaining gates

Root's 17 focused tests cover preservation of exact posted values and cells,
non-aggregating arrangement, legal selection, incompatible company/revision,
unsupported operations, contradictory source evidence and unpinned requests.
Targeted lint and typing pass. A native read-only compilation of the original SEG
invocation returned 59 groups with its original receipt and excluded Base!S288.

The second authentic non-posting subject is the three existing SOG CompanyDimension
headers. `scripts/prepare-semantic-metadata-analysis.py` defaults to read-only
preparation. After code freeze, `--apply` publishes the exact query/Function through
the existing separate-review path and executes or reopens one deterministic
invocation per Function version. The headers describe available source dimensions,
not transaction totals or complete source coverage.

The integrated API and production frontend are frozen at implementation commit
24fd9cc; [the manifest](evidence/nin59-integrated-manifest.json) records migration
62, actual runtime and web-input fingerprints, and preserved unrelated worktree
changes. The [HTTP proof](evidence/nin59-semantic-http.json) passed 11 requests:
both subjects use the same projection route; SEG preserves 59 original groups,
58988.95 with six contributors, Base!S2=731.97 and excluded Base!S288; metadata
preserves three original headers and literal cells TR!Y2/Z2/AA2. Anonymous,
unsupported aggregation, stale revision and foreign-company requests are refused.
No verification request recalculated or changed a retained result.

The operator metadata invocation is 39bbb1ea-cc53-55f1-b901-cc4675ecb7f2, receipt
2b6925f22ca513238fa4f87ca5547e0cf3319e0a2c2d6895cdbe204eefea9730. The first
preparation used the steward's read capabilities and correctly returned 404 to
the normal operator. The helper now executes as the existing operator and reuses
one invocation per exact Function version and actor; the earlier steward-only
receipt remains retained. No authentication grants were changed.

The local production build and targeted typing/lint pass; the two backend focused
sets passed 17 checks each, and the product state set passed three checks. API,
worker and web restarted; this checkpoint does not add a new interrupted-workflow
recovery proof. Observed projection request times were 1.906–4.429 seconds in this
small local workload; no p95 or scale claim is established.

Authenticated browser and independent held-out checks are pending at this
integration checkpoint. Full semantic evolution, reviewed correction
and later compatible-source reuse, general adaptive projection, full financial
statements, Metrics/Findings/Investigations, model reasoning and release acceptance
remain open. No new authentic later SEG snapshot has been supplied.
