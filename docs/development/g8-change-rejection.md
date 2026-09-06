# G8 retained change decisions

NIN-25 operator progress over the existing NIN-28 review authority.

The replacement G8 inspector now offers approval and rejection in the same review
panel. Rejection is available when deterministic evaluation or dependency checks
block approval. It uses the existing canonical decision endpoint, records the
operator's rationale, and does not alter accepted business records. The server's
retained response updates the selected proposal and work state and refreshes the
queue; the client does not invent a successful decision.

Approval still requires current eligibility, and the server rechecks it during
promotion. Both decisions retain the existing authentication, scope and reviewer
checks. A recorded rejection cannot be converted into approval or given a different
reason by retrying the request. Engineering access remains separately available;
it is no longer required for this decision.

## Focused evidence, 2026-09-06

Native PostgreSQL plus authenticated HTTP verification in
`services/api/tests/test_proposal_rejection.py` passed: failed-evaluation rejection,
exact retained rationale/reviewer/time, idempotent retry, immutable decisions,
authentication denial, and unchanged accepted resource/version history. The
synthetic fixture is not authentic company evidence.

Web TypeScript and focused ESLint passed. Next.js production build passed in the
isolated D:-resident `.next-history` directory. React review covered keyed state,
submission guards, retained-response updates and accessible form controls.

Browser acceptance remains unverified: inspection of the existing G8 tab through
CUA timed out. The earlier web3072 launch was rejected by automatic approval review
with `blocked by policy`; no equivalent launch workaround was attempted. These
limitations do not block independent backend implementation and do not establish
NIN-25 completion.
