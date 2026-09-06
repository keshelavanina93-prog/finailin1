# Effective definition execution

Unpinned ontology execution now selects the same current-effective version as the definition catalog. Previously an unpinned read selected the latest editing head, which could be a future-effective definition excluded from the catalog. Explicit definition-version pins retain replay semantics, including applying a saved definition to historical data. Editing still resolves publication heads and enforces the existing expected-version conflict check.

Focused native verification passed: 17 checks in `test_definition_history.py`, `test_derived_runs.py` and `test_derived_coalesce.py` (15.99 seconds, `G8_BINDING_DB_TEST=1`, pytest `--no-cov -q`). Scheduled Object Set and Type Group successors leave default execution on the catalog's current version; explicit future pins replay their own definitions. Future-only definitions are unavailable by default but remain editable. Stale editing versions and revoked temporal winners are refused. Ruff and targeted mypy passed.

After API restart, the retained source account Object Set `bbbe95f6-a0d0-4313-ab3e-6ebc73177087` executed through the production web proxy using the exact version returned by its catalog. It returned source account definitions from the retained chart. Reproduction: `scripts/verify-effective-definition-runtime.py`; readback: `nin26-effective-definition-runtime.json`.

Scheduling behavior uses synthetic fixtures. The deployed source query is a real retained-source read, not activation of ledger accounts or financial certification. Full ontology, finance, intelligence, frontend and release acceptance remain open.
