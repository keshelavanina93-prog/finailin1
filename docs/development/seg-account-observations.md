# SEG source account observations in G8 Data

NIN-26: the retained January 2025 Base worksheet can now be inspected through
its accepted company Alias without assigning an operational chart or creating
LocalAccounts. The API returns literal debit/credit codes, side occurrence counts,
exact source coordinates and retained SourceAccountDefinition candidates. It
does not normalize codes, infer hierarchy/leaf status, or turn a code match into
an accounting mapping. Multiple matches remain visible as ambiguous candidates.

The G8 Data/NYX accounting review includes a dense expandable account table.
Original cells and candidate versions/provenance are accessible from each code.
All counts are API-derived. The response explicitly refuses accounting authority.
Definition inventory, distinct-code count and coordinate previews are bounded;
coordinate truncation is signalled in both API and UI.

Authenticated native API proof using the original SEG receipt returned 596
source rows, 38 distinct literal codes and 1,192 debit/credit cell references
without truncation. Each code currently has one exact-code definition candidate;
none was selected or promoted. The original source hash remains
`d7c7e67c093b40b6f9209b301ca8fab7e4febc85c27d735babb95fa2028a8f0a`.

Reproduce through `scripts/verify-accounting-context.py`; local evidence is
`.finai/artifacts/source-accounting-context-v2.json`. Source inspection returns
200; attempted unresolved accounting activation still returns 409. Four focused
observation tests, typing/lint checks and the isolated production web build pass.
Browser/visual acceptance and authentic financial calculation remain unverified.

The next accounting decision requires explicit ledger/book, chart/mapping and
monetary interpretation. In particular, source column S and annotated column AD
have not been equated, assigned a currency or treated as interchangeable
net/gross/VAT amounts. The pending user question requests that missing meaning;
no sign-in context or account-prefix heuristic substitutes for it.

## Live web integration checkpoint

On 2026-09-06 the existing web surface on port 3062 had an explicit
FINAI_API_URL pointing to 8062, but no API process was listening there.
Starting the managed API on its configured 8062 port restored authenticated
web-proxy session, readiness and account-observation responses to HTTP 200.
The retained response contains 596 rows and 38 codes; accounting use remains
false. Local evidence: `.finai/artifacts/live-web-source-accounting.json`.
The existing web process and its explicit configuration were preserved.

Separately, the five server proxy routes now share one API base resolver.
Its default is 8061, matching the packaged runtime, instead of the obsolete
8000 default. Explicit FINAI_API_URL overrides remain authoritative. Focused
proxy lint and the isolated production build including TypeScript pass.
These are live HTTP integration checks, not authenticated browser acceptance.
