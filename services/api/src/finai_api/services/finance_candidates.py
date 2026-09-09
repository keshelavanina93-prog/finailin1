"""Translate retained candidate files into pending, independently reviewed proposals."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal
from uuid import UUID, uuid5

from finai_api.domain.finance_candidates import CandidateIntakeRequest, CandidateVersionPin
from finai_api.domain.finance_catalog_loader import (
    candidate_construction_bytes,
    load_candidate_construction,
)
from finai_api.domain.ontology_catalog import canonical_id
from finai_api.domain.resources import ResourceMutation, ResourceProposal
from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services import resources, source_documents
from finai_api.services.account_source import profile_accounts
from finai_api.services.workbook_source import read_workbook
from finai_api.services.workspace import WorkspaceError

CONSTRUCTION_IDS = ("g8.candidate.coa-406", "g8.candidate.seg-entities")


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(encoded.encode("utf-8")).hexdigest()


def constructions() -> list[dict[str, Any]]:
    """Read-only inventory; no rows in these files have canonical authority."""
    result = []
    for identity in CONSTRUCTION_IDS:
        candidate = load_candidate_construction(identity)
        result.append(
            {
                "construction_id": identity,
                "status": "CANDIDATE",
                "row_count": len(candidate["mutations"]),
                "construction_content_sha256": _digest(candidate),
                "candidate_file_sha256": sha256(candidate_construction_bytes(identity)).hexdigest(),
                "source_sha256": candidate.get("evidence", {}).get("sha256"),
                "authority": "CANDIDATE_ONLY",
                "rows": candidate["mutations"],
            }
        )
    return result


def _proposal_id(
    principal: Principal,
    request: CandidateIntakeRequest,
    construction: dict[str, Any],
) -> UUID:
    digest = _digest(
        {
            "scope": principal.scope.model_dump(mode="json"),
            "actor_id": principal.actor_id,
            "request": request.model_dump(mode="json"),
            "construction": construction,
            "adapter_version": "finance-candidates/1",
        }
    )
    return uuid5(principal.scope.tenant_id, "finance-candidates:" + digest)


def _accepted(
    principal: Principal,
    pin: CandidateVersionPin,
    kind: str,
    *,
    platform: bool = False,
) -> dict[str, Any]:
    row: dict[str, Any] = resources.get_resource(principal, pin.resource_id)["resource"]
    now = datetime.now(UTC)
    start = datetime.fromisoformat(str(row["valid_from"]).replace("Z", "+00:00"))
    end = row.get("valid_to")
    allowed = {principal.scope.legal_entity_id}
    if platform:
        allowed.add("__PLATFORM__")
    if (
        str(row["resource_id"]) != str(pin.resource_id)
        or str(row["version_id"]) != str(pin.version_id)
        or row["object_type"] != kind
        or row["authority_state"] != "APPROVED"
        or row["access_entity"] not in allowed
        or (row["evidence_class"] == "REFERENCE_TEMPLATE" and not platform)
        or start > now
        or (end and datetime.fromisoformat(str(end).replace("Z", "+00:00")) <= now)
    ):
        raise WorkspaceError(409, f"{kind} selection is stale, unavailable or outside this scope")
    return row


def _sources(
    principal: Principal,
    request: CandidateIntakeRequest,
    construction: dict[str, Any],
) -> tuple[dict[str, Any], bytes, dict[UUID, UUID], UUID]:
    if not request.document_id or not request.evidence:
        raise WorkspaceError(422, "Select a retained document and its reviewed SourceEvidence")
    metadata, content = source_documents.document_bytes(principal, request.document_id)
    source_hash = sha256(content).hexdigest()
    evidence = _accepted(principal, request.evidence, "SourceEvidence")
    if (
        metadata["source_sha256"] != source_hash
        or evidence["attributes"].get("sha256") != source_hash
        or evidence["evidence_class"] != "SOURCE_BOUND"
    ):
        raise WorkspaceError(409, "Retained document bytes do not match reviewed source evidence")
    if request.construction_id == "g8.candidate.coa-406":
        expected = construction["evidence"]["sha256"]
        if source_hash != expected or expected != construction["evidence"]["expected_sha256"]:
            raise WorkspaceError(409, "Retained workbook does not match the pinned CoA source hash")
    elif content != candidate_construction_bytes(request.construction_id):
        raise WorkspaceError(409, "Retained entity assertions differ from the candidate file bytes")
    pins = {request.evidence.resource_id: request.evidence.version_id}
    if request.construction_id == "g8.candidate.coa-406":
        if not request.company or not request.chart:
            raise WorkspaceError(422, "Select a reviewed company and its reviewed chart version")
        _accepted(principal, request.company, "LegalEntity")
        chart = _accepted(principal, request.chart, "LocalChartOfAccounts")
        if chart["attributes"].get("legal_entity_id") != str(request.company.resource_id):
            raise WorkspaceError(409, "The selected chart belongs to a different company")
        pins.update(
            {
                request.company.resource_id: request.company.version_id,
                request.chart.resource_id: request.chart.version_id,
            }
        )
    elif request.company or request.chart:
        raise WorkspaceError(
            422, "Entity assertions do not accept an implicit company/chart binding"
        )
    relation_id = canonical_id(principal.scope.tenant_id, "LinkType", "DERIVED_FROM")
    relation = resources.get_resource(principal, relation_id)["resource"]
    relation_pin = CandidateVersionPin(resource_id=relation_id, version_id=relation["version_id"])
    _accepted(principal, relation_pin, "LinkType", platform=True)
    if "SourceRecord" not in relation["attributes"].get("targets", []):
        raise WorkspaceError(409, "Reviewed DERIVED_FROM link does not support source records")
    sources = relation["attributes"].get("sources", [])
    if "*" not in sources and any(
        row["object_type"] not in sources for row in construction["mutations"]
    ):
        raise WorkspaceError(409, "Reviewed DERIVED_FROM link does not support candidate types")
    pins[relation_id] = relation_pin.version_id
    return metadata, content, pins, relation_id


def _observations(content: bytes) -> list[dict[str, Any]]:
    try:
        book = read_workbook(content)
    except ValueError as exc:
        raise WorkspaceError(422, "Pinned workbook cannot be read: " + str(exc)) from exc
    observations = []
    for sheet in book["sheets"]:
        profile = profile_accounts(sheet)
        if profile:
            name_columns = [
                match[1]
                for address, cell in sheet["cells"].items()
                if (match := re.fullmatch(r"([A-Z]+)(\d+)", address))
                and int(match[2]) == profile["header_row"]
                and str(cell["value"]).strip().casefold() == "наименование"
            ]
            if len(name_columns) != 1:
                raise WorkspaceError(422, "Account name column is missing or ambiguous")
            for account in profile["accounts"]:
                observations.append(
                    {
                        **account,
                        "raw_source_name": str(
                            sheet["cells"]
                            .get(f"{name_columns[0]}{account['source_row']}", {})
                            .get("value", "")
                        ),
                        "findings": [
                            finding["code"]
                            for finding in profile["findings"]
                            if account["coordinate"] in finding["coordinates"]
                        ],
                    }
                )
    return observations


def _account_observation(row: dict[str, Any], observed: list[dict[str, Any]]) -> dict[str, Any]:
    attrs = row["attributes"]
    code = attrs.get("code")
    if row.get("object_type") != "LocalAccount":
        raise WorkspaceError(422, "Account constructions may only contain LocalAccount rows")
    if not isinstance(code, str) or not code.strip():
        raise WorkspaceError(
            422, "Account code is missing; explicit reviewed classification is required"
        )
    if row.get("identity_key") != code:
        raise WorkspaceError(422, "Candidate account identity differs from its observed code")
    matches = [item for item in observed if item["source_row"] == attrs.get("source_row")]
    if len(matches) != 1:
        raise WorkspaceError(422, "Candidate source row is missing or ambiguous across worksheets")
    source = matches[0]
    if (
        source["findings"]
        or source["account_code"] != code
        # The account profiler removes presentation-only edge whitespace when it
        # builds the candidate display name. Preserve the original cell in the
        # retained observation, while comparing the candidate to that normalized
        # source identity.
        or source["raw_source_name"].strip() != str(attrs.get("name", "")).strip()
        or row.get("display_name") != attrs.get("name")
        or [item["source_label"] for item in source["analytics"]]
        != attrs.get("subkonto_labels", [])
    ):
        raise WorkspaceError(
            422, "Candidate labels/code do not match an unambiguous retained source row"
        )
    return source


def _row_mutations(
    principal: Principal,
    request: CandidateIntakeRequest,
    row: dict[str, Any],
    index: int,
    source: dict[str, Any] | None,
    relation_id: UUID,
) -> list[ResourceMutation]:
    assert request.evidence is not None
    evidence_id = request.evidence.resource_id
    account = request.construction_id == "g8.candidate.coa-406"
    coordinate = source["coordinate"] if source else f"candidate/mutations/{index}"
    record_id = uuid5(evidence_id, coordinate)
    key = row["identity_key"]
    if account:
        assert request.chart is not None and source is not None
        identity = uuid5(request.chart.resource_id, key)
        attributes = {
            "chart_id": str(request.chart.resource_id),
            "account_code": key,
            "evidence_id": str(evidence_id),
        }
    else:
        identity = canonical_id(
            principal.scope.tenant_id,
            row["object_type"],
            f"candidate:{principal.scope.legal_entity_id}:{request.construction_id}:{key}",
        )
        attributes = {"evidence_id": str(evidence_id)}
        if row["object_type"] == "EnterpriseGroup":
            attributes["code"] = key
        elif row["object_type"] == "LegalEntity":
            jurisdiction = row["attributes"].get("jurisdiction")
            if jurisdiction:
                attributes["jurisdiction"] = jurisdiction
        else:
            raise WorkspaceError(422, "Entity candidates may only propose groups or legal entities")
    if not isinstance(row.get("display_name"), str) or not 1 <= len(row["display_name"]) <= 200:
        raise WorkspaceError(422, "Candidate display name must have 1-200 characters")

    def mutation(
        identity: UUID,
        kind: str,
        name: str,
        attrs: dict[str, Any],
        evidence_class: Literal["SOURCE_BOUND", "USER_ASSERTED"] = "SOURCE_BOUND",
    ) -> ResourceMutation:
        return ResourceMutation(
            resource_id=identity,
            object_type=kind,
            identity_key="source-chart:" + str(identity),
            display_name=name,
            attributes=attrs,
            valid_from=request.valid_from,
            evidence_class=evidence_class,
        )

    result = [
        mutation(
            record_id,
            "SourceRecord",
            coordinate,
            {
                "evidence_id": str(evidence_id),
                "coordinate": coordinate,
            },
        )
    ]
    if account:
        assert request.chart is not None
        assert source is not None
        result.append(
            mutation(
                uuid5(record_id, "SourceAccountDefinition"),
                "SourceAccountDefinition",
                row["display_name"],
                {
                    "account_code": key,
                    "source_name": source["raw_source_name"],
                    "source_record_id": str(record_id),
                    "chart_id": str(request.chart.resource_id),
                    "evidence_id": str(evidence_id),
                    "definition": {
                        "observed": source,
                        "candidate": row,
                        "construction_id": request.construction_id,
                        "document_id": request.document_id,
                        "financial_mapping": "UNESTABLISHED",
                        "required_dimension_policy": "UNESTABLISHED",
                    },
                },
            )
        )
    evidence_class: Literal["SOURCE_BOUND", "USER_ASSERTED"] = (
        "SOURCE_BOUND" if account else "USER_ASSERTED"
    )
    result.append(
        mutation(identity, row["object_type"], row["display_name"], attributes, evidence_class)
    )
    result.append(
        mutation(
            uuid5(identity, "observed-in:" + str(record_id)),
            "Relationship",
            "Candidate lineage at " + coordinate,
            {
                "relation_id": str(relation_id),
                "source_id": str(identity),
                "target_id": str(record_id),
                "evidence_id": str(evidence_id),
            },
            evidence_class,
        )
    )
    return result


def preview(principal: Principal, request: CandidateIntakeRequest) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    construction = load_candidate_construction(request.construction_id)
    all_rows = construction["mutations"]
    selected = all_rows[request.offset : request.offset + request.limit]
    blockers: list[str] = []
    if not selected:
        blockers.append("No candidate rows in the requested page")
    counts = Counter((row.get("object_type"), row.get("identity_key")) for row in all_rows)
    pins: dict[UUID, UUID] = {}
    observations: list[dict[str, Any]] = []
    relation_id = UUID(int=0)
    try:
        _, content, pins, relation_id = _sources(principal, request, construction)
        if request.construction_id == "g8.candidate.coa-406":
            observations = _observations(content)
    except WorkspaceError as exc:
        blockers.append(exc.detail)
    base_pin_ids = set(pins)
    row_plans = []
    plans: list[ResourceMutation] = []
    for index, row in enumerate(selected, request.offset):
        errors = []
        mutations = []
        if row.get("authority_state") != "CANDIDATE":
            errors.append("Input row must remain CANDIDATE")
        if counts[(row.get("object_type"), row.get("identity_key"))] != 1:
            errors.append("Duplicate candidate identity; resolve the source before submission")
        try:
            if not errors and not blockers:
                source = (
                    _account_observation(row, observations)
                    if request.construction_id == "g8.candidate.coa-406"
                    else None
                )
                mutations = _row_mutations(principal, request, row, index, source, relation_id)
        except WorkspaceError as exc:
            errors.append(exc.detail)
        plans.extend(mutations)
        row_plans.append(
            {
                "index": index,
                "identity_key": row.get("identity_key"),
                "object_type": row.get("object_type"),
                "display_name": row.get("display_name"),
                "original": row,
                "authority": "CANDIDATE_ONLY",
                "epistemic": "OBSERVED" if not errors and not blockers else "UNAVAILABLE",
                "evidence_class": (
                    "SOURCE_BOUND"
                    if request.construction_id == "g8.candidate.coa-406"
                    else "USER_ASSERTED"
                ),
                "blockers": errors,
                "planned_resource_ids": [str(item.resource_id) for item in mutations],
            }
        )
    existing = (
        resources.current_resources(principal, [item.resource_id for item in plans])
        if plans
        else {}
    )
    row_dependencies = {
        resource_id: set(row["planned_resource_ids"])
        for row in row_plans
        for resource_id in row["planned_resource_ids"]
    }
    mutations = []
    for item in plans:
        previous = existing.get(str(item.resource_id))
        if previous:
            if (
                previous["access_entity"] != principal.scope.legal_entity_id
                or previous["authority_state"] != "APPROVED"
                or previous["object_type"] != item.object_type
                or previous["attributes"] != item.attributes
                or previous["display_name"] != item.display_name
                or previous["evidence_class"] != item.evidence_class
                or datetime.fromisoformat(str(previous["valid_from"]).replace("Z", "+00:00"))
                > datetime.now(UTC)
                or (
                    previous.get("valid_to")
                    and datetime.fromisoformat(str(previous["valid_to"]).replace("Z", "+00:00"))
                    <= datetime.now(UTC)
                )
            ):
                blockers.append(
                    f"Existing canonical identity conflicts with candidate: {item.resource_id}"
                )
            else:
                pins[item.resource_id] = UUID(previous["version_id"])
        else:
            mutations.append(item)
    if any(row["blockers"] for row in row_plans):
        blockers.append("One or more candidate rows require resolution")
    proposal_id = _proposal_id(principal, request, construction)
    proposal = None
    if mutations and not blockers:
        proposal = ResourceProposal(
            proposal_id=proposal_id,
            title="Review finance candidate account definitions"
            if request.chart
            else "Review retained entity assertions",
            rationale=request.rationale
            + " Retained candidate assertions require independent review; "
            "no ownership, functional currency, dimension policy or financial mapping is inferred.",
            access_entity=principal.scope.legal_entity_id,
            mutations=mutations,
            source_versions={
                item.resource_id: {
                    key: value
                    for key, value in pins.items()
                    if key != item.resource_id
                    and (key in base_pin_ids or str(key) in row_dependencies[str(item.resource_id)])
                }
                for item in mutations
            },
        )
    return {
        "construction_id": request.construction_id,
        "construction_content_sha256": _digest(construction),
        "scope": principal.scope.model_dump(mode="json"),
        "total_rows": len(all_rows),
        "offset": request.offset,
        "limit": request.limit,
        "next_offset": request.offset + len(selected)
        if request.offset + len(selected) < len(all_rows)
        else None,
        "rows": row_plans,
        "blockers": list(dict.fromkeys(blockers)),
        "proposal_id": str(proposal_id),
        "proposal": proposal.model_dump(mode="json") if proposal else None,
        "mutation_count": len(mutations),
        "reused_count": len(plans) - len(mutations),
        "can_submit": proposal is not None,
        "authority": "CANDIDATE_ONLY",
        "review_required": True,
    }


def submit(principal: Principal, request: CandidateIntakeRequest) -> dict[str, Any]:
    require_permission(principal, "ontology_read")
    require_permission(principal, "ontology_propose")
    construction = load_candidate_construction(request.construction_id)
    proposal_id = _proposal_id(principal, request, construction)
    try:
        prior = resources.proposal_detail(principal, proposal_id)
    except WorkspaceError as exc:
        if exc.status != 404:
            raise
    else:
        if (
            prior.submitted_by != principal.actor_id
            or prior.proposal.access_entity != principal.scope.legal_entity_id
        ):
            raise WorkspaceError(
                409, "Candidate proposal belongs to a different submitter or scope"
            )
        return {
            "proposal_id": str(proposal_id),
            "decision": prior.decision,
            "review_required": prior.decision is None,
            "created": False,
            "proposal": prior.proposal.model_dump(mode="json"),
        }
    plan = preview(principal, request)
    if not plan["can_submit"]:
        raise WorkspaceError(
            409, "; ".join(plan["blockers"]) or "Candidate page is already present"
        )
    proposal = ResourceProposal.model_validate(plan["proposal"])
    detail = resources.propose(principal, proposal)
    return {
        "proposal_id": str(proposal_id),
        "decision": detail.decision,
        "review_required": detail.decision is None,
        "created": True,
        "proposal": proposal.model_dump(mode="json"),
    }
