# Effective source-company attribution

Source-company matching now reads current-effective LegalEntity and Alias versions through the shared migration-032 resolver. A scheduled company rename or future Alias target no longer changes today's source attribution. Both accounting-scope observation and readiness inspection use that effective company context instead of independently reading an editing head.

Proposal editing still rereads the publication head for expected-version comparison. An unchanged current or scheduled match cannot be republished to overwrite its schedule. Source hashes, coordinates, canonical company/Alias IDs, exact dependency pins and withdrawal checks remain intact. Generic publication continues to reject stale pins; this does not authorize a proposal to bypass a scheduled company revision.

## Verification

After loading the D:-only local environment and setting `G8_BINDING_DB_TEST=1`, the focused source-company-alias, alias-time and source-accounting-context tests passed: **25 checks, 19.80 seconds**, using pytest `--no-cov -q`. Ruff and targeted mypy passed for the two changed service files.

The native temporal fixture retains actual synthetic XLSX bytes in the private evidence store and uses normal canonical proposal/review. Current metadata and alias pins remain unchanged after scheduling a company rename and a different Alias target. Mismatched targets, duplicate replacement, revoked temporal winners and future-only companies are refused. Accounting readiness uses the same current company and remains blocked without a chart.

After the API restart, read-only inspection of the authentic retained January 2025 SEG source through the production web proxy returned HTTP 200. It retained company `365aa5d9-c2ec-52e1-867a-50fe3415f486` and reviewed Alias `45a5248a-fee0-5bfe-b689-fb935d2345f1`, with unchanged versions. The missing accepted source chart remains explicit. Reproduce with `scripts/verify-effective-source-company.py`; see `nin26-effective-source-company.json`.

This repairs source identity readiness. It does not establish chart membership, ledger, currency, amount interpretation or financial authority, and does not close full NIN-26 or product/release acceptance.
