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
