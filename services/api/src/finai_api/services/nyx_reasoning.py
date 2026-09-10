"""Governed, citation-first NYX reasoning boundary.

This endpoint deliberately explains exact retained resources and refuses
authoritative financial claims until a certified metric/report contract is
selected. It never creates canonical facts or executes actions.
"""

import re

from finai_api.domain.nyx_reasoning import ReasonCitation, ReasonRequest, ReasonResponse
from finai_api.security import require_permission
from finai_api.services import resources

FINANCIAL_CLAIM = re.compile(
    r"\b(forecast|profit|margin|revenue|cash flow|budget|liquidity|earnings|variance)\b",
    re.IGNORECASE,
)


def reason(principal, request: ReasonRequest) -> dict:
    require_permission(principal, "ontology_read")
    if request.selected is None:
        return ReasonResponse(
            state="NEEDS_EXACT_SCOPE",
            answer=(
                "Select one exact accepted resource before asking NYX to explain it. "
                "No company or current resource is substituted."
            ),
            refusal_code="EXACT_RESOURCE_REQUIRED",
        ).model_dump(mode="json")
    inspected = resources.get_resource(principal, request.selected.resource_id)
    selected = next(
        (
            row
            for row in inspected["versions"]
            if row["version_id"] == str(request.selected.version_id)
        ),
        None,
    )
    if selected is None:
        return ReasonResponse(
            state="REFUSED",
            answer="The requested version is not available in the authorized knowledge scope.",
            refusal_code="EXACT_VERSION_UNAVAILABLE",
        ).model_dump(mode="json")
    citation = ReasonCitation(
        reference=request.selected,
        display_name=selected["display_name"],
        object_type=selected["object_type"],
        content_hash=selected["content_hash"],
        evidence_class=selected["evidence_class"],
        authority_state=selected["authority_state"],
    )
    if FINANCIAL_CLAIM.search(request.question):
        return ReasonResponse(
            state="REFUSED",
            answer=(
                "This question requires an accepted, scope-bound metric or certified report. "
                "The selected resource is evidence for investigation, not financial authority."
            ),
            citations=(citation,),
            refusal_code="AUTHORITATIVE_FINANCIAL_FACT_REQUIRED",
        ).model_dump(mode="json")
    return ReasonResponse(
        state="EVIDENCE_EXPLANATION",
        answer=(
            f"{selected['display_name']} is a recorded {selected['object_type']} in "
            f"{selected['authority_state']} state with {selected['evidence_class']} evidence. "
            f"The exact version is cited below; this explanation does not establish cause, "
            "financial accuracy, current-use authority or permission to act."
        ),
        citations=(citation,),
        proposal_handoff="REQUIRES_SEPARATE_GOVERNED_PROPOSAL",
    ).model_dump(mode="json")
