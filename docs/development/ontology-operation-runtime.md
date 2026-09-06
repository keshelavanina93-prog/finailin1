# Ontology operations: retained preparation, effects and review

Implemented locally on 2026-09-06 for NIN-6's ontology operating boundary and NIN-29's shared effect authority. This is not completion of either issue or of the ontology engineering program.

## Executable behavior

`POST /v1/ontology/operations/bindings` accepts a request UUID, an exact published ObjectBinding resource/version, an Object Set query and a rationale. Preparation runs the existing typed mapping implementation. It requires 1–100 source-backed objects, matching source-schema versions and unique target identities. The proposed mutations retain the source-object, binding and target-schema versions. Object Sets exposes this action and retained history for the selected binding. No artificial binding definitions were installed to fill the selector.

`POST /v1/ontology/operations/licence-notices` runs the existing original-Matsne parsing and company-identity validation through the same operation path. Licence preparation now pins the exact company, supporting registration binding and already-published evidence versions. Current resource validation and final review reject changed source versions. Issuance notices remain historical evidence; they do not create current HOLDS_LICENSE links, tariffs or financial obligations.

Both paths commit the frozen request and ResourceProposal to the existing immutable `workflow_requests` authority before attempting the proposal effect. The operation identity includes the exact authorized scope, actor and caller request UUID. Reusing that identity with different content is rejected. Its proposal UUID is deterministic and retries submit the identical frozen payload to the existing canonical proposal authority. Publication continues through the existing resource review transaction; no second publication store or reviewer role was added.

Attempt starts, domain failures and the proposal receipt use existing immutable `workflow_events`. A crash after proposal commit but before receipt does not require a new proposal. Resume recovers it. A stale ObjectBinding head blocks a new effect but does not prevent readback of an already-retained effect.

`GET /v1/ontology/operations/{id}` returns the authoritative proposal/review state and retained events. `POST /{id}/resume` retries preparation's frozen effect. `GET /v1/ontology/operations?document_id=...` or `?binding_id=...` reads the latest 20 operations in the exact authorized scope. The browser uses this database history after remount/restart, and exposes prepared-operation recovery and review readback.

## Local authentic evidence

- SGG original Matsne notice 2575115, licence 127, registration 202403121: operation `opa_009dbb9483f0499e2b974a77db17d7191f98e4a5614db5644626af9f77388097`; proposal `3b6d27ef-fe03-5d6f-9c86-3fb98798cdfd`. An injected interruption after canonical proposal commit recovered the same proposal, retained one proposal receipt, and rejected a different payload under the same request UUID. The separately reviewed published result survived API and web restart.
- Sakorggazi original Matsne notice 2184003, licence 125, registration 208147637: browser inspection → company/rationale → operation preparation → separate review → published outcome. Operation `opa_ca5eced6def25c9076a13dad5e22a0edac5cd0b5e7e6a0771643aac671f52abf`; proposal `c220506f-1f18-540f-9ff9-fb138694ebc1`. Its frozen proposal includes six existing evidence/identity version pins, including the selected canonical company.
- Local artifacts: `.finai/artifacts/ontology-operation-recovery.json`, `ontology-operation-browser.json`, `ontology-action-final.json`, `ontology-action-final.png`. These are local runtime evidence, not remotely published release artifacts.
- Production frontend build and focused lint passed. Focused regression checks cover stale-binding rejection versus existing-effect recovery and the historical licence identity boundary. No broad test-count target was used.

## Remaining implementation boundary

This executor currently supports two typed in-process handlers, synchronously invoked or explicitly resumed. It is not the complete shared Function authority: deployable code/dependency identities, typed general function results, worker dispatch and output publication remain required under NIN-47/NIN-12/NIN-32. It is not a general workflow engine with scheduling, parallel branches, compensation and autonomous recovery. Domain failure events and retained attempts do not themselves constitute a complete outcome/compensation ledger.

NIN-6 still requires complete authoring/version evolution and generated SDK contracts, ontology-backed application composition, and integrated shared Functions/Actions/Metrics. NIN-40 still requires actual effective regulatory rules and deterministic calculations with their supporting legal evidence. SGP and SGG financial context must continue to distinguish company, ledger, source grain, overlaps, time behavior, units and source authority. Historical company and licence evidence cannot fill missing current legal or accounting authority. Keep NIN-6/NIN-29/NIN-47/NIN-40 and their unsatisfied dependencies open.
