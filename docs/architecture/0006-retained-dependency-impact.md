# G8 retained dependency impact

NIN-28 proposals now retain a bounded reverse dependency snapshot across current accepted heads and proposed definitions. Review shows each affected canonical resource and exact version, its changed root, and dependency distance. Shared descendants are accepted; cycles and incomplete traversals fail closed. Promotion recomputes the fingerprint under the registry lock and refuses changed impact until a fresh proposal is reviewed.

Snapshots are append-only PostgreSQL evidence. When a snapshot includes consumers outside the proposal's read policy, the public proposal payload retains only restricted status and a fingerprint. Full details reside in a separate FORCE-RLS table accessible to authorized tenant stewards. Narrow callers cannot propose or promote changes whose complete impact they cannot inspect. The privileged hidden-consumer helper discloses only a boolean for a caller-visible root within its tenant; its search path and row-security behavior are explicit.

## Local acceptance

Three focused persistent PostgreSQL tests passed in `test_dependency_impact.py`, using isolated synthetic entity scopes and definitions. They cover multi-resource proposed diamonds, current transitive consumers, newly introduced consumers invalidating pending review, refreshed promotion, obsolete-edge exclusion, restricted evidence at rest and API reads, sentinel spoof denial, hidden-root refusal, and bounded/cyclic traversal rejection.

Backend mypy and affected Ruff checks passed. The integrated review UI passed the production build. Supervised API and web restarted healthy on ports 8061 and 3061 with all runtime state on D:.

## Remaining acceptance

This is a shared substrate capability, not completion of NIN-28 or G8. Traversal conservatively unions current and proposed edges, so an atomic cycle-removal change may require restructuring. Limits are 16 links and 1,000 retained impact entries/resources; larger changes are refused, not truncated. Historical execution impact, policy-specific certification/evaluation evidence, semantic compatibility enforcement, and an authentic schema/function/report rollback journey remain open. The fixtures prove local graph and policy behavior only.
