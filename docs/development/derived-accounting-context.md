# Derived accounting source context

NIN-53 identified a shared consumption guard gap: a derived fact could retain accepted accounting ancestry while declaring an unrelated posting date or fiscal period. The repaired authority validates explicit period identities against the exact accepted SourceAccountingBinding on source facts, derived facts and typed calculation consumers. A derived posting date must equal the unique date of its actual contributing accounting source facts. The source scope's coverage envelope is not permission to relabel a fact.

The existing same-period aggregate case remains supported without inventing a single posting date for multiple source dates. Cross-period transformations and new temporal aliases have no new authorization contract in this change. Existing measure-free typed calculation consumers retain their current path.

Focused verification: `test_accounting_consumption.py` and `test_accounting_promotion.py` passed 48 cases in 1.36 seconds. New cases reject a changed date within the same month, a 2030 date, an unrelated derived period, an unrelated explicit source period and a falsely single-dated multi-date aggregate. Original source date and bound period, and a same-period aggregate without a fabricated date, pass. All fixtures are synthetic; no withdrawn source workbook was used. Ruff passed. Targeted mypy crashed internally in its typeshed `zipimport.pyi`; no typing result is claimed.

Candidate source SHA-256: `d4443b845ee83ac1e5d2a07333cc24e987a8ccd283678dd32805ec2dad2551fe` for `services/api/src/finai_api/services/accounting_consumption.py`. Independent revalidation and authentic downstream report acceptance remain separate gates. This repair does not certify a report or expand the finance feature sequence.
