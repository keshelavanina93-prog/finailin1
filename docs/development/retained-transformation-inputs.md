# Retained transformation inputs — NIN-12

Completion dependencies order work. An explicit `input_binding` additionally connects a downstream ontology Function to an upstream node's retained result. The downstream invocation commits to the upstream invocation identity derived from the same transformation request. The shared immutable receipt resolves that identity to an exact result hash when execution occurs.

The consumer uses the complete retained object page and its original query cutoffs, with the same exact Object Set definition. It applies the reviewed derived properties to those canonical object versions. It does not issue a replacement Object Set query. The result records the consumed invocation, receipt hash and content-addressed calculation result. Both steps remain evidence analysis; source account observations do not become approved accounting facts.

Migration 048 adds database checks for the reviewed input binding, dependency membership, matching invocation reference, compatible Object Set, exact scope/time and a succeeded upstream result. It also requires the downstream output to preserve the upstream objects/query and exact consumed-result reference. Existing completion-barrier, immutable invocation, publication and budget guards continue to apply.

The Builds workbench distinguishes declared input from observed execution. Its existing retained-analysis inspector displays consumed-result provenance. This extends a real capability inside the replacement G8 shell; it does not restore the rejected engineering navigation.

## Verification boundary

Fourteen selected native/unit checks passed. The final two-case rerun additionally confirmed wrong-scope input refusal. Tests cover whole-page preservation, no Object Set re-query, unchanged completed replay after a later correction, stale static-dependency rejection and direct SQL rejection of a nonexistent upstream receipt. Targeted Ruff/mypy, frontend lint/TypeScript and the production web build passed.

The actual reviewed chain `6ae16d38-c3d1-4c82-9239-dda508de2545` consumed three retained SourceAccountDefinition objects from the authentic accounts workbook. All three downstream original-label values were available; object bytes, version pins and query cutoffs matched the upstream output. Its consumed invocation is `fada6b8d-ffb2-59de-8901-f5999abaedec`, receipt `b63c443ae9d32bb1d68149223129818c1b612d00ccb85ab6b3b047fa540b0a02`, result `fcr_f593423c6c1f38cc44f387516b222814fcf32e91327d14dc55ae0f34a807d125`.

After the managed API and worker were stopped and restarted, resubmitting the same request preserved the retained history. The existing no-input build also replayed unchanged. Evidence is retained in `evidence/nin12-transformation-retained-input.json` and the refreshed existing `evidence/nin12-transformation-runtime.json`. Completed replay across restart is proven; interruption during a running step is not claimed here.

Authenticated browser inspection reopened that exact build in Data → Builds, followed its downstream analysis, and showed consumed provenance, three source objects and their original labels without bound-result pagination. Local screenshots are `D:\FinAI\finailinear1\.finai\browser-verification\screenshots\g8-retained-input-chain.png` and `g8-retained-input-values.png`. This verifies this data-flow journey, not full NIN-25 acceptance.

Arbitrary value ports, joins, worksheet-to-object promotion, incremental state, external writes and financial authority remain outside this input contract.
