# Retained ontology validation runtime

This component checks external meaning against an explicit reviewed constraint profile. It creates retained observations. Conformance does not grant accounting, company-fact, certification or current consumption authority.

## Canonical contracts and execution

`OntologyProfile` selects exact approved release versions and named graphs for a domain pack. `ExternalConstraintProfile` pins that profile, an exact shapes release/graph selection and an explicit evaluation-selection mode. Both use shared canonical Resource identities, independent proposal review and immutable versions. The initial profile identities are content-addressed: changing their definitions creates a new identity and requires new review. Automatic profile upgrades are not implemented.

Validation requests pin the constraint profile and a data selection contained in its ontology profile. Retention verifies exact version IDs, content hashes, current effective availability, company policy, selected graph membership and current publisher dependencies. A future editing head cannot replace the currently effective pin. A profile proposal cannot also mutate any resource it uses as authority.

The `ontology-validation/1` workflow family uses existing PostgreSQL `workflow_requests`/`workflow_events`, Temporal workers, retained source documents, private object storage and execution publication manifests. It adds no job database. The API retains intent before dispatch. If dispatch is unobservable, it returns the retained identity; retrying the same exact request redispatches safely. There is no automatic outbox dispatcher in this implementation.

The canonical retained ID is `ontology-validation:{request_uuid}`. The internal Temporal ID hashes that ID together with the complete retained scope and actor. Start, inspection and cancellation use the same derived identity, so a caller choosing another tenant's request UUID cannot reach that tenant's runtime handle.

The worker reloads current server grants, verifies the frozen plan and starts a capped child process. Cancellation and publication serialize using the canonical lock followed by a workflow-specific lock. The expensive validator runs outside those locks. An immutable terminal report supports recovery after a lost acknowledgement; generation zero publishes only the exact completed report. Cancellation before publication prevents later publication. A published report remains retained evidence.

The SQL migration guards workflow identity, exact input pins, scope, declared event identities, report-document linkage, cancellation and terminal/staging/publication consistency. SQL does not execute or prove SHACL computation. Authorized worker execution and report verification establish that boundary.

`OntologyValidationReport` is a separate canonical observation. A convenience endpoint prepares its normal review proposal from an existing published execution and canonical SourceEvidence identity. Independent approval does not change `VIOLATES`, `NOT_EVALUATED` or `REFUSED` into conformance.

## Validator contract

The initial implementation pins pySHACL 0.40.1, RDFLib 7.6.0 and pyoxigraph 0.5.11. The Windows runtime lock contains hashes for every new dependency; the existing pins are preserved. Its manifest records installed semantic dependency versions, fixed options, limits, selection, and normalized executable hashes for the controller, worker and shared resource-cap implementation.

Only retained canonical N-Quads enter the worker. It verifies dataset hashes and named graphs before selecting fresh data and shape graphs. Data and shapes retain separate blank-node scopes. Literal lexical forms are preserved, including values such as `"01"^^xsd:integer`. Publisher/import/context URLs are not fetched. Inference, SHACL-SPARQL, SHACL-JS, executable advanced extensions and unsupported shape constructs are refused or disabled explicitly.

The fixed policy uses no inference, no early abort, strict warning/info treatment and meta-SHACL checks. Supported Core components run through a version-checked adapter. Explicit root-shape selection retains referenced property-shape dependencies; it does not rely on a library selection option that can discard those dependencies.

Selection modes are distinct:

| Mode | Coverage |
| --- | --- |
| `PROFILE_TARGETS` | All targets of the selected profile graphs; no selectors permitted |
| `FILTER_TARGETS` | Explicit focus nodes intersected with natural shape targets |
| `EXPLICIT_SHAPE_FOCUS` | Explicit selected shapes evaluated against explicit focus nodes |

Counts record completed substantive Core component/shape/focus evaluations. Structural wrappers alone cannot establish a passing evaluation. Empty, deactivated or zero-target evaluation returns `NOT_EVALUATED` with no conformance assertion. Resource exhaustion, malformed or unsupported input fails closed. Nonconformance is a completed observation, distinct from runtime failure.

Default limits are 8 MiB combined input, 50,000 data quads, 5,000 shape quads, 1,000 shapes, 5,000 evaluated focus nodes, 100 selected focus IRIs, 32 selected shape IRIs, 1 MiB retained RDF report, 1,000 results, 512 MiB memory, 8 CPU seconds and 10 seconds wall time. Exceeding report limits refuses the result; it does not silently truncate evaluation.

Reports preserve machine result triples and authored messages. Generated prose is omitted under the explicit `AUTHOR_MESSAGES_ONLY` normalization policy. Before report canonicalization, actual selected input blank nodes receive reserved dataset-hash, original canonical-label and data/shape-role annotations. Report-local blank-node renaming therefore does not erase their original evidence coordinates. Caller-authored origin annotations cannot replace these mappings.

## Operator access

Authenticated endpoints are below `/v1/ontology/external`:

| Method/path | Behavior |
| --- | --- |
| `POST /profiles/proposals` | Prepare subset profile for independent review |
| `POST /constraint-profiles/proposals` | Prepare exact constraint profile review |
| `POST /validation/runs` | Retain and dispatch an idempotent validation request |
| `GET /validation/runs/{request_id}` | Retained plan, outcome, report and publication; runtime can be unobservable |
| `POST /validation/runs/{request_id}/cancel` | Retain cancellation before best-effort runtime notification |
| `POST /validation/runs/{request_id}/report-proposals` | Prepare canonical report/evidence review |

The local CLI adds `propose-profile`, `propose-constraints`, `validate`, `validation-status` and `propose-report`. Status/report lookup takes a JSON file containing the exact request UUID. Launch requires ontology read, source read and ingestion permissions. Status is owned by the retained actor; independent report review uses the normal authorized publication proof path. Both generic and operator work listings hide validation records from other actors and actors without ontology access.

The typed SDK starts, reads and cancels validation using explicit expected scope. Reads take the frozen full request and verify exact pins, graph selection, request/plan/report hashes and publication before returning a typed observation. Workflows & Actions consumes that contract from its owner-scoped work list. Its inspector shows evaluated coverage, retained state, runtime observability, verified evidence downloads and a permission-gated canonical report proposal opening the existing review surface. It does not launch validation from placeholder forms or grant approval from conformance.

## Acceptance limits

Synthetic fixtures and local durable execution prove the implemented plumbing and refusal boundaries. They do not establish authentic FIBO/GeoSPARQL/PROV profile adoption, full SHACL conformance, alignment correctness, geometry validation, finance correctness, browser acceptance or production scale. The selected authentic external profiles, comparative validator benchmark, ontology upgrades/diffs, alignment review and authentic business consumers remain subsequent dependency-ordered work. No fake product screens are added for these unfinished consumers.
