"""Resolve exact retained financial sections for a new report, without execution."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from psycopg.rows import dict_row

from finai_api.domain.semantic_analysis import Pin, ProjectionRequest
from finai_api.security import require_permission
from finai_api.services import company_context, function_execution, semantic_analysis
from finai_api.services.resource_lifecycle import require_available_version
from finai_api.services.resources import resource_connection
from finai_api.services.semantic_analysis_support import digest, pin
from finai_api.services.upstream_authority import upstream_authority
from finai_api.services.workspace import WorkspaceError

if TYPE_CHECKING:
    from finai_api.domain.retained_reports import ReportSectionReference
    from finai_api.domain.review import Principal

POSTED = "accounting.retained-posted-movements/v1"
ACCEPTED = "finance.accepted-journal-movements/v1"


def require(condition: Any, detail: str) -> None:
    if not condition:
        raise WorkspaceError(409, detail)


def builder(history: dict, plan: dict):
    implementation = plan["implementation"]["implementation_id"]
    if implementation not in (POSTED, ACCEPTED):
        raise WorkspaceError(422, "Report section requires a supported financial result")
    # A retained execution keeps its original package hash. Composing is not rerunning it.
    function_execution.manifest(implementation)
    if implementation == ACCEPTED:
        from finai_api.services.semantic_analysis_accepted_movements import build
    elif history["output"].get("entity_movement_review") is not None:
        from finai_api.services.semantic_analysis_movements import build
    else:
        from finai_api.services.semantic_analysis_posted import build
    return build


def collect_pins(value: Any, found: dict[tuple[UUID, UUID], Pin]) -> None:
    if isinstance(value, dict):
        if {"resource_id", "version_id", "content_hash"}.issubset(value):
            reference = Pin.model_validate(
                {k: value[k] for k in ("resource_id", "version_id", "content_hash")}
            )
            key = (reference.resource_id, reference.version_id)
            require(key not in found or found[key] == reference, "Report evidence pins disagree")
            found[key] = reference
        for child in value.values():
            collect_pins(child, found)
    elif isinstance(value, list):
        for child in value:
            collect_pins(child, found)


def authority(principal: Principal, roots: list[Pin]) -> dict:
    require(len(roots) <= 1000, "Report authority exceeds the supported resource bound")
    upstream: dict[tuple[str, str], dict[str, Any]] = {}
    with resource_connection(principal) as conn, conn.cursor(row_factory=dict_row) as cursor:
        conn.execute(
            "SELECT pg_advisory_xact_lock_shared(hashtextextended(%s,0))",
            (f"canonical:{principal.scope.tenant_id}",),
        )
        for reference in roots:
            current = require_available_version(
                conn, principal, reference.resource_id, reference.version_id
            )
            require(pin(current) == reference, "Report input differs from its retained hash")
            for item in upstream_authority(
                cursor,
                principal.scope.tenant_id,
                reference.version_id,
                allow_historical_provenance=True,
            ):
                key = (item["resource_id"], item["version_id"])
                previous = upstream.get(key)
                if previous is not None:
                    require(
                        {k: v for k, v in previous.items() if k != "lineage_use"}
                        == {k: v for k, v in item.items() if k != "lineage_use"},
                        "Report authority changed during resolution",
                    )
                if previous is None or item.get("lineage_use") == "ACTIVE":
                    upstream[key] = item
                require(len(upstream) <= 1000, "Report upstream authority exceeds its bound")
    return {
        "roots": [r.model_dump(mode="json") for r in roots],
        "upstream": [upstream[key] for key in sorted(upstream)],
    }


def resolve_section(principal: Principal, company_id: UUID, section: ReportSectionReference):
    history, plan, resolver = semantic_analysis.load(principal, section.invocation_id)
    require(history["receipt_hash"] == section.receipt_hash, "Report invocation receipt changed")
    build = builder(history, plan)
    with resolver.read_session():
        descriptor, rows, contributors = build(history, plan, resolver, company_id)
    require(
        descriptor.company.resource_id == company_id
        and descriptor.receipt_hash == section.receipt_hash
        and descriptor.invocation_id == section.invocation_id,
        "Report section differs from its retained company or invocation",
    )
    require(
        len(rows) <= 1000
        and len(contributors) == len(rows)
        and {row.key for row in rows} == set(contributors),
        "Report result exceeds its bound or has incomplete contributors",
    )
    revision = digest(
        {
            "descriptor": descriptor.model_dump(mode="json"),
            "rows": [row.model_dump(mode="json") for row in rows],
        }
    )
    require(revision == section.descriptor_sha256, "Report descriptor revision changed")
    fields = {field.key: field for field in descriptor.fields}
    if (
        not 1 <= len(section.columns) <= 32
        or len(set(section.columns)) != len(section.columns)
        or any(key not in fields for key in section.columns)
    ):
        raise WorkspaceError(422, "Report columns must select distinct retained fields")
    for key in ("valid_at", "known_at"):
        value = getattr(descriptor, key)
        stamp = datetime.fromisoformat(value)
        require(
            stamp.tzinfo is not None and stamp.utcoffset() is not None,
            "Report source clocks require timezone information",
        )
        require(value == history["output"]["query"][key], "Report source clock changed")
    currencies = {field.unit_reference for field in descriptor.fields if field.unit_reference}
    require(len(currencies) == 1, "Report financial section requires one exact currency")
    currency = next(iter(currencies))
    with resolver.read_session():
        currency_row = resolver.version(currency.model_dump(mode="json"))
    require(currency_row["object_type"] == "Currency", "Report currency reference is invalid")
    projection = semantic_analysis.project(
        principal,
        ProjectionRequest(
            invocation_id=section.invocation_id,
            company_id=company_id,
            descriptor_sha256=section.descriptor_sha256,
            filters=section.filters,
            group_by=section.group_by,
        ),
    )
    require(
        projection.descriptor == descriptor and projection.total_rows == len(rows),
        "Report projection changed during resolution",
    )
    originals = {row.key: row for row in rows}
    selected = {}
    for row in projection.rows:
        require(originals.get(row.key) == row, "Report row differs from retained result")
        evidence = contributors[row.key]
        require(len(evidence) == row.contributor_count, "Report row evidence is incomplete")
        selected[row.key] = [item.model_dump(mode="json") for item in evidence]
    roots: dict[tuple[UUID, UUID], Pin] = {}
    collect_pins([plan["function"], *plan["static_dependencies"]], roots)
    collect_pins(projection.model_dump(mode="json"), roots)
    collect_pins(list(selected.values()), roots)
    if plan["implementation"]["implementation_id"] == ACCEPTED:
        source_id = UUID(plan["accepted_movements"]["source_invocation_id"])
        source_history, source_plan, _ = semantic_analysis.load(principal, source_id)
        require(
            source_plan["implementation"]["implementation_id"] == POSTED,
            "Accepted report section requires its retained posted source",
        )
        require(
            source_history["receipt_hash"]
            == plan["accepted_movements"]["source_invocation_receipt_hash"],
            "Report source receipt changed",
        )
        collect_pins([source_plan["function"], *source_plan["static_dependencies"]], roots)
    observed = authority(
        principal, sorted(roots.values(), key=lambda r: (str(r.resource_id), str(r.version_id)))
    )
    return {
        "reference": section.model_dump(mode="json"),
        "projection": projection.model_dump(mode="json"),
        "contributors": selected,
        "authority_observation": observed,
        "current_use_authorized": False,
        "business_effect_authorized": False,
    }


def resolve(
    principal: Principal, company_id: UUID, sections: list[ReportSectionReference]
) -> list[dict]:
    require_permission(principal, "ontology_read")
    if str(company_id) != str(principal.scope.legal_entity_id):
        raise WorkspaceError(404, "Report company is unavailable in this access scope")
    if not 1 <= len(sections) <= 8 or len({s.section_id for s in sections}) != len(sections):
        raise WorkspaceError(422, "Report requires one to eight distinct sections")
    context = company_context.resolve(principal, company_id)
    if not any(
        item["company"]["resource_id"] == str(company_id)
        for item in context["company_directory"]["companies"]
    ):
        raise WorkspaceError(404, "Report requires an established company")
    try:
        return [resolve_section(principal, company_id, section) for section in sections]
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkspaceError(409, "Report retained evidence is incomplete or inconsistent") from exc
