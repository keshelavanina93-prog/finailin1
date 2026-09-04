# ADR 0001: Shared platform foundation and authority boundary

- Status: accepted
- Scope: initial monorepo and enterprise hydration slice
- Linear alignment: FinAI / NYX Core platform reconstruction, NIN-24, NIN-25

## Decision

FinAI / NYX Core is one evidence-native enterprise operating platform. Finance,
planning, industrial operations, interoperability, and NYX are domain packs over
shared identity, scope, authority, lineage, policy, function, metric, action, and
release primitives.

The initial deployment shape is:

- `apps/web`: the unified React/Next.js operator environment;
- `services/api`: FastAPI application and deterministic platform/domain logic;
- `packages/contracts`: language-neutral schemas and TypeScript contracts;
- immutable object storage for source evidence (adapter to be implemented);
- PostgreSQL for governed resource state (adapter to be implemented);
- workers for replayable builds and external-effect protocols (to be implemented).

## Authority invariant

Incoming evidence hydrates a prebuilt operating model. It never expands its own
authority. A `SourceAuthorityContract` declares exact tenant/entity/period/currency
scope and the observations a source can prove. The compiler may produce:

- `OBSERVED`: directly supported by retained source evidence;
- `DERIVED`: deterministically calculated from supported observations and a versioned rule;
- `INFERRED`: a reviewable candidate that is never canonical authority;
- `UNAVAILABLE`: not supported by the evidence supplied.

Every compilation returns a content-addressed `ConstructionReceipt`. Promotion to
canonical enterprise state is deliberately outside the compiler and will require
validation, reconciliation, policy, approval, and persistence receipts.

## Consequences

- Language models may propose mappings or explain results but cannot create or
  silently mutate authoritative financial facts.
- Exact scope, authority state, evidence references, rule versions, and hashes are
  part of the product contract, not log-only metadata.
- UI states must distinguish unavailable evidence from errors and inferred values
  from observed or deterministic values.
- CI verifies contract parity, deterministic compiler behavior, frontend types,
  lint, tests, and a production build.
