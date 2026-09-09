"""Retained-source discovery for diagnostics; classification never grants authority."""

import json
from calendar import monthrange
from datetime import date, datetime
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services.resources import resource_connection
from finai_api.storage import connection

# These are parser profiles implemented by source_accounting_context.observe.
# Report names, filenames and user-entered descriptions never enter this map.
PROFILE_CLASSES = {
    "1c_tb": "TRIAL_BALANCE",
    "1c_journal": "GL_OR_JOURNAL",
    "seg_expense_base": "GL_OR_JOURNAL",
}
MAX_UNASSIGNED = 100
MAX_PENDING = 100


def _pin(row: dict, field: str, versions: dict[str, dict], kind: str) -> dict | None:
    identity = str(row.get("attributes", {}).get(field, ""))
    version = row.get("_pins", {}).get("FIELD:" + field)
    if not version:
        return None
    selected = versions.get(str(version))
    if (
        selected
        and selected.get("object_type") == kind
        and str(selected.get("resource_id")) == identity
    ):
        return selected
    return None


def _period_reason(observation: dict, period: str) -> tuple[str, str]:
    """Presence in a date extent is not a claim of complete monthly coverage."""
    periods = observation.get("observed_periods", [])
    start, end = observation.get("observed_from"), observation.get("observed_through")
    if periods:
        if period not in periods:
            return (
                "STALE_OR_INCOMPATIBLE",
                "Observed source periods do not match the target period.",
            )
        return "UNBOUND", "Observed period matches; complete target coverage remains unestablished."
    if start and end:
        try:
            first, last = date.fromisoformat(str(start)[:10]), date.fromisoformat(str(end)[:10])
            year, month = map(int, period.split("-"))
            wanted_first, wanted_last = (
                date(year, month, 1),
                date(year, month, monthrange(year, month)[1]),
            )
        except (TypeError, ValueError):
            return "UNBOUND", "Source period cannot be established from the retained observation."
        if first > last:
            return "STALE_OR_INCOMPATIBLE", "The observed source interval is inconsistent."
        if last < wanted_first or first > wanted_last:
            return (
                "STALE_OR_INCOMPATIBLE",
                "Observed source interval does not overlap the target period.",
            )
        if first > wanted_first or last < wanted_last:
            return "UNBOUND", "Observed dates cover only part of the requested period."
        return (
            "UNBOUND",
            "Observed dates overlap the target; complete target coverage remains unestablished.",
        )
    return "UNBOUND", "Reporting dates have not been established from source evidence."


def source_candidates(
    requirement: dict,
    rows: list[dict],
    company_id: str,
    period: str,
    *,
    retained_sources: list[dict] | None = None,
) -> list[dict]:
    """Inspect already authorized snapshot rows and metadata without reading document bytes.

    The caller supplies its temporal/authority-filtered graph. Every returned match
    remains a candidate; approved scope nouns or receipt bindings cannot fulfill the
    target's material fact contract through this helper.
    """
    wanted = set(requirement.get("source_classes", []))
    if not wanted:
        return []
    versions = {str(row["version_id"]): row for row in rows if row.get("version_id")}
    result: list[dict[str, Any]] = []
    assigned: set[tuple[str, str]] = set()
    for row in sorted(
        rows, key=lambda item: (str(item.get("resource_id", "")), str(item.get("version_id", "")))
    ):
        if row.get("object_type") != "SourceAccountingScope":
            continue
        attrs = row.get("attributes", {})
        source_class = PROFILE_CLASSES.get(attrs.get("source_profile"))
        if source_class not in wanted:
            continue
        state, period_reason = _period_reason(attrs, period)
        reasons = [period_reason]
        declared_company = attrs.get("legal_entity_id")
        if declared_company and str(declared_company) != str(company_id):
            state = "STALE_OR_INCOMPATIBLE"
            reasons.append("The retained scope is bound to a different canonical company.")
        elif not declared_company:
            reasons.append("The source organization has no reviewed canonical company binding.")
        authority = row.get("authority_state")
        if authority != "APPROVED":
            if state != "STALE_OR_INCOMPATIBLE":
                state = "REVIEW_REQUIRED"
            reasons.append("This source scope is awaiting approval or has withdrawn authority.")
        lifecycle = row.get("lifecycle") or {}
        if authority == "REVOKED" or lifecycle.get("target_state") in {"REVOKED", "SUPERSEDED"}:
            state = "STALE_OR_INCOMPATIBLE"
            reasons.append("The retained source scope no longer carries available authority.")
        if row.get("evidence_class") != "SOURCE_BOUND":
            reasons.append("This scope has no source-bound evidence authority.")
        reasons.append(
            "A recognized source class is not an approved target input; review the "
            "accounting/measurement binding and exact source-to-target grain."
        )
        record = _pin(row, "source_record_id", versions, "SourceRecord")
        evidence = _pin(row, "evidence_id", versions, "SourceEvidence")
        candidate = {
            "resource_id": str(row["resource_id"]),
            "version_id": str(row["version_id"]),
            "document_id": attrs.get("document_id"),
            "worksheet": attrs.get("worksheet"),
            "source_class": source_class,
            "source_profile": attrs.get("source_profile"),
            "observed_from": attrs.get("observed_from"),
            "observed_through": attrs.get("observed_through"),
            "date_basis": attrs.get("date_basis"),
            "coverage_state": attrs.get("coverage_state", "UNESTABLISHED"),
            "observed_company_id": declared_company,
            "company_binding_state": "REVIEWED_SCOPE"
            if (
                declared_company == company_id
                and authority == "APPROVED"
                and row.get("evidence_class") == "SOURCE_BOUND"
            )
            else "UNBOUND_OR_MISMATCHED",
            "state": state,
            "reason": " ".join(reasons),
        }
        if record:
            candidate["source_coordinate"] = record["attributes"].get("coordinate")
        if evidence:
            candidate["source_sha256"] = evidence["attributes"].get("sha256")
        result.append(candidate)
        assigned.add((str(attrs.get("document_id", "")), str(attrs.get("worksheet", ""))))

    for retained in retained_sources or []:
        for observation in retained.get("observations", []):
            if observation.get("source_class") not in wanted:
                continue
            if (
                str(retained.get("document_id", "")),
                str(observation.get("worksheet", "")),
            ) in assigned:
                continue
            state, reason = _period_reason(observation, period)
            if retained.get("source_use") not in {None, "ACTUAL_INPUT"}:
                reason += " This source is retained for reference use, not actual accounting input."
            result.append(
                {
                    **observation,
                    "document_id": retained["document_id"],
                    "filename": retained.get("filename"),
                    "source_sha256": retained.get("source_sha256"),
                    "company_binding_state": "UNBOUND",
                    "coverage_state": "UNESTABLISHED",
                    "state": state,
                    "reason": reason
                    + " The retained upload is not bound to the selected canonical "
                    "company or this target's approved input contract. Observed company labels are "
                    "source text, not canonical identity.",
                }
            )
    return result


def _retained_metadata(row: dict) -> dict:
    profile = row.get("source_profile") or {}
    observed = row.get("observed_bindings") or {}
    observations = []
    if row.get("source_class") == "TRIAL_BALANCE":
        observed_period = profile.get("observed_period")
        observations.append(
            {
                "source_class": "TRIAL_BALANCE",
                "observed_periods": [observed_period] if observed_period else [],
                "observed_company_labels": [profile["observed_company_label"]]
                if profile.get("observed_company_label")
                else [],
                "source_coordinate": observed.get("period_coordinate"),
            }
        )
    for sheet in profile.get("sheets", []):
        # Stored classifier output is structural evidence, still not binding authority.
        observations.append(
            {
                "worksheet": sheet.get("sheet"),
                "source_class": sheet.get("source_type"),
                "observed_periods": sheet.get("periods", []),
                "observed_company_labels": sheet.get("company_labels", []),
                "observed_grain": sheet.get("grain"),
            }
        )
    return {
        "document_id": row["document_id"],
        "filename": row.get("filename"),
        "source_sha256": row["source_sha256"],
        "retained_at": row["retained_at"].isoformat(),
        "source_use": row.get("source_use") or profile.get("source_use"),
        "source_class": row.get("source_class") or "UNCLASSIFIED",
        "company_binding_state": "UNBOUND",
        "state": "UNBOUND",
        "observations": observations,
        "reason": "Retained source has no selected canonical source-scope association. "
        "Review its observed company, period, schema and bindings; filename is not evidence.",
    }


def load_unassigned(
    principal: Principal,
    known_at: datetime,
    assigned_document_ids: set[str],
) -> dict[str, Any]:
    """List bounded uploads from the caller's ORIGINAL exact scope and knowledge time.

    No selected-company or report-period substitution is allowed here. Only retained
    metadata is read; this performs no parser execution or evidence object download.
    """
    require_permission(principal, "ontology_read")
    scope = principal.scope.model_dump(mode="json")
    params = {
        "tenant": principal.scope.tenant_id,
        "scope": Jsonb(scope),
        "known": known_at,
        "assigned": sorted(assigned_document_ids),
        "limit": MAX_UNASSIGNED + 1,
    }
    with (
        connection(principal.scope, repeatable_read=True) as conn,
        conn.cursor(row_factory=dict_row) as cur,
    ):
        conn.execute("SELECT set_config('finai.exact_scope',%s,true)", (json.dumps(scope),))
        conn.execute("SELECT set_config('statement_timeout','10000',true)")
        documents = cur.execute(
            "SELECT document_id,filename,source_sha256,created_at AS retained_at "
            "FROM source_documents WHERE tenant_id=%(tenant)s AND exact_scope=%(scope)s "
            "AND created_at<=%(known)s AND NOT(document_id=ANY(%(assigned)s::text[])) "
            "ORDER BY created_at DESC,document_id LIMIT %(limit)s",
            params,
        ).fetchall()
        receipts = cur.execute(
            "SELECT receipt_id AS document_id,request->>'filename' AS filename,"
            "source_sha256,ingested_at AS retained_at,receipt->>'source_class' AS source_class,"
            "receipt->'source_profile' AS source_profile,"
            "receipt->'observed_bindings' AS observed_bindings,"
            "request->>'source_use' AS source_use "
            "FROM hydration_runs WHERE tenant_id=%(tenant)s AND exact_scope=%(scope)s "
            "AND ingested_at<=%(known)s AND NOT(receipt_id=ANY(%(assigned)s::text[])) "
            "ORDER BY ingested_at DESC,receipt_id LIMIT %(limit)s",
            params,
        ).fetchall()
    return {
        "items": [
            _retained_metadata(row)
            for row in [*documents[:MAX_UNASSIGNED], *receipts[:MAX_UNASSIGNED]]
        ],
        "complete": len(documents) <= MAX_UNASSIGNED and len(receipts) <= MAX_UNASSIGNED,
        "scope": scope,
        "known_at": known_at.isoformat(),
        "classification_policy": "RETAINED_PARSER_METADATA_ONLY_NO_FILENAME_INFERENCE",
    }


def _declared_company(item: dict, company_id: str) -> bool:
    attrs = item.get("attributes", {})
    companies = [str(attrs[key]) for key in ("legal_entity_id", "company_id") if attrs.get(key)]
    if companies:
        return all(value == company_id for value in companies)
    return item.get("object_type") == "LegalEntity" and str(item.get("resource_id")) == company_id


def pending_candidates(
    proposals: list[dict],
    company_id: str,
    known_at: datetime,
    required_resource_types: set[str],
    scope_versions: list[dict],
    *,
    access_entity: str | None = None,
) -> dict[str, Any]:
    """Project authorized proposals into candidate references, never canonical versions."""
    scopes = {str(row["version_id"]): row for row in scope_versions}
    items = []
    for proposal in proposals:
        allowed_access = {access_entity, "__TENANT__"}
        if access_entity is not None and proposal.get("access_entity") not in allowed_access:
            continue
        if proposal["created_at"] > known_at:
            continue
        decided = proposal.get("decision_recorded_at")
        if proposal.get("decision") and decided is not None and decided <= known_at:
            continue
        mutations = [
            item
            for item in proposal.get("mutations", [])
            if access_entity is None
            or (item.get("access_entity") or proposal.get("access_entity")) in allowed_access
        ]
        local = {str(item.get("resource_id")): item for item in mutations}
        for item in mutations:
            kind, identity = item.get("object_type"), str(item.get("resource_id", ""))
            if kind not in required_resource_types or not identity:
                continue
            attrs = item.get("attributes", {})
            company_match = _declared_company(item, company_id)
            # Conflicting direct company fields must never be rescued by an indirect scope.
            declared = any(attrs.get(key) for key in ("legal_entity_id", "company_id"))
            scope_id = str(attrs.get("scope_id", ""))
            if not company_match and not declared and scope_id:
                scope = local.get(scope_id)
                if scope is not None:
                    company_match = scope.get(
                        "object_type"
                    ) == "SourceAccountingScope" and _declared_company(scope, company_id)
                else:
                    for pin in (proposal.get("dependencies") or {}).get(identity, []):
                        if str(pin.get("resource_id")) != scope_id or pin.get("relation") not in {
                            "FIELD:scope_id",
                            "ACCOUNTING_SOURCE_SCOPE",
                        }:
                            continue
                        exact = scopes.get(str(pin.get("version_id")))
                        if exact and str(exact.get("resource_id")) == scope_id:
                            company_match = exact.get(
                                "object_type"
                            ) == "SourceAccountingScope" and _declared_company(exact, company_id)
                            if company_match:
                                break
            if not company_match:
                continue
            candidate = {
                "proposal_id": str(proposal["proposal_id"]),
                "title": f"Review pending {kind}",
                "resource_id": identity,
                "object_type": kind,
                "company_id": company_id,
                "state": "REVIEW_REQUIRED",
                "submitted_at": proposal["created_at"].isoformat(),
                "candidate_authority_state": item.get("authority_state", "APPROVED"),
                "reason": "An explicitly company-associated proposal is awaiting a decision at "
                "the selected knowledge time. It has no published canonical version and cannot "
                "satisfy the target until reviewed and rechecked.",
            }
            for field in (
                "document_id",
                "worksheet",
                "source_profile",
                "source_record_id",
                "scope_id",
                "evidence_id",
                "period_id",
                "currency_id",
            ):
                if attrs.get(field) is not None:
                    candidate[field] = attrs[field]
            items.append(candidate)
    return {"items": items[:MAX_PENDING], "complete": len(items) <= MAX_PENDING}


def load_pending(
    principal: Principal,
    company_id: str,
    known_at: datetime,
    required_resource_types: set[str],
) -> dict[str, Any]:
    """Read pending proposals using original RLS credentials, never selected-company credentials.

    The caller must already have authorized the selected company. Only explicitly
    grounded mutation references leave this helper, even for a mixed tenant proposal.
    A decision recorded after known_at must not erase a historical pending proposal.
    """
    require_permission(principal, "ontology_read")
    if not required_resource_types:
        return {"items": [], "complete": True}
    params = {
        "tenant": principal.scope.tenant_id,
        "access": principal.scope.legal_entity_id,
        "company": str(company_id),
        "known": known_at,
        "kinds": sorted(required_resource_types),
        "limit": MAX_PENDING + 1,
    }
    with (
        resource_connection(principal, repeatable_read=True) as conn,
        conn.cursor(row_factory=dict_row) as cur,
    ):
        # Proposal discovery is a bounded, read-only metadata scan.  On the
        # production tenant the RLS-protected recency page can take just over
        # ten seconds while it evaluates the exact-scope policy; keep the
        # result bounded, but allow enough time to return an explicit
        # incomplete diagnostic instead of surfacing a storage 503.
        cur.execute(
            "SELECT set_config('statement_timeout','30000',true), "
            "set_config('enable_sort','off',true)"
        )
        proposals = cur.execute(
            "WITH page AS MATERIALIZED ("
            "SELECT p.proposal_id,p.created_at,p.access_entity,p.payload "
            "FROM resource_proposals p WHERE p.tenant_id=%(tenant)s "
            "AND p.access_entity IN (%(access)s,'__TENANT__') AND p.created_at<=%(known)s "
            "ORDER BY p.created_at DESC,p.proposal_id LIMIT %(limit)s) "
            "SELECT p.proposal_id,p.created_at,p.access_entity,"
            "p.payload->'request'->'mutations' AS mutations,"
            "p.payload->'validation'->'dependencies' AS dependencies "
            "FROM page p ORDER BY p.created_at DESC,p.proposal_id",
            params,
        ).fetchall()
        page = proposals[:MAX_PENDING]
        # Bound policy work before checking pending state. Filtering pending inside the
        # base scan exhausts accepted history and repeatedly evaluates expensive RLS.
        decisions = cur.execute(
            "SELECT proposal_id FROM resource_decisions WHERE tenant_id=%(tenant)s "
            "AND proposal_id=ANY(%(ids)s::uuid[]) AND recorded_at<=%(known)s",
            {**params, "ids": [p["proposal_id"] for p in page]},
        ).fetchall()
        decided = {str(d["proposal_id"]) for d in decisions}
        page = [p for p in page if str(p["proposal_id"]) not in decided]
        scope_pins = {
            str(pin["version_id"])
            for proposal in page
            for mutation in proposal.get("mutations", [])
            if mutation.get("object_type") in required_resource_types
            and mutation.get("attributes", {}).get("scope_id")
            for pin in (proposal.get("dependencies") or {}).get(str(mutation["resource_id"]), [])
            if pin.get("version_id")
            and str(pin.get("resource_id")) == str(mutation["attributes"]["scope_id"])
            and pin.get("relation") in {"FIELD:scope_id", "ACCOUNTING_SOURCE_SCOPE"}
        }
        scopes = []
        if scope_pins:
            scopes = cur.execute(
                "SELECT resource_id,version_id,object_type,attributes FROM resource_versions "
                "WHERE tenant_id=%(tenant)s AND access_entity IN (%(access)s,'__TENANT__') "
                "AND object_type='SourceAccountingScope' AND system_from<=%(known)s "
                "AND attributes->>'legal_entity_id'=%(company)s "
                "AND version_id=ANY(%(pins)s::uuid[])",
                {**params, "pins": sorted(scope_pins)},
            ).fetchall()
    result = pending_candidates(
        page,
        str(company_id),
        known_at,
        required_resource_types,
        scopes,
        access_entity=principal.scope.legal_entity_id,
    )
    result["complete"] = result["complete"] and len(proposals) <= MAX_PENDING
    return result
