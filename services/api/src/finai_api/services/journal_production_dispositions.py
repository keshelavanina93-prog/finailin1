"""Read current item outcomes without rewriting immutable production intent."""

from datetime import UTC, datetime
from uuid import uuid5

from psycopg.rows import dict_row

from finai_api.domain.journal_production import JournalProductionRequest
from finai_api.domain.resources import CanonicalResource, ResourceProposal
from finai_api.security import require_permission
from finai_api.services import journal_production_history, resources
from finai_api.services.entity_movement_review import digest
from finai_api.services.workspace import WorkspaceError


def pin(node):
    return {key: str(node[key]) for key in ("resource_id", "version_id", "content_hash")}


def published_bundle(proposal, versions):
    """Only versions produced by this exact approved proposal establish publication."""
    expected = {str(m.resource_id): m for m in proposal.mutations}
    if len(versions) != len(expected) or {v["resource_id"] for v in versions} != set(expected):
        raise WorkspaceError(409, "Exact published journal bundle is unavailable")
    for version in versions:
        mutation = expected[version["resource_id"]]
        if (
            version["proposal_id"] != str(proposal.proposal_id)
            or version["object_type"] != mutation.object_type
            or version["attributes"] != mutation.model_dump(mode="json")["attributes"]
            or version["authority_state"] != "APPROVED"
        ):
            raise WorkspaceError(409, "Published version differs from retained proposal")
    journal = next(v for v in versions if v["object_type"] == "JournalEntry")
    lines = [v for v in versions if v["object_type"] == "JournalLine"]
    if len(lines) != 2 or any(
        v["attributes"]["journal_id"] != journal["resource_id"] for v in lines
    ):
        raise WorkspaceError(409, "Published journal membership is inconsistent")
    return {
        "journal": pin(journal),
        "lines": [pin(v) for v in sorted(lines, key=lambda v: v["resource_id"])],
    }


def compile_dispositions(manifest, request_id, company_id, read_proposal, read_versions):
    """Conserve every selected item, including crash-interrupted PREPARED attempts."""
    try:
        request = JournalProductionRequest.model_validate(manifest["request"])
        source_sha256, binding = manifest["source_sha256"], manifest["binding"]
        if manifest.get("contract") != "source-journal-production/1":
            raise WorkspaceError(409, "Unsupported journal attempt contract")
        if request.request_id != request_id or request.company_id != company_id:
            raise WorkspaceError(404, "Journal attempt unavailable for this company")
        if (
            digest({k: v for k, v in manifest.items() if k != "receipt_hash"})
            != manifest["receipt_hash"]
        ):
            raise WorkspaceError(409, "Journal attempt receipt failed integrity verification")
        rows = {row["coordinate"]: row for row in manifest["rows"]}
        submitted = {item["coordinate"]: item for item in manifest.get("submitted", [])}
        if (
            len(rows) != len(manifest["rows"])
            or len(submitted) != len(manifest.get("submitted", []))
            or not set(request.coordinates).issubset(rows)
            or not set(submitted).issubset(request.coordinates)
        ):
            raise WorkspaceError(409, "Journal attempt item coverage is inconsistent")
        items = []
        for coordinate in request.coordinates:
            row = rows[coordinate]
            item = {
                "coordinate": coordinate,
                "prepared_state": row["state"],
                "prepared_blockers": row.get("blockers", []),
                "blockers": row.get("blockers", []),
                "proposal_id": None,
                "review": None,
                "publication": None,
            }
            if "proposal" not in row:
                if coordinate in submitted or row["state"] not in ("BLOCKED", "EXCLUDED"):
                    raise WorkspaceError(409, "Journal attempt lacks its exact proposed intent")
                item["state"] = row["state"]
                items.append(item)
                continue
            proposal = ResourceProposal.model_validate(row["proposal"])
            entries = [m for m in proposal.mutations if m.object_type == "JournalEntry"]
            if len(entries) != 1 or (
                entries[0].attributes.get("legal_entity_id") != str(company_id)
                or entries[0].attributes.get("accounting_binding_id") != binding["resource_id"]
            ):
                raise WorkspaceError(409, "Journal item differs from its company or binding")
            kinds = sorted(m.object_type for m in proposal.mutations)
            if (
                proposal.proposal_id != uuid5(request.request_id, coordinate)
                or kinds
                not in (
                    ["JournalEntry", "JournalLine", "JournalLine"],
                    ["JournalEntry", "JournalLine", "JournalLine", "SourceRecord"],
                )
                or row["state"] == "EXCLUDED"
                or (
                    coordinate in submitted
                    and submitted[coordinate]["proposal_id"] != str(proposal.proposal_id)
                )
            ):
                raise WorkspaceError(409, "Journal item proposal identity is inconsistent")
            item["proposal_id"] = str(proposal.proposal_id)
            try:
                detail = read_proposal(proposal.proposal_id)
            except WorkspaceError as exc:
                if exc.status != 404:
                    raise
                item["state"] = (
                    "UNAVAILABLE"
                    if coordinate in submitted
                    else ("BLOCKED" if row["state"] == "BLOCKED" else "NOT_SUBMITTED")
                )
                if coordinate in submitted:
                    item["blockers"] = [
                        {
                            "code": "RETAINED_PROPOSAL_UNAVAILABLE",
                            "required_authority": {
                                "object_type": "ResourceProposal",
                                "proposal_id": str(proposal.proposal_id),
                            },
                        }
                    ]
                items.append(item)
                continue
            if detail.proposal != proposal:
                raise WorkspaceError(409, "Canonical proposal differs from retained item intent")
            item["blockers"] = []
            item["review"] = {
                "decision": detail.decision,
                "submitted_by": detail.submitted_by,
                "reviewed_by": detail.reviewed_by,
                "rationale": detail.review_rationale,
                "recorded_at": detail.recorded_at.isoformat() if detail.recorded_at else None,
            }
            if detail.decision is None:
                item["state"] = "PENDING_REVIEW"
            elif detail.decision == "REJECTED":
                item["state"] = "REJECTED"
                item["blockers"] = [
                    {
                        "code": "JOURNAL_PROPOSAL_REJECTED",
                        "detail": detail.review_rationale,
                        "required_authority": {
                            "object_type": "ResourceProposal",
                            "proposal_id": str(proposal.proposal_id),
                        },
                    }
                ]
            elif detail.decision == "APPROVED":
                try:
                    item["publication"] = published_bundle(
                        proposal, read_versions(proposal.proposal_id)
                    )
                    item["state"] = "PUBLISHED"
                except WorkspaceError as exc:
                    if exc.status != 409:
                        raise
                    item["state"] = "UNAVAILABLE"
                    item["blockers"] = [
                        {
                            "code": "CANONICAL_PUBLICATION_UNAVAILABLE",
                            "detail": exc.detail,
                            "required_authority": {
                                "object_type": "JournalEntry",
                                "proposal_id": str(proposal.proposal_id),
                            },
                        }
                    ]
            else:
                raise WorkspaceError(409, "Unsupported journal review decision")
            items.append(item)
    except (KeyError, ValueError, TypeError) as exc:
        raise WorkspaceError(409, "Retained journal disposition evidence is malformed") from exc
    counts = {
        state: sum(item["state"] == state for item in items)
        for state in sorted({item["state"] for item in items})
    }
    return {
        "contract": "journal-production-dispositions/1",
        "request_id": str(request_id),
        "company_id": str(company_id),
        "invocation_id": str(request.invocation_id),
        "attempt_receipt_hash": manifest["receipt_hash"],
        "source_sha256": source_sha256,
        "binding": binding,
        "source_exclusions": [
            {"coordinate": r["coordinate"], "blockers": r.get("blockers", [])}
            for r in manifest["rows"]
            if r["state"] == "EXCLUDED"
        ],
        "selection_count": len(request.coordinates),
        "items": items,
        "counts": counts,
        "financial_totals": None,
        "current_use_authorized": False,
        "business_effect_authorized": False,
    }


def read(principal, request_id, company_id):
    require_permission(principal, "ontology_read")
    started_at = datetime.now(UTC).isoformat()
    manifest = journal_production_history.history(principal, request_id)
    if manifest is None:
        manifest = journal_production_history.history(principal, request_id, "PREPARED")
    if manifest is None:
        raise WorkspaceError(404, "Journal attempt unavailable in this exact scope")

    def versions(proposal_id):
        with (
            resources.resource_connection(principal) as conn,
            conn.cursor(row_factory=dict_row) as cursor,
        ):
            rows = cursor.execute(
                "SELECT v.*,i.identity_key FROM resource_versions v "
                "JOIN canonical_identities i USING(tenant_id,resource_id) "
                "WHERE v.tenant_id=%s AND v.proposal_id=%s ORDER BY v.resource_id LIMIT 5",
                (principal.scope.tenant_id, proposal_id),
            ).fetchall()
        return [CanonicalResource.model_validate(row).model_dump(mode="json") for row in rows]

    result = compile_dispositions(
        manifest,
        request_id,
        company_id,
        lambda identity: resources.proposal_detail(principal, identity),
        versions,
    )
    result["observed_at"] = datetime.now(UTC).isoformat()
    result["observation_started_at"] = started_at
    result["consistency"] = "PER_ITEM_READ_OBSERVATION"
    result["receipt_hash"] = digest(result)
    return result
