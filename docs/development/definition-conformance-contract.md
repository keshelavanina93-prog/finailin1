# Definition conformance and business-use authority

G8 retains a narrow conformance claim against an exact canonical definition and an
exact reviewed CertificationContract. The first supported claim is
`CANONICAL_DEFINITION_CONFORMANCE`, evaluated by the existing
`canonical-structural-contract/v1` promotion evaluator. It cannot assert source
authenticity, accounting accuracy or financial certification.

Contracts are canonical resources with normal schema, proposal, review, immutable
version and dependency history. An optional canonical subject schema is pinned by
the contract and must match the subject's actual schema version. Only the three
bootstrap definition types may omit that schema. Typed control contracts can use
platform scope; enterprise facts retain their existing policy boundaries.

`POST /v1/ontology/certifications/evaluations` takes exact subject/contract references
and a request identity. The server verifies retained successful proposal evaluation,
content/version binding, declared checks and effective upstream state. The caller
cannot provide a PASS result. Repeated identical requests return the original
receipt; conflicting identity reuse fails. `GET .../receipts/{receipt_id}` returns
immutable historical evidence, explicitly with `current_use_authorized: false`.

Persistence uses migrations 034–036. PostgreSQL independently checks accepted
publication, exact policy/subject pins, retained evaluation, complete transitive
lineage and current availability. Update/delete/truncate are refused. API readiness
requires the entire migration chain through 036.

The internal current-use verifier rechecks policy and subject state before returning
a positive conformance result. It is not an independent business-use grant.
CERTIFIED lifecycle transitions and consumers remain unavailable until their exact
policy requirements and matching Python/SQL guards are integrated. NIN-27 remains
open; this contract does not complete NIN-5, Finance, intelligence or release.

The replacement G8 shell separately displays definition review and retained material
authority, business lifecycle, epistemic state and availability. The inspector and
NYX use the same exact resource/version/knowledge-cutoff contract. Historical absence
of an event does not establish current state. NYX replies retain their original
Trace/History references after the selected object changes.

Focused native verification passed five cases covering replay/conflicting identity,
withdrawal with historical readback, forged SQL lineage omission, immutability,
isolation, mismatched type, scheduled policy versions and platform control publication.
Ruff and targeted typing passed. The deployed API/web evaluation of the retained
source-account Object Set, identical repeat and historical readback are recorded in
`evidence/nin27-definition-conformance-runtime.json` after API restart. This is
technical conformance of a real saved definition, not a financial certificate.

Frontend TypeScript, focused lint and the production build passed. Authenticated
browser verification uses the retained Gas regulatory rule and its exact knowledge
cutoff; it does not supply the missing financial/intelligence acceptance journey.
The browser then selected another object and reopened the original NYX reply's
Trace. The request retained resource `f2412b1d-fe1f-423e-966d-95f326d0cc0a`, version
`123923c7-5ee4-5c53-8ca7-7f4c08432655` and knowledge time
`2026-09-06T23:19:25.102010+00:00`. Viewed local captures are
`.finai/artifacts/browser-shots/g8-definition-state-nyx.png` and
`g8-definition-original-trace.png`. The trace remained explicitly bounded (8 of 17
versions). Browser verification does not certify financial or regulatory conclusions.
