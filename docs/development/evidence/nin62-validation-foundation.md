# NIN-62 validation/profile foundation evidence

Implementation builds on canonical foundation `0212bc4d8b7b23bd6f327c1b77e3a085d8b5d64e`, in isolated `D:\FinAI\g8-ontology-import`. Canonical application and user edits remain on that integrated foundation until the new candidate passes its required CI gate.

Focused evidence completed before candidate publication:

| Boundary | Evidence |
| --- | --- |
| Offline capped validator | 39 real subprocess tests passed in 27.50 seconds; Windows and Linux static types passed |
| Profile authority | 9 native cases passed; 2 affected cases passed after replay hardening |
| Canonical report review and metadata policy | 2 new native cases passed in 27.33 seconds |
| Durable validation records and refusal | 9 unique native cases passed across two runs; final boundary selection passed in 42.50 seconds |
| Reviewed installer | Expanded seven-type native regression passed in 12.09 seconds |
| API outage/cancellation and runtime isolation | 5 focused cases passed in 6.52 seconds; runtime identity bound to actor and every scope field |
| Work-list ownership | Native permission and cross-actor visibility proof passed in 21.44 seconds |
| Actual local Temporal execution | Unique synthetic queue completed load → validate → publish using scoped runtime identity; 18.05 seconds |
| Actual HTTP, CLI and typed SDK | One native proof passed in 34.20 seconds: published conformance report, runtime outage, retained start, cancellation and subsequent read |
| Typed SDK guards | 32 package tests passed, including nine validation cases; build and type checks passed |
| API static integration | Ruff passed; mypy passed over 184 source files |
| G8 workbench | Five focused model tests, typecheck, focused lint and production build passed |
| Web proxy integration | Four allow/deny and forwarding tests passed; rebuilt production artifact passed |

The real local Temporal workflow is `ontology-validation:976febcc-d86a-4783-92d6-e9629d49090a`, dispatched with runtime identity `ontology-validation-runtime:dc72fb98af299686be630664176b2a8935623174ebee0540e6766c90a92c5c80`. It completed with a retained `VIOLATES` observation and exact publication; runtime completion did not turn that observation into conformance. The worker used its own test queue and stopped afterward. Exact scope, profile/data/shape pins, plan hash, report reference and publication ID are retained in `.finai/artifacts/nin62-temporal-validation.json` in the isolated checkout.

The actual HTTP proof read published workflow `ontology-validation:300ea85d-0f96-4c93-8ae8-c51855c8f40d` through both CLI and SDK. It verified request, plan, report and publication hashes against the retained response. A separate exact request was retained while Temporal was deliberately unreachable, then cancelled and read back as cancelled. The owned API stopped afterward. Evidence is `.finai/artifacts/nin62-validation-http-sdk.json`; credentials remained in the child environment and are absent from evidence.

Dependency evidence is in `nin62-shacl-dependency-validation.json` and `nin62-shacl-wheel-provenance.json`: new wheel hashes verified against official PyPI metadata, offline hash-required installation, previous 57 lock pins unchanged, exact literal preservation and no optional JS/HTTP extras. Durable service evidence is in `nin62-validation-runs-evidence.json`, including source hashes and both focused-run logs.

Refusal cases cover unsupported executable shapes, vacuous evaluation, recursive/budget failures, altered data hashes/graph selections, original blank-node coordinates, source withdrawal during work and before publication, changed operator grants, cross-scope access, cancellation races, forged terminal SQL, report outcome/plan/hash substitution, self-review and immutable replay. Parser/index tests from the preceding foundation are not repeated as new validator acceptance.

The Linux early probe must exercise the actual capped validator before the mandatory full API CI and unchanged 90% coverage gate. Local focused results do not replace that integration gate.

## Exact coverage gate correction

Candidate `2e264364de202b0d527b801de25278143dad6f11` failed run `34177228866`: 1,345 passed, 18 skipped and one native materialized-group-count failure. Its focused reproduction passed locally; no production defect was declared repaired. Diagnostic-only `fd7528580ff3cf068007a6234f902b8820539d6b` exposes sanitized failure stages without changing materialization behavior.

Run `34178419126` then passed all 1,346 tests (18 skipped), but its GitHub success is not coverage acceptance. The report contains 16,177 statements and 1,620 missed: 89.98578% covered. pytest-cov used coverage's default zero-digit rounding for its exit decision, despite printing a below-90 failure message. The candidate remains excluded from canonical integration until exact count enforcement and a new full run pass. Neither denominator exclusions nor a reduced threshold are permitted.

Ten focused orchestration cases now prove that exhausted activity failure and cancellation at every stage stop subsequent work and leave the workflow interrupted. Completed retained reports may contain CONFORMS, VIOLATES, NOT_EVALUATED or REFUSED; completion does not grant semantic or business authority. These are injected activity-boundary tests, distinct from the real Temporal execution proof above.

Authenticated browser inspection reached the replacement G8 shell and real owner-scoped validation work list. Opening the report found a missing Next proxy allowlist entry. The fix permits only strict-UUID inspection GET and report-proposal POST, and rejects adjacent commands and malformed routes. The post-fix authenticated browser repeat remains unobserved; route tests and a successful build do not establish browser acceptance.

All source/profile fixtures in this evidence are synthetic. Authentic selected FIBO/GeoSPARQL/PROV profiles, standards conformance, benchmark comparison, ontology upgrades, alignment, business/map consumers, browser acceptance and release acceptance remain open. This component is a real validation runtime; it is not completion of NIN-62 or the G8 product.
