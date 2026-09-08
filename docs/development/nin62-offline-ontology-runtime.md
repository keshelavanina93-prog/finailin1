# Retained external ontology runtime — NIN-62 foundation

External standards supply meaning, not G8 company identity or accounting authority. This foundation retains reviewed publisher declarations and exact RDF artifacts through the existing resource, evidence, review and lifecycle services. It does not create enterprise facts, approve alignments, infer journal entries, or certify standards compliance.

## Runtime and authority

- PostgreSQL owns `ExternalOntologySource`, `ExternalOntologyRelease`, `ExternalOntologyModule` and `OntologyImportRun` versions, shared canonical identities, dependency pins, review decisions and history.
- Existing private object storage retains original RDF bytes, canonical N-Quads and deterministic import reports. Existing `SourceEvidence` identities link these bytes into resource lineage.
- `pyoxigraph==0.5.11` parses Turtle/RDF/XML and canonicalizes named-graph datasets with explicit RDFC-1.0. Each graph identifies an exact retained module artifact. The Windows CPython 3.13 wheel is hash-pinned in `requirements-local.lock`; bootstrap installs it through the existing package path.
- The local Oxigraph index is a disposable projection under `FINAI_RUNTIME_ROOT/ontology-index`, keyed by tenant/entity, exact release/version/content hash and dataset hash. It cannot replace retained evidence or publication authority. Rebuilding the same exact release creates no canonical version.
- RDF processing runs in a separate killable Python process with a minimal environment, Windows Job Object or Linux resource limits, fixed CPU/memory limits and a wall timeout. No publisher URL or import IRI is fetched. Parsing and index work occur outside the canonical publication lock.

Default importer budgets: 16 artifacts, 8 MiB original bytes, 50,000 quads, 10,000 blank nodes, 1 MiB total literal bytes, 16 MiB canonical output, import depth 16, 10 seconds wall time, 8 seconds CPU and 512 MiB memory. One import worker per API process prevents concurrent parser amplification. RDF/XML is UTF-8 only; DTD/entity declarations, RDF-star and unsupported RDF 1.2 constructs are refused. Imports must be supplied, explicitly permitted, namespace-compatible and acyclic.

Index inspection returns at most 100 subject quads and 256 KiB. An intact exact rebuild reuses its verified generation. Corrupt-index recovery retains at most two generations per key and refuses further rebuilds until an operator safely evicts the disposable cache while readers are stopped. No live generation is automatically deleted. The initial runtime uses one API process: its serialized storage reservation checks a 1 GiB root budget, with 256 MiB per index. Multiple independent API processes sharing a cache can race the reservation; a cross-process quota is required before enabling that deployment topology. Each read verifies the indexed dataset hash in a capped worker before returning its selected quads.

## Operator sequence

Run from the D: checkout after the ordinary packaged environment/bootstrap and canonical definition installation. Supply an existing operator credential through `G8_ONTOLOGY_TOKEN`; the CLI neither chooses another actor nor prints credentials. All generated evidence/runtime/index files remain on D: on Windows.

1. `python scripts/g8-external-ontology.py retain D:\Ontology\module.ttl` retains immutable bytes and returns their document ID/hash/length.
2. `propose-source D:\Ontology\publisher.json` creates a canonical publisher proposal with explicit publisher URL, namespaces, formats and license. Use the existing independent review workflow to approve it and obtain its exact resource/version/content pin.
3. `prepare-import D:\Ontology\release.json` references that pin and retained documents. Every module declares artifact IRI, format, owned namespaces, permitted imports, source URL, license and aware retrieval time. The response is either a retained parser refusal, a review-required proposal or an exact replay of an existing release.
4. Independently review the prepared proposal through the existing resource review workflow. The service replays retained RDF before acquiring the publication lock, then checks exact publisher versions and availability under the lock. A release proposal cannot also change one of its publishers. Releases/modules/runs are immutable; a changed release requires a new release identity, not an overwrite.
5. `inspect-release`, `rebuild-index` and `inspect-term` accept JSON requests with the exact release pin. Rebuild requires `ontology_propose`; all reads require `ontology_read` and retained-artifact access. There is no arbitrary path or SPARQL argument.

Default local endpoint: `http://127.0.0.1:8062/v1/ontology`. Override with `--base-url` for an isolated local runtime. The CLI refuses redirects and non-local endpoints.

Example term inspection request (replace all three pin values with actual retained values):

```json
{
  "release": {
    "resource_id": "<canonical release UUID>",
    "version_id": "<exact version UUID>",
    "content_hash": "<64 lowercase hex characters>"
  },
  "mode": "CURRENT_RELEASE",
  "subject_iri": "https://publisher.example/ontology/Term",
  "limit": 50
}
```

`CURRENT_RELEASE` checks current effective release/publisher authority and availability before and after index work. `HISTORICAL_INSPECTION` instead requires an aware `known_at` and selects an exact retained version through the existing historical inspection authority. A subsequent publisher change does not erase historical inspection. Every response declares no business effect and no current consumption authority; inspecting an old term is not permission to use it as current truth.

## API and SDK

All endpoints are authenticated POSTs below `/v1/ontology/external`:

| Path | Purpose |
| --- | --- |
| `/sources/proposals` | Prepare publisher metadata review |
| `/imports/proposals` | Replay retained bytes and prepare release review |
| `/releases/inspect` | Exact current or historical release metadata |
| `/index/rebuild` | Rebuild disposable index from authorized retained N-Quads |
| `/terms/inspect` | Bounded exact subject quads with named graph provenance |

The typed ontology client exposes exact release/index/subject inspection with explicit expected scope, authenticated transport and cancellation. It verifies the release pin, dataset hash, scope and requested historical/current mode rather than trusting an arbitrary cached response. External RDF labels/literals are untrusted data, never instructions for NYX or executable UI content.

## Acceptance limits and next stages

Synthetic retained fixtures test the engine and native publication/inspection boundaries; they are not authentic FIBO, GeoSPARQL, PROV or SOCAR alignment acceptance. Parsing is `PARSED_ONLY`, reasoning `NONE`, constraint validation `NOT_PERFORMED`. Index lookup is bounded exact-subject inspection, not general SPARQL or semantic reasoning. No performance multiplier is claimed.

NIN-62 remains open for the validator/profile foundation, exact and semantic diff, reviewed upgrades, alignment review, authentic company/map consumers, NYX grounding/serialization, product rendering and independent acceptance. NIN-25 product acceptance is not satisfied by these technical inspection endpoints.
