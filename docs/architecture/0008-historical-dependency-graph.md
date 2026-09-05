# G8 historical dependency graph

NIN-27 consumers can call `GET /v1/ontology/resources/{resource_id}/graph` with independent timezone-aware `valid_at` and `known_at` timestamps. The shared registry selects the root version effective at that business time and recorded by that knowledge time. Every upstream edge follows its immutable target-version pin. Later corrections or revocations never silently replace those dependency versions.

The response is explicitly `HISTORICAL_LINEAGE`. It preserves canonical resource and version identities, recorded authority state, effective/recording timestamps and typed dependency relations. It does not grant permission to execute or publish a current authoritative result. Requested identity and redirected identity remain distinct: alias/merge resolution uses its existing dedicated API.

PostgreSQL RLS applies before nodes are returned. Missing or hidden targets make the whole trace unavailable; the API does not expose partial names/identifiers or infer missing nodes. A shared registry lock prevents reads from mixing concurrent accepted transactions. Traversal refuses cycles and incomplete graphs beyond depth 16, 1,000 versions or 5,000 relationships. Multiple retained versions of one canonical identity are allowed.

The advanced history inspector uses the same API and displays the retained version trace with the two time selections. It is a consumer of the shared graph, not a separate browser graph model.

## Temporal boundary

Dependency effective intervals describe those recorded versions; they are not rebound or filtered into a new execution set. A dependency recorded after the requested knowledge time is refused. The current schema records per-row system timestamps; a requested instant between rows of one atomic acceptance can therefore be refused rather than represented as a complete historical view. Commit-time temporal indexing remains future work.

## Local acceptance

Three focused PostgreSQL cases passed: historical root selection, preserved pins after correction/revocation, explicitly revoked historical roots, complete edge endpoints, timezone validation, unauthenticated/cross-scope denial, hidden-target refusal, traversal limits, and future-recorded dependency refusal. Backend Ruff/mypy and the frontend production build passed. An authenticated mounted web-proxy request returned a complete historical lineage graph; database and evidence-store readiness remained healthy. These are synthetic/local substrate proofs, not authoritative financial execution or authenticated browser acceptance.
