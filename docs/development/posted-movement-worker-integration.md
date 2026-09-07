# SEG posted movements: main runtime integration

The main development branch now consumes the reviewed January 2025 SEG source
through the shared Function, Transformation, Temporal worker and retained report
result. Source authority remains the user's explicit statutory/reglamented 1C
interpretation: GEL, `Сумма` as posted, no blanket VAT adjustment, and `Amount`
preserved as a non-authoritative observation. This is a partial posted-movement
analysis; it is not a complete ledger, trial balance or financial statement.

## Integrated implementation and canonical state

Frozen vertical commits e33a0f0, b0ce23f, 4c7c053 and 69c368a were integrated as
99c705d, 82fe7d9, 16a5f1f and 1ce0144. The equivalent NIN-53 correction already in
main was not duplicated. Existing unrelated working-tree changes were preserved.
Migration 062 follows 061 and retains the materialized Object Set budget rules.

The replay helpers used the target runtime's separate proposer/reviewer through
canonical review and lifecycle services. They checked the original retained hash,
reused the existing company and all 38 account identities, and published target
versions rather than copying the isolated database. Before definition preparation,
the target Function/Transformation schemas were checked: no fields removed or
changed. Input availability remains provisional OBSERVED, not certified.

| Authority | Target resource | Target version |
| --- | --- | --- |
| Company | 365aa5d9-c2ec-52e1-867a-50fe3415f486 | Existing canonical company |
| Accounting binding | f4cf95a5-9552-519c-8e59-96ee06bd4308 | 8d08c8a1-3c38-53dc-aaf7-fd3a4c117910 |
| Function | 94c26511-53bf-5dd4-97e8-b89a11334bd3 | 43338349-1dde-5fa5-81a0-8a94c871f1bc |
| Transformation | b062ec8f-8b97-53cb-ad16-91d6d5c52b32 | d356c02f-9cbf-5707-a816-1b958599e728 |

The Function pins 48 shared inputs, including exact account mappings, source,
scope and binding. Its executable manifest is recorded in the machine evidence.
The retained source hash is
`d7c7e67c093b40b6f9209b301ca8fab7e4febc85c27d735babb95fa2028a8f0a`.

## Actual worker checkpoint and recovery

Build request `d1393555-a1c2-4b0a-b071-d59a1b0a9a92` was submitted through the
authenticated API to Temporal. After the Function completed, the workflow paused
before publication. The owned worker was stopped and restarted (PID 46188 to
41332). The API then returned the same paused checkpoint. Resume published one
result without repeating the completed node. Temporal and the workflow both
reported COMPLETED.

The completed node, staged output, invocation, receipt and source contributors
survived the restart unchanged. Resubmitting the identical request preserved the
retained build and invocation hashes, events and sole publication.

- Invocation: `c631bb9c-f92e-5dd9-a693-233c1b3b7925`.
- Receipt: `1cb82d90e0945947feb5aee646d8dc3ce076a4c2311b4b2eea17a41dfe2350d7`.
- Publication: `pub_5bc23eacba3cd9b4bd4eb8739ddb1588dbd563059c40cfa537376675310dbe9b`.
- Coverage: 595 included amounts, 596 retained rows, 59 account-side groups.
- Exclusion: `Base!S288`, missing literal posted amount; no zero substitution.
- Exact debit and credit control sums: `12502967.2300000000006576` GEL each.
- Persisted budget: 596 returned rows, 0 derived evaluations, 3,592,612 JSONB bytes.

The proof helper initially expected the unqualified cell name `S288`; the retained
contract correctly uses `Base!S288`. That verification assertion was corrected.
The already completed build was then read back and its checkpoint, restart
identities, resume event, unchanged node and publication revalidated. No replacement
calculation was used to conceal the failed assertion.

## Focused verification and remaining gates

Fifty focused accounting/source-binding tests passed. The integrated production web
build passed, including TypeScript. On the actual main invocation, rollback-only SQL
probes rejected a forged total, wrong currency, removed exclusion and missing
authority proof. A foreign company received 404; saved history retained its receipt.

Evidence is in `evidence/nin58-posted-movement-worker.json`,
`evidence/nin58-worker-restart-processes.json` and
`evidence/nin58-posted-movement-guards.json`. The helper
`scripts/verify-posted-movement-worker.py` can perform readback without starting new
work; `--replay` checks the existing request's idempotency. For a new checkpoint
proof, use `--pause` with a fresh evidence path, record the owned worker restart,
then `--resume --restart-evidence PATH`.

NIN-50 independently reconciled the frozen vertical result to the original OOXML
in cycle 9. Independent main-worker consistency and Finance browser acceptance
remain separate checks. The product stream is now exposing this same published
invocation through Finance and an Open in Finance handoff from retained builds.
NIN-25, NIN-49, NIN-58 and release acceptance remain open. Compatible later-source
adoption, shared Finding/Investigation state and the rest of the golden journey
remain unbuilt or unproven.
