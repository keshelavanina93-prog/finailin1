# G8 schema compatibility in controlled review

NIN-26/NIN-28 schema proposals use a deterministic compatibility check before retention and again before promotion. Field identities, semantic bindings, kinds and reference targets cannot be changed under an existing field name. Removal and new required fields are refused. Tightening an optional field to required, or narrowing acceptance of undeclared fields, requires an explicit migration capability that is not yet implemented; a review click cannot bypass this boundary.

Compatible evolution includes optional fields, deprecation metadata and loosening a required field. Review retains structured changes by stable field identity, with before/after values and an explicit initial/backward-compatible classification. The interface displays those retained changes rather than recomputing a separate browser diff.

Malformed definitions return validation errors before registry lookup. The same shared schema authority remains in use for ontology resources and intake bindings; no separate module schema registry is introduced.

## Local acceptance

Twenty-two focused checks passed, including PostgreSQL optional-field evolution, deprecation and requirement loosening through independent promotion; rejected undeclared-field narrowing preserving the accepted head; malformed semantic UUID returning HTTP 422; and exact Georgian/space-containing field names and vendor schema keys. Backend Ruff/mypy and frontend build/ESLint passed. Explicit destructive schema migrations and full NIN-26/NIN-28 acceptance remain open.
