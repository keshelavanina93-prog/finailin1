# NIN-61 canonical CI repair

The canonical CI command stopped at ontology formatting and a web test loader
that could not resolve relative imports from a data URL. Repairing those exposed
previously hidden API typing errors and native integration checks that lacked
versioned evidence storage. The user explicitly prioritized reaching the existing
90% API coverage gate before further feature integration.

## Changes

- A shared filesystem ESM test loader resolves relative TypeScript imports while
  retaining normal package resolution. Shared backend URL configuration remains
  in the application; the tests no longer depend on data-URL module resolution.
- Ontology declarations retain their semantic content and canonical identities.
  API typing repairs narrow optional results, validator names and source row
  shapes. Unknown Temporal schedule actions are handled without an invalid
  workflow lookup. Missing retained data fails closed.
- CI provisions restricted PostgreSQL and private versioned MinIO, then installs
  canonical platform definitions before running native authority checks. MinIO
  and its client are built from the same pinned official source commits used by
  the local runtime. Credentials and generated service state are not committed.
- Existing native checks are enabled explicitly. New tests cover exact scope,
  historical version pins, independent review, immutable evidence, workflow
  replay and refusal, accounting source parsing, deterministic calculations,
  regulatory observations and quarantined reference reporting. BIFF fixtures
  use a development-only xlwt dependency. No production parser is replaced.
- The API coverage source scope and 90% threshold are unchanged. No coverage
  exclusions or skipped failing tests were added. Root mypy configuration only
  repeats the API's existing third-party untyped-library exceptions; the exact
  root CI command continues to check application code.

## Evidence boundaries

All new native source data is synthetic and scoped separately from authentic
company evidence. A green build does not establish NIN-25/NIN-59 product
acceptance, authentic accounting or regulatory correctness, production recovery,
scale, or release readiness. It permits the next frozen candidate to proceed to
independent validation under NIN-44.

The isolated repair checkout is `D:\FinAI\g8-ci-repair`. Its PostgreSQL and MinIO
ports are 55441 and 9064. It does not modify the mounted product's database,
object store, credentials, or running processes. Coverage logs and service state
remain under this checkout's ignored `.finai` directory.

The existing source-document preview contract supports BIFF XLS; accepting an
OOXML document does not establish OOXML preview support through that endpoint.
The separate hydration preview path must not be conflated with it.

Local and canonical outcomes are recorded separately in the accompanying
`evidence/nin61-ci-repair.json`. Canonical acceptance requires both GitHub jobs
to complete green on the pushed canonical SHA. Branch protection follows that
green result; the absent `main` branch must be recorded explicitly rather than
reported as protected.
