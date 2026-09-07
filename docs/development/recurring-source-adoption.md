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
native transition/multi-role coverage remains in progress. Native family publication
and refusal artifacts are in `evidence/nin56-family-native-*.json`. The source-family
helper defaults to inspection and requires `--apply` for reviewed publication.

No eligible authentic later SEG snapshot exists in the retained inventory. Native
baseline and synthetic compatibility checks do not establish authentic recurring
refresh, paired reporting comparison, full NIN-56/NIN-58 or release acceptance.
