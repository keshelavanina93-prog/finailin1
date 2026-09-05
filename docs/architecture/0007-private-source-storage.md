# G8 private evidence storage

Implements the raw evidence boundary from NIN-35 and ADR-DATA-002/003. PostgreSQL remains the authority for scoped receipts, canonical resources, reviews and lineage. New original CSV payloads reside in private S3-compatible object storage, with content-addressed keys containing tenant, exact-scope fingerprint and SHA-256. Existing immutable PostgreSQL payloads remain readable; this deployment does not rewrite historical receipts.

New receipts retain bucket, object key, byte length, SHA-256 and object version where supported. PostgreSQL stores no second raw CSV copy in the request JSON. Create-only writes use a conditional request; replay verifies existing bytes. Reads use the retained object version and check length/hash before returning content. The browser additionally hashes each download before saving it. Neither public object URLs nor direct browser credentials are exposed.

Object writes precede the PostgreSQL receipt transaction. A storage failure prevents a new receipt; a subsequent database failure can leave an unreferenced private object. Retry safely reuses verified content. There is deliberately no automatic deletion or garbage collection, which would require an approved retention policy. A prior successful receipt remains retrievable as metadata during an object-store outage; source download fails explicitly.

The API uses separate restricted S3 credentials. Local MinIO stores its data, tools, configuration, builds and caches on D:. Version pinning protects retained receipts from later versions; it is not a claim of production WORM/legal-retention certification. Raw object storage carries bytes, never accounting meaning.

`/health` reports process liveness. `/ready` requires the migrated database table and private bucket to be accessible and returns sanitized dependency status. The supervisor uses readiness before accepting the API as running successfully.

## Scope and remaining work

The current intake contract is bounded UTF-8 CSV. Arbitrary binary/multipart and connector payloads, historical blob migration, lifecycle/retention enforcement, backup/restore, cloud deployment, and large-source streaming remain separate work. No certification of authentic financial sources or full G8 completion follows from this adapter.

## Local acceptance

- Four focused MinIO/PostgreSQL cases passed: healthy/unavailable readiness, real object retention/replay, no raw PostgreSQL copy, source/export hashes, scoped denial, legacy reads, object-store failure blocking approval/download/new retention, and malformed metadata refusal. Existing canonical-binding acceptance also exercised request reconstruction from S3.
- Three adapter tests passed for conditional replay, version pinning, corruption and scope rejection. Backend Ruff/mypy and frontend build/typecheck/ESLint passed.
- The restricted service credential received HTTP 412 for a duplicate conditional write and HTTP 403 for deletion. The same object version/hash remained readable after a verified MinIO restart.
- Mounted web-proxy upload, replay, original download and evidence-bundle export passed with a clearly labeled synthetic pending receipt. `/ready` returned both database and evidence store ready. This is authenticated HTTP integration evidence, not authenticated browser acceptance or authentic-source certification.
