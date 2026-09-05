# Canonical binding and atomic review evidence

This is foundation evidence for NIN-26/NIN-28, not G8 product-shell acceptance.

- Ingestion can bind an external account code through an explicitly selected, approved source-system Alias version to the same canonical LocalAccount used by ontology consumers. Original source codes remain intact. Alias and target account revocation block pending intake approval; earlier exports remain unchanged.
- One tenant-restricted proposal can atomically promote shared schema/semantic definitions and company-scoped function/report definitions. Each resource retains its own policy and exact dependency version pins. This does not execute functions or generate reports.
- Migration 009 enforces accepted-content matching, head policy, dependency policy and retained dependency pins. Failed publication rolls back decisions and versions together. Legacy requests/proposals retain their serialized hash when new optional fields are unused.

Focused verification: 21 combined tests passed; one newly added hash assertion incorrectly passed a dictionary to the model-only hashing helper. Corrected the assertion to calculate the legacy JSON hash directly; its focused rerun passed. The combined run includes PostgreSQL alias revocation, atomic publication/rollback and cross-company/tenant-envelope isolation. Ruff passed all affected Python files. Web production build passed. Managed API, web and MinIO restarted successfully on D:.

The four existing engineering workspaces are temporary internal access. Metadata and an explicit notice identify this boundary. No replacement G8 shell or frontend acceptance is claimed. Real downstream product surfaces must follow NIN-25's business navigation and shared Detect → Explain → Trace → Act context.
