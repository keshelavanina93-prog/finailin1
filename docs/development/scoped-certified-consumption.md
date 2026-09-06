# Reviewed certification and exact-policy consumption

NIN-27 now supports AUTHORITATIVE → CERTIFIED through an explicit reviewed request
binding an immutable conformance receipt and exact canonical contract version. The
server retains the receipt hash separately from caller input. A bare CERTIFIED label
is refused by both service and PostgreSQL. The current supported claim remains
definition conformance; it does not certify financial correctness or source authenticity.

Certification policies and subject versions are rechecked at request, approval and
current consumption. Reviewed availability amendments preserve the original evidence.
Repairing DEGRADED to AVAILABLE can inspect the subject's prior degraded state without
ignoring a withdrawn policy or ancestor. Withdrawal preserves historical evidence and
remains possible after the policy is revoked.

Consumers declare `certification_requirements`, mapping each direct material resource
to an exact CertificationContract reference. All recorded direct inputs must still
be supplied. Only the consumer's actual schema and mapped policy pins are controls;
they require AUTHORITATIVE and AVAILABLE state. An arbitrary schema input is not an
exemption. Every other input must have the certificate required by the consumer.
Even an AUTHORITATIVE consumer rechecks a CERTIFIED input's exact receipt and policy.
The transitive authority guard checks certified ancestors as well.

Migration 037 implements reviewed transitions and the shared SQL receipt verifier;
038 enforces the same consumer/control/certificate rules in PostgreSQL. New certified
receipts use `guarded-consumption/3`; ordinary `/2` receipts remain supported.
Historical receipt retrieval never authorizes current use. Status reports policy
withdrawal as BLOCKED and preserves the original receipt.

The existing G8 inspector and NYX present “Definition conformance certified” only
after reading a matching retained receipt at the selected knowledge cutoff. They
show its meaning and limitations, with exact references in secondary detail.
Financial certification is not inferred from that label.

## Focused acceptance

- Native reviewed lifecycle: two cases passed, including missing/forged certification,
  independent review, availability repair and policy withdrawal before approval.
- Native combined publication → lifecycle → exact certified consumption → withdrawal:
  passed in 16.67 seconds. A forged material-as-control input was refused. Both a
  CERTIFIED consumer and an AUTHORITATIVE consumer stopped accepting the certified
  input after its policy was withdrawn; historical receipts stayed unchanged.
- Existing lifecycle, guarded accounting and requirement-boundary checks: 14 passed
  in 34.02 seconds. These preserve ordinary authority and accounting rejection rules.
- Focused Ruff and typing passed for the new/changed services. These are synthetic
  contract proofs, not authentic financial or release acceptance.
- After API/web restart, authenticated web-proxy readback returned the unchanged
  synthetic `/3` receipt and BLOCKED current status after policy withdrawal.
  Evidence: `evidence/nin27-certified-consumption-runtime.json`; API readiness passed
  through migration 038.
- Frontend focused lint/types and production build passed. Authenticated browser
  inspection of the actual Gas rule showed definition review separately from absent
  material state at `2026-09-06T23:36:25` UTC. Viewed capture:
  `.finai/artifacts/browser-shots/g8-certification-gas-inspector.png`. Positive
  CERTIFIED rendering is not browser-accepted; the certified fixtures remain in
  explicitly synthetic scopes and were not presented as real company facts.

NIN-27 remains open for shared artifact-retention classification and governed
disposition. Source preservation exists, but actual legal periods/holds/obligations
remain unestablished and no deletion compliance is claimed.
