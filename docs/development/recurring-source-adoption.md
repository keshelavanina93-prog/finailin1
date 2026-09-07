# Reviewed recurring source adoption

NIN-56 adds SourceFamily and SourceSnapshotAdoption to the shared canonical graph.
Family identity uses the existing company, explicit source-system code and stable
family key. Each adoption links exact family, predecessor and successor versions;
company/account/chart/currency/metric identities are reused. Existing source facts'
`profile:hash:sheet` snapshot keys and the original January report remain unchanged.

Snapshots are rederived from original retained bytes at both proposal and promotion.
The contract pins source hash, header/layout schema hash, reviewed company alias,
scope, binding, actual observed dates, its own reviewed period and exact accounting
meaning/mapping versions. All rows and missing authoritative amounts remain visible;
no supplementary amount or zero fills a gap. Coverage remains UNESTABLISHED.

Two explicit policies are supported: add a later disjoint period, or replace a
snapshot for the exact same reviewed period. A non-baseline predecessor must belong
to the exact reviewed family through a prior adoption. Duplicate successors,
competing branches, changed schema/meaning/company, and cycling back to the baseline
are refused. These contracts do not combine sources or authorize financial aggregation.

Every write uses the canonical proposal, separate reviewer, dependency fingerprint
and promotion lock. Publication rechecks effective versions, lifecycle availability
and upstream withdrawal. Family policy must equal its company's policy; adoption
policy must equal its family's. The existing tenant-fenced hidden-dependents boolean
also makes incomplete membership fail closed when field permissions hide an existing
successor. This intentionally may refuse a transition because of an unrelated hidden
dependent; it never discloses that dependent's identity. No new privileged SQL helper
or permission widening was introduced. Only one transition is accepted per change set.

The API exposes family/transition inspection and proposal, plus exact accepted
successor reopening. Requests contain references and rationale, not client assertions
of compatibility. The frontend consumer is being integrated within existing company
source accounting context, using the shared Ontology SDK and normal proposal handoff.

Native baseline evidence uses the original SEG January 2025 source SHA
d7c7e67c093b40b6f9209b301ca8fab7e4febc85c27d735babb95fa2028a8f0a:
596 rows, one missing authoritative amount at Base!S288, 51 exact dependencies and
schema hash aa506fdbc8a4c54a265d2d67b900147a7e1bdc7adfbbf4a485e6b378c22da268.
The published family is f3ce6cc0-04a1-50d8-ae11-6a64fccd18de, version
99e799f1-99c1-5dba-b0b8-208d3d396fcf. Native self-review was refused; a separate
configured reviewer accepted the baseline. Five deliberately altered generic
proposals (source hash, schema, row count, missing amounts, amount role) were refused
before retention. Foreign-entity read returned 404. The original family was unchanged.

Validation: 20 parser/snapshot tests; 20 compatibility tests including the original
snapshot cycle guard; 37 governance tests including policy/visibility and same-change
set branching refusal. The latter emulate the existing hidden-dependents helper;
native restricted-field multi-role coverage remains open. Native family publication
and refusal artifacts are in `evidence/nin56-family-native-*.json`. The source-family
helper defaults to inspection and requires `--apply` for reviewed publication.

No eligible authentic later SEG snapshot exists in the retained inventory. Native
baseline and synthetic compatibility checks do not establish authentic recurring
refresh, paired reporting comparison, full NIN-56/NIN-58 or release acceptance.

## Integrated runtime and durable transition proof

Backend 452009a and frontend edf6ecf/4d6f641 are mounted on API 8062 and web 3062.
The production build and three consumer response checks passed. Authenticated HTTP
inspection returned the exact accepted real family and its 51 dependencies;
unauthenticated inspection returned 401, client compatibility assertions and a
same-snapshot successor returned 422, and duplicate family proposal returned 409.
The original family/version/hash remained unchanged. See
`evidence/nin56-family-integrated-http.json`.

The durable native synthetic transition test passed in 92.14 seconds. Three generated
workbooks, one company, shared accounts/mappings, per-snapshot aliases, separate
source scopes/bindings/periods and available lifecycle state were retained inside
`SYNTHETIC-source-adoption-d70f7a89-516f-4843-aecd-93d8a0584b2c`.
The reviewed A-to-B transition reopened B's own February period and row count;
A's missing Base!S2, company version and family baseline remained unchanged.
Generic schema tampering, self-review, a competing A-to-C successor and invalid
same-period replacement were refused. An ordinary entity reader received 404 for
the synthetic company, adoption and retained source. No test resources were placed
in the ordinary company's visible scope. Exact evidence is in
`evidence/nin56-source-adoption-native.json`; no authentic later-source claim follows.

API and worker restarted for the integrated code. Existing SEG Function and
Transformation identities were reviewed against the new runtime manifest, producing
versions dbd0ad6d-60e9-5101-92ce-0a6fef5a380e and
2a7e0bd0-3876-587c-9bef-90fa2eb4bf28. The source accounting binding remains
8d08c8a1-3c38-53dc-aaf7-fd3a4c117910 and the original saved invocation is unchanged.
Worker process liveness after this restart is not a new workflow execution proof.
