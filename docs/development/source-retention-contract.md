# Source retention contract

NIN-27 / NIN-35 `source-retention/1` classifies newly retained source bytes as
`IMMUTABLE_SOURCE_EVIDENCE`. Metadata is stored with the existing immutable
hydration receipt and exposed through the shared receipt contract. Legacy
metadata remains readable without inventing a historical policy decision.

The disposition is `PRESERVE_PENDING_GOVERNED_DISPOSITION`. Legal policy is
explicitly `NOT_ESTABLISHED`: no retention period, legal hold or deletion approval
is inferred from upload, source type or accounting period.

The private evidence adapter checks bucket lifecycle configuration before each
write and during readiness. Enabled current-object or noncurrent-version expiry
rules refuse the operation. This is conservative for the dedicated evidence
bucket, including filtered expiry rules. Lifecycle inspection failures fail
closed. The runtime can inspect lifecycle configuration but cannot change it or
delete evidence. External administrators remain a trust boundary; this check is
not a transactional S3 Object Lock or a legal-compliance certification.

The local provisioner updates existing scoped service-account policy without
rotating credentials or rewriting already-protected credential ACLs.

Verification: five focused adapter checks passed, including both automatic
expiry refusal cases. The real D:-resident MinIO accepted an explicitly synthetic
source, returned its retention metadata and reproduced its exact bytes. Shared
contracts passed TypeScript checking. Broader artifact classes and reviewed
disposition/deletion workflows remain open; no deletion has been implemented.
