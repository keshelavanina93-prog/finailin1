"""Explain target blockers from declared contracts and exact canonical version pins.

This is an advisory read: no proposal, ingestion, calculation receipt or authority is
published. An absent edge can only be diagnosed from an explicit requirement contract;
an ontology type name alone never proves that its business engine exists.
"""

import json
import re
from collections import Counter, deque
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

from finai_api.domain.enterprise_diagnostics import DiagnosticRequest
from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services.resources import resource_connection
from finai_api.services.workspace import WorkspaceError

VERSION = "enterprise-diagnostics/1"
MAX_NODES = 1000
MAX_EDGES = 5000
MAX_DEPTH = 16
MAX_CANDIDATES = 2000
SHARED_TYPES = {
    "SchemaDefinition",
    "SemanticContract",
    "LinkType",
    "InterfaceDefinition",
    "TypeGroup",
    "Currency",
    "DimensionDefinition",
    "DerivedProperty",
    "FactContract",
    "BindingDefinition",
    "ObjectSetDefinition",
    "FiscalCalendar",
    "FiscalPeriod",
}
ENGINE_TYPES = {
    "FunctionDefinition",
    "TransformationDefinition",
    "FactContract",
    "MetricDefinition",
}
STATES = (
    "UNKNOWN_TARGET",
    "ENGINE_NOT_IMPLEMENTED",
    "STALE_OR_INCOMPATIBLE",
    "UNBOUND",
    "REVIEW_REQUIRED",
    "MISSING_EVIDENCE",
    "READY",
)


def catalog() -> dict[str, Any]:
    from finai_api.services.enterprise_diagnostics_catalog import catalog as target_catalog

    return target_catalog()


def _contracts() -> tuple[dict, dict]:
    from finai_api.services.enterprise_diagnostics_catalog import REQUIREMENTS, TARGETS

    return TARGETS, REQUIREMENTS


def _normal(value: str) -> str:
    return " ".join(re.findall(r"\w+", value.casefold()))


def resolve_target(value: str, targets: dict) -> dict | None:
    if value in targets:
        return targets[value]
    normalized = _normal(value)
    matches = []
    for target in targets.values():
        names = [_normal(n) for n in [target["id"], target["label"], *target.get("aliases", [])]]
        if any(
            name == normalized or (len(name) >= 5 and f" {name} " in f" {normalized} ")
            for name in names
        ):
            matches.append(target)
    return matches[0] if len(matches) == 1 else None


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _json(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str, sort_keys=True))


def _action(kind: str, label: str, **refs: Any) -> dict:
    return {"kind": kind, "label": label, **{k: v for k, v in refs.items() if v is not None}}


def _finding(identity: str, label: str, state: str, reason: str, **extra: Any) -> dict:
    actions = extra.pop("actions", None)
    if actions is None:
        if state == "ENGINE_NOT_IMPLEMENTED":
            actions = [_action("IMPLEMENT_ENGINE", "Inspect the missing computation contract")]
        elif state in {"UNBOUND", "REVIEW_REQUIRED"}:
            actions = [_action("REVIEW_BINDING", "Review source and dependency bindings")]
        elif state == "MISSING_EVIDENCE":
            actions = [_action("UPLOAD_SOURCE", "Upload source evidence")]
        else:
            actions = [_action("RECHECK", "Recheck this target and context")]
    return {
        "id": identity,
        "label": label,
        "state": state,
        "reason": reason,
        "actions": actions,
        **extra,
    }


def _pinned(row: dict, field: str, versions: dict[str, dict]) -> dict | None:
    pin = row.get("_pins", {}).get("FIELD:" + field)
    target = versions.get(pin) if pin else None
    if target and str(target["resource_id"]) == str(row.get("attributes", {}).get(field)):
        return target
    return None


def _company_match(
    row: dict, company_id: str, versions: dict[str, dict], seen: frozenset[str] = frozenset()
) -> bool:
    """Use explicit company fields and exact scope pins, never labels or filename inference."""
    attrs = row.get("attributes", {})
    declared = [str(attrs[k]) for k in ("legal_entity_id", "company_id") if attrs.get(k)]
    if declared:
        return all(value == company_id for value in declared)
    if row["object_type"] == "LegalEntity":
        return str(row["resource_id"]) == company_id
    version = str(row["version_id"])
    if version in seen or len(seen) >= MAX_DEPTH:
        return False
    owner_fields = [
        field
        for field in ("scope_id", "ledger_id", "journal_id", "entry_id", "chart_id", "book_id")
        if attrs.get(field)
    ]
    if owner_fields:
        return all(
            (target := _pinned(row, field, versions)) is not None
            and _company_match(target, company_id, versions, seen | {version})
            for field in owner_fields
        )
    return str(row.get("access_entity")) == company_id


def _in_scope(row: dict, company_id: str, versions: dict[str, dict], access_entity: str) -> bool:
    if str(row.get("access_entity")) not in {
        access_entity,
        company_id,
        "__TENANT__",
        "__PLATFORM__",
    }:
        return False
    attrs = row.get("attributes", {})
    if (
        attrs.get("legal_entity_id")
        or attrs.get("company_id")
        or row["object_type"] == "LegalEntity"
    ):
        return _company_match(row, company_id, versions)
    if _company_match(row, company_id, versions):
        return True
    return row["object_type"] in SHARED_TYPES


def _period_matches(row: dict, period: str, versions: dict[str, dict]) -> bool:
    attrs = row.get("attributes", {})
    if attrs.get("period"):
        return attrs["period"] == period
    start, end = attrs.get("observed_from"), attrs.get("observed_through")
    if start and end:
        from calendar import monthrange

        year, month = map(int, period.split("-"))
        return str(start)[:10] <= f"{period}-01" and str(end)[:10] >= (
            f"{period}-{monthrange(year, month)[1]:02}"
        )
    for key in ("date", "posting_date", "observation_date", "as_of", "stock_date"):
        if attrs.get(key):
            return str(attrs[key])[:7] == period
    if attrs.get("period_id"):
        selected = _pinned(row, "period_id", versions)
        if selected:
            fields = selected.get("attributes", {})
            return (
                fields.get("period") == period
                or fields.get("code") == period
                or (
                    str(fields.get("start_date", ""))[:7] == period
                    and str(fields.get("end_date", ""))[:7] == period
                )
            )
    return False


def _node_blockers(row: dict, request: DiagnosticRequest, current: dict[str, str]) -> list[dict]:
    version = str(row["version_id"])
    label = row.get("display_name", row["object_type"])
    refs = {"resource_id": str(row["resource_id"]), "version_id": version}
    result = []
    valid, known = request.valid_at, request.known_at
    assert valid is not None and known is not None
    if _timestamp(row["system_from"]) > known:
        result.append(
            _finding(
                f"{version}:knowledge",
                label,
                "STALE_OR_INCOMPATIBLE",
                "This exact version was not recorded at the selected knowledge time.",
                **refs,
            )
        )
    if _timestamp(row["valid_from"]) > valid or (
        row.get("valid_to") and _timestamp(row["valid_to"]) <= valid
    ):
        result.append(
            _finding(
                f"{version}:effective",
                label,
                "STALE_OR_INCOMPATIBLE",
                "This exact version is outside the selected effective interval.",
                **refs,
            )
        )
    if current.get(str(row["resource_id"])) != version:
        result.append(
            _finding(
                f"{version}:pin",
                label,
                "STALE_OR_INCOMPATIBLE",
                "The retained pin is not the effective version at this context cutoff.",
                **refs,
            )
        )
    authority = row.get("authority_state")
    if authority != "APPROVED":
        state = "STALE_OR_INCOMPATIBLE" if authority == "REVOKED" else "REVIEW_REQUIRED"
        result.append(
            _finding(
                f"{version}:authority",
                label,
                state,
                "This resource has no available approved authority at the selected cutoff.",
                **refs,
            )
        )
    event = row.get("lifecycle") or {}
    if event and (
        event.get("target_state") in {"REVOKED", "SUPERSEDED"}
        or event.get("availability_state") != "AVAILABLE"
    ):
        result.append(
            _finding(
                f"{version}:lifecycle",
                label,
                "STALE_OR_INCOMPATIBLE",
                "The retained lifecycle state withdraws authority or availability.",
                **refs,
            )
        )
    if row.get("evidence_class") == "REFERENCE_TEMPLATE":
        result.append(
            _finding(
                f"{version}:reference",
                label,
                "UNBOUND",
                "Reference templates are not company source evidence.",
                **refs,
            )
        )
    return result


def evaluate(
    request: DiagnosticRequest,
    context: dict,
    rows: list[dict],
    dependencies: list[dict],
    *,
    targets: dict | None = None,
    requirements: dict | None = None,
    runtime_checks: dict[str, dict] | None = None,
    retained_sources: list[dict] | None = None,
    pending_candidates: list[dict] | None = None,
    complete: bool = True,
) -> dict:
    """Pure deterministic projection; the loader supplies only authorized rows and pins."""
    if targets is None or requirements is None:
        targets, requirements = _contracts()
    runtime_checks = runtime_checks or {}
    from finai_api.services.enterprise_diagnostics_sources import source_candidates

    company = str(context["company_id"])
    valid, known = request.valid_at, request.known_at
    assert valid is not None and known is not None
    # Choose the temporal winner before authority filtering; revocation cannot revive old truth.
    versions = {str(row["version_id"]): {**row, "_pins": {}} for row in rows}
    for dep in dependencies:
        source = versions.get(str(dep["version_id"]))
        target_row = versions.get(str(dep["target_version_id"]))
        if (
            source
            and target_row
            and str(target_row["resource_id"]) == str(dep["target_resource_id"])
        ):
            source["_pins"][dep["relation"]] = str(dep["target_version_id"])
    current: dict[str, str] = {}
    for version, row in sorted(
        versions.items(), key=lambda item: (_timestamp(item[1]["system_from"]), item[0])
    ):
        if (
            _timestamp(row["system_from"]) <= known
            and _timestamp(row["valid_from"]) <= valid
            and (not row.get("valid_to") or _timestamp(row["valid_to"]) > valid)
        ):
            current[str(row["resource_id"])] = version
    visible = {
        v: r
        for v, r in versions.items()
        if _in_scope(r, company, versions, str(context.get("access_entity", company)))
    }
    # Knowledge-future resources must not leak labels, hashes, IDs or their existence.
    visible = {v: r for v, r in visible.items() if _timestamp(r["system_from"]) <= known}
    # Source provenance has no company label of its own. Only an exact incoming pin from
    # an already company-bound resource can bring it into this diagnostic perimeter.
    for _ in range(MAX_DEPTH):
        added = False
        for dep in dependencies:
            source = visible.get(str(dep["version_id"]))
            target_row = versions.get(str(dep["target_version_id"]))
            if (
                source
                and target_row
                and str(target_row["resource_id"]) == str(dep["target_resource_id"])
                and target_row["object_type"] in {"SourceEvidence", "SourceRecord"}
                and str(target_row.get("access_entity"))
                in {company, str(context.get("access_entity", company)), "__TENANT__"}
                and _timestamp(target_row["system_from"]) <= known
                and str(target_row["version_id"]) not in visible
            ):
                visible[str(target_row["version_id"])] = target_row
                added = True
        if not added:
            break
    findings: list[dict] = []
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    target = resolve_target(request.target_id, targets)
    roots: list[str] = []
    canonical_target = False
    if target:
        target = dict(target)
        engine = {"state": target["engine_state"], "reason": target["engine_reason"]}
        if engine["state"] != "IMPLEMENTED":
            engine["state"] = "ENGINE_NOT_IMPLEMENTED"
            findings.append(
                _finding("target:engine", target["label"], engine["state"], engine["reason"])
            )
        pending = deque((r, [target["id"]], 0) for r in target.get("requirements", []))
        seen_requirements: set[str] = set()
        requirement_edges: dict[str, set[str]] = {}
        while pending:
            identity, path, depth = pending.popleft()
            edges.append({"source": path[-1], "target": identity, "relation": "REQUIRES"})
            requirement_edges.setdefault(path[-1], set()).add(identity)
            if identity in path:
                findings.append(
                    _finding(
                        f"{identity}:cycle",
                        "Requirement cycle",
                        "STALE_OR_INCOMPATIBLE",
                        "The declared target contract contains a dependency cycle.",
                        path=[*path, identity],
                    )
                )
                complete = False
                continue
            if identity in seen_requirements:
                continue
            seen_requirements.add(identity)
            if depth > MAX_DEPTH or len(seen_requirements) > MAX_NODES:
                findings.append(
                    _finding(
                        "requirements:bounds",
                        "Incomplete requirement inspection",
                        "STALE_OR_INCOMPATIBLE",
                        "Narrow the target: declared dependency bounds were exceeded.",
                    )
                )
                complete = False
                break
            requirement = requirements.get(identity)
            if requirement is None:
                findings.append(
                    _finding(
                        identity,
                        identity,
                        "UNBOUND",
                        "The target references an undeclared input contract.",
                    )
                )
                continue
            for dep in requirement.get("dependencies", []):
                pending.append((dep, [*path, identity], depth + 1))
            matches = [
                r
                for r in visible.values()
                if current.get(str(r["resource_id"])) == str(r["version_id"])
                and r["object_type"] in requirement.get("resource_types", [])
                and _company_match(r, company, visible)
            ]
            candidates = []
            for row in matches:
                version = str(row["version_id"])
                reasons = _node_blockers(row, request, current)
                attrs = row.get("attributes", {})
                if (
                    requirement.get("material", True)
                    and row.get("evidence_class") != "SOURCE_BOUND"
                ):
                    reasons.append(
                        _finding(
                            f"{identity}:{version}:material",
                            requirement["label"],
                            "UNBOUND",
                            "An approved object identity does not establish "
                            "source-bound measurements.",
                        )
                    )
                if requirement.get("material", True) or row["object_type"] in {
                    "JournalEntry",
                    "JournalLine",
                }:
                    reasons.append(
                        _finding(
                            f"{identity}:{version}:coverage",
                            requirement["label"],
                            "UNBOUND",
                            "Observed or governed rows exist, but an installed input validator "
                            "has not established complete grain, unit, currency "
                            "and period coverage.",
                        )
                    )
                check = runtime_checks.get(version)
                if check and check.get("state") != "READY":
                    reasons.append(
                        _finding(
                            f"{identity}:{version}:eligibility",
                            requirement["label"],
                            check["state"],
                            check["reason"],
                        )
                    )
                missing = [
                    f
                    for f in requirement.get("required_fields", [])
                    if attrs.get(f) in (None, "", [])
                ]
                if missing:
                    reasons.append(
                        _finding(
                            f"{identity}:{version}:fields",
                            requirement["label"],
                            "UNBOUND",
                            "Required canonical fields are unbound: " + ", ".join(missing) + ".",
                        )
                    )
                if requirement.get("period_required", True) and not _period_matches(
                    row, context["period"], visible
                ):
                    reasons.append(
                        _finding(
                            f"{identity}:{version}:period",
                            requirement["label"],
                            "STALE_OR_INCOMPATIBLE",
                            "Source period coverage does not establish "
                            "the complete selected period.",
                        )
                    )
                if row["object_type"] == "SourceAccountingBinding" and (
                    attrs.get("source_use") != "ACCOUNTING_INPUT"
                    or attrs.get("contract_version") != "2"
                ):
                    reasons.append(
                        _finding(
                            f"{identity}:{version}:binding",
                            requirement["label"],
                            "UNBOUND",
                            "The source needs a reviewed version 2 "
                            "accounting-input interpretation.",
                        )
                    )
                candidates.append((row, reasons))
            ready_candidates = [row for row, reasons in candidates if not reasons]
            observed = []
            proposed = []
            primary_source = None
            candidate_actions = None
            if ready_candidates:
                state, reason = (
                    "READY",
                    "Matching source-bound inputs satisfy the declared diagnostic contract.",
                )
                chosen = ready_candidates
            elif candidates:
                chosen = [row for row, _ in candidates]
                all_reasons = [f for _, reasons in candidates for f in reasons]
                state = next(s for s in STATES if any(f["state"] == s for f in all_reasons))
                reason = " ".join(dict.fromkeys(f["reason"] for f in all_reasons))
            else:
                chosen = []
                state, reason = (
                    "MISSING_EVIDENCE",
                    "No matching canonical input is available for this company and cutoff.",
                )
                observed = source_candidates(
                    requirement,
                    [r for v, r in visible.items() if current.get(str(r["resource_id"])) == v],
                    company,
                    context["period"],
                    retained_sources=retained_sources,
                )
                if observed:
                    observed.sort(
                        key=lambda c: (
                            {"REVIEW_REQUIRED": 0, "UNBOUND": 1, "STALE_OR_INCOMPATIBLE": 2}[
                                c["state"]
                            ],
                            c.get("company_binding_state") != "REVIEWED_SCOPE",
                            str(c.get("document_id", "")),
                            str(c.get("worksheet", "")),
                        )
                    )
                    primary_source = observed[0]
                    scoped = primary_source.get("company_binding_state") == "REVIEWED_SCOPE"
                    if scoped or primary_source["state"] != "STALE_OR_INCOMPATIBLE":
                        state = primary_source["state"]
                        reason = (
                            "A recognized source observation exists for this company. "
                            if scoped
                            else "An authorized unassigned upload may match this input class; "
                            "its company identity is not established. "
                        ) + primary_source["reason"]
                    candidate_actions = [
                        _action(
                            "OPEN_RESOURCE",
                            "Inspect candidate source evidence",
                            document_id=primary_source.get("document_id"),
                            resource_id=primary_source.get("resource_id"),
                        ),
                        _action(
                            "REVIEW_BINDING",
                            "Review company and input binding",
                            document_id=primary_source.get("document_id"),
                            resource_id=primary_source.get("resource_id"),
                        ),
                    ]
            if not ready_candidates:
                proposed = [
                    p
                    for p in pending_candidates or []
                    if p.get("object_type") in requirement.get("resource_types", [])
                    and p.get("company_id") == company
                ]
                if proposed:
                    state = "REVIEW_REQUIRED"
                    reason += (
                        f" {len(proposed)} proposed input(s) await independent review. "
                        "Pending proposals provide no calculation authority."
                    )
                    candidate_actions = [
                        _action(
                            "REVIEW_BINDING",
                            "Open pending proposal review",
                            proposal_id=p["proposal_id"],
                        )
                        for p in proposed[:5]
                    ]
            guidance = requirement.get("guidance", "")
            if guidance and state != "READY":
                reason += " " + guidance
            nodes[identity] = {"id": identity, "label": requirement["label"], "state": state}
            if state != "READY":
                findings.append(
                    _finding(
                        identity,
                        requirement["label"],
                        state,
                        reason,
                        requirement_id=identity,
                        path=[*path, identity],
                        examples=requirement.get("examples", []),
                        required_fields=requirement.get("required_fields", []),
                        grain=requirement.get("grain", []),
                        scope_fields=requirement.get("scope_fields", []),
                        schema_state=requirement.get("schema_state"),
                        source_candidates=observed[:8],
                        source_candidate_count=len(observed),
                        pending_proposals=proposed[:8],
                        document_id=primary_source.get("document_id") if primary_source else None,
                        source_filename=primary_source.get("filename") if primary_source else None,
                        actions=candidate_actions,
                    )
                )
            for row in chosen:
                version = str(row["version_id"])
                roots.append(version)
                edges.append({"source": identity, "target": version, "relation": "CANDIDATE_INPUT"})
        requirement_nodes = set(requirement_edges) | {
            child for children in requirement_edges.values() for child in children
        }
        degree = dict.fromkeys(requirement_nodes, 0)
        for children in requirement_edges.values():
            for child in children:
                degree[child] += 1
        ready_requirements = deque(n for n, value in degree.items() if value == 0)
        lengths = dict.fromkeys(requirement_nodes, 0)
        removed_requirements = 0
        while ready_requirements:
            parent = ready_requirements.popleft()
            removed_requirements += 1
            for child in requirement_edges.get(parent, set()):
                lengths[child] = max(lengths[child], lengths[parent] + 1)
                degree[child] -= 1
                if degree[child] == 0:
                    ready_requirements.append(child)
        if removed_requirements != len(degree) or any(n > MAX_DEPTH + 1 for n in lengths.values()):
            complete = False
            findings.append(
                _finding(
                    "requirements:cycle",
                    "Invalid requirement dependency graph",
                    "STALE_OR_INCOMPATIBLE",
                    "The declared requirement graph contains a cycle "
                    "or exceeds the maximum path depth.",
                )
            )
    else:
        canonical_target = True
        try:
            resource_id = str(UUID(request.target_id))
        except ValueError:
            resource_id = ""
        root = (
            visible.get(str(request.root_version_id))
            if request.root_version_id
            else visible.get(current.get(resource_id, ""))
        )
        if root is None or str(root["resource_id"]) != resource_id:
            target = {
                "id": request.target_id,
                "label": "Unresolved enterprise target",
                "domain": "enterprise",
            }
            engine = {
                "state": "UNKNOWN_TARGET",
                "reason": "Select one declared target or an authorized "
                "canonical resource at this cutoff.",
            }
            findings.append(
                _finding("target:unknown", target["label"], "UNKNOWN_TARGET", engine["reason"])
            )
        else:
            roots = [str(root["version_id"])]
            target = {
                "id": resource_id,
                "label": root.get("display_name", root["object_type"]),
                "domain": "canonical",
            }
            check = runtime_checks.get(roots[0])
            engine = {
                "state": "IMPLEMENTED"
                if check and check.get("engine_implemented")
                else "ENGINE_NOT_IMPLEMENTED",
                "reason": check.get("engine_reason", check.get("reason", ""))
                if check
                else "No installed executable target adapter was verified for this resource. "
                "A schema or accepted object is not a calculation engine.",
            }
            if engine["state"] == "ENGINE_NOT_IMPLEMENTED":
                findings.append(
                    _finding("target:engine", target["label"], engine["state"], engine["reason"])
                )

    adjacency: dict[str, list[dict]] = {}
    for dep in dependencies:
        adjacency.setdefault(str(dep["version_id"]), []).append(dep)
    pending_nodes = deque((v, [target["id"]], 0) for v in sorted(set(roots)))
    visited: set[str] = set()
    graph_neighbors: dict[str, set[str]] = {}
    while pending_nodes:
        version, path, depth = pending_nodes.popleft()
        if version in visited:
            continue
        if len(visited) >= MAX_NODES or depth > MAX_DEPTH or len(edges) > MAX_EDGES:
            complete = False
            findings.append(
                _finding(
                    "graph:bounds",
                    "Incomplete graph inspection",
                    "STALE_OR_INCOMPATIBLE",
                    "The dependency graph exceeds the diagnostic bound; "
                    "narrow the selected target.",
                )
            )
            break
        visited.add(version)
        row = visible.get(version)
        if row is None:
            # Deliberately do not distinguish hidden data from absent data.
            findings.append(
                _finding(
                    "graph:unavailable:" + str(len(findings)),
                    "Unavailable dependency",
                    "MISSING_EVIDENCE",
                    "A required exact dependency is unavailable in the selected "
                    "company and knowledge context.",
                    path=path,
                )
            )
            continue
        node_findings = _node_blockers(row, request, current)
        check = runtime_checks.get(version)
        if check and check.get("state") != "READY":
            node_findings.append(
                _finding(
                    version + ":runtime",
                    row.get("display_name", row["object_type"]),
                    check["state"],
                    check["reason"],
                    resource_id=str(row["resource_id"]),
                    version_id=version,
                )
            )
        findings.extend(node_findings)
        nodes[version] = {
            "id": version,
            "label": row.get("display_name", row["object_type"]),
            "state": next(
                (s for s in STATES if any(f["state"] == s for f in node_findings)), "READY"
            ),
            "object_type": row["object_type"],
            "resource_id": str(row["resource_id"]),
            "version_id": version,
            "content_hash": row.get("content_hash"),
            "authority_state": row.get("authority_state"),
            "evidence_class": row.get("evidence_class"),
            "valid_from": str(row["valid_from"]),
            "valid_to": str(row["valid_to"]) if row.get("valid_to") else None,
            "system_from": str(row["system_from"]),
        }
        refs = adjacency.get(version, [])
        for field, identity in row.get("attributes", {}).items():
            if not field.endswith("_id") or not isinstance(identity, str):
                continue
            try:
                UUID(identity)
            except ValueError:
                continue
            if not any(
                str(d["target_resource_id"]) == identity and d["relation"] == "FIELD:" + field
                for d in refs
            ):
                findings.append(
                    _finding(
                        f"{version}:missing-link:{field}",
                        nodes[version]["label"],
                        "UNBOUND",
                        f"The declared {field.removesuffix('_id').replace('_', ' ')} "
                        "reference has no exact dependency pin.",
                        resource_id=str(row["resource_id"]),
                        version_id=version,
                        actions=[
                            _action(
                                "REVIEW_BINDING",
                                "Review the missing dependency link",
                                resource_id=str(row["resource_id"]),
                            )
                        ],
                    )
                )
        for dep in refs:
            target_version = str(dep["target_version_id"])
            target_row = visible.get(target_version)
            if target_row and str(target_row["resource_id"]) != str(dep["target_resource_id"]):
                findings.append(
                    _finding(
                        version + ":bad-pin",
                        nodes[version]["label"],
                        "STALE_OR_INCOMPATIBLE",
                        "A dependency resource identity disagrees with its exact version pin.",
                    )
                )
                complete = False
                continue
            # Do not expose hidden target identifiers through an otherwise visible edge.
            public_target = target_version if target_row else "unavailable:" + str(len(edges))
            edges.append({"source": version, "target": public_target, "relation": dep["relation"]})
            graph_neighbors.setdefault(version, set()).add(target_version)
            pending_nodes.append((target_version, [*path, version], depth + 1))
    # Kahn traversal detects cycles while allowing shared dependencies and diamonds.
    indegree = dict.fromkeys(visited, 0)
    for source in visited:
        for child in graph_neighbors.get(source, set()) & visited:
            indegree[child] += 1
    ready = deque(v for v, degree in indegree.items() if degree == 0)
    longest = dict.fromkeys(visited, 0)
    removed = 0
    while ready:
        node = ready.popleft()
        removed += 1
        for child in graph_neighbors.get(node, set()) & visited:
            longest[child] = max(longest[child], longest[node] + 1)
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    if removed != len(indegree):
        findings.append(
            _finding(
                "graph:cycle",
                "Dependency cycle",
                "STALE_OR_INCOMPATIBLE",
                "The selected canonical dependency graph contains a cycle.",
            )
        )
        complete = False
    elif any(depth > MAX_DEPTH for depth in longest.values()):
        findings.append(
            _finding(
                "graph:bounds",
                "Incomplete graph inspection",
                "STALE_OR_INCOMPATIBLE",
                "The canonical dependency graph exceeds the maximum path depth.",
            )
        )
        complete = False
    if not complete and not any(f["id"].endswith((":bounds", ":cycle")) for f in findings):
        findings.append(
            _finding(
                "snapshot:bounds",
                "Incomplete snapshot",
                "STALE_OR_INCOMPATIBLE",
                "The authorized snapshot exceeded its read bound; "
                "absence and readiness are not established.",
            )
        )
    # A positive runtime check is mandatory; a fully approved structural graph is insufficient.
    if canonical_target and roots and not runtime_checks.get(roots[0]) and not findings:
        findings.append(
            _finding(
                "target:unverified",
                target["label"],
                "ENGINE_NOT_IMPLEMENTED",
                "No target-specific execution adapter was verified.",
            )
        )
    findings = list({f["id"]: f for f in findings}.values())
    for finding in findings:
        node = nodes.get(finding.get("version_id", ""))
        if node and node["state"] == "READY":
            node["state"] = finding["state"]
    # A ready parent cannot conceal a blocked dependency in either graph.
    for _ in range(MAX_DEPTH + 1):
        changed = False
        for edge in edges:
            parent, child = nodes.get(edge["source"]), nodes.get(edge["target"])
            if parent and child and parent["state"] == "READY" and child["state"] != "READY":
                parent["state"] = "UNBOUND"
                findings.append(
                    _finding(
                        parent["id"] + ":upstream",
                        parent["label"],
                        "UNBOUND",
                        "An upstream dependency has not passed its declared input checks.",
                    )
                )
                changed = True
        if not changed:
            break
    findings.sort(key=lambda f: (STATES.index(f["state"]), f["id"]))
    state = findings[0]["state"] if findings else "READY"
    counts = dict(Counter(f["state"] for f in findings))
    ready_count = sum(n["state"] == "READY" for n in nodes.values())
    if not findings:
        summary = (
            f"{target['label']}: the declared diagnostic checks are ready for this company "
            "and cutoff. Execution must recheck its inputs; no financial result was calculated."
        )
    else:
        summary = (
            f"{target['label']}: {len(findings)} blocking findings; {ready_count} inspected "
            "nodes pass their declared checks. "
            + (
                "The business computation is not implemented, so uploading evidence "
                "alone cannot unlock this target. "
                if engine["state"] == "ENGINE_NOT_IMPLEMENTED"
                else ""
            )
            + " ".join(f"{f['label']}: {f['reason']}" for f in findings[:3])
        )
    result = {
        "contract_version": VERSION,
        "target": {k: target[k] for k in ("id", "label", "domain")},
        "context": context,
        "state": state,
        "engine": engine,
        "findings": findings,
        "nodes": sorted(nodes.values(), key=lambda n: n["id"]),
        "edges": sorted(edges, key=lambda e: (e["source"], e["target"], e["relation"])),
        "summary": summary,
        "counts": counts,
        "complete": complete,
        "actions": [
            _action("RECHECK", "Recheck this target and context"),
            *list(
                {json.dumps(a, sort_keys=True): a for f in findings for a in f["actions"]}.values()
            ),
        ],
        "recheck": {"request": request.model_dump(mode="json")},
        "unassigned_sources": retained_sources or [],
        "current_use_authorized": False,
        "business_effect_authorized": False,
        "financial_certification": None,
        "amounts_calculated": False,
    }
    result = _json(result)
    result["fingerprint"] = sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return result


def _runtime_check(principal: Principal, row: dict, request: DiagnosticRequest) -> dict:
    kind = row["object_type"]
    if kind == "SourceAccountingBinding":
        from finai_api.services.accounting_binding_status import inspect

        status = inspect(principal, _json(row))
        return {
            "engine_implemented": False,
            "engine_reason": "A source accounting binding is configuration, "
            "not a calculation engine.",
            "state": "READY" if status["state"] == "ELIGIBLE_FOR_GUARDED_USE" else "UNBOUND",
            "reason": status["reason"],
        }
    if kind == "FactContract":
        from finai_api.domain.ontology_definitions import FactContract

        try:
            FactContract.model_validate(row["attributes"]["definition"])
        except (ValueError, KeyError, TypeError):
            return {
                "engine_implemented": False,
                "state": "ENGINE_NOT_IMPLEMENTED",
                "reason": "This resource does not contain an executable FactContract.",
            }
        return {
            "engine_implemented": True,
            "state": "UNBOUND",
            "reason": "The shared fact aggregation engine exists. Select its exact Object Set, "
            "grouping and observation cutoff in analysis to validate material rows; "
            "the contract alone contains no facts.",
        }
    if kind == "FunctionDefinition":
        from finai_api.domain.function_execution import FunctionDefinition, FunctionInvocation
        from finai_api.services.function_execution import _check_implementation, plan

        try:
            spec = FunctionDefinition.model_validate(row["attributes"])
        except (ValueError, KeyError, TypeError):
            return {
                "engine_implemented": False,
                "state": "ENGINE_NOT_IMPLEMENTED",
                "reason": "The Function has no supported executable adapter contract.",
            }
        try:
            _check_implementation(spec)
        except WorkspaceError as exc:
            return {
                "engine_implemented": True,
                "state": "STALE_OR_INCOMPATIBLE",
                "reason": exc.detail,
            }
        if request.period != principal.scope.period:
            return {
                "engine_implemented": True,
                "state": "UNBOUND",
                "reason": "Canonical dependencies were inspected for the requested month. "
                "Retained source execution remains in the original authorized document scope; "
                "select that source scope before running this Function.",
            }
        try:
            invocation = FunctionInvocation(
                function={"resource_id": row["resource_id"], "version_id": row["version_id"]},
                valid_at=request.valid_at,
                known_at=request.known_at,
                limit=min(50, getattr(spec.definition, "row_count", 50)),
            )
            compiled = plan(principal, invocation)
        except WorkspaceError as exc:
            return {
                "engine_implemented": True,
                "state": "UNBOUND" if exc.status == 422 else "STALE_OR_INCOMPATIBLE",
                "reason": exc.detail,
            }
        if compiled.get("source_document"):
            return {
                "engine_implemented": True,
                "state": "READY",
                "reason": "Installed Function manifest and exact retained source are verified "
                "for source analysis only.",
            }
        return {
            "engine_implemented": True,
            "state": "UNBOUND",
            "reason": "The exact Function plan is valid. Run its saved analysis to inspect "
            "the selected material rows and retained result; structural dependencies "
            "do not establish metric coverage.",
        }
    if kind == "TransformationDefinition":
        from finai_api.domain.transformation import TransformationDefinition

        try:
            TransformationDefinition.model_validate(row["attributes"])
        except (ValueError, KeyError, TypeError):
            return {
                "engine_implemented": False,
                "state": "ENGINE_NOT_IMPLEMENTED",
                "reason": "The resource has no supported executable Transformation DAG.",
            }
        return {
            "engine_implemented": True,
            "state": "UNBOUND",
            "reason": "The shared Transformation DAG engine exists. Each exact Function "
            "and required retained result must pass its input checks before execution.",
        }
    if kind == "MetricDefinition":
        from finai_api.domain.metric_execution import MetricDefinition

        try:
            MetricDefinition.model_validate(row["attributes"]["definition"])
            if not row["attributes"].get("function_id"):
                raise ValueError("missing function")
        except (ValueError, KeyError, TypeError):
            return {
                "engine_implemented": False,
                "state": "ENGINE_NOT_IMPLEMENTED",
                "reason": "This Metric is a structural definition without "
                "an executable selector and Function.",
            }
        return {
            "engine_implemented": True,
            "state": "UNBOUND",
            "reason": "The shared metric observation engine exists. Supply the exact retained "
            "Function result before observation; an accepted Metric definition "
            "is not a measured value.",
        }
    return {
        "engine_implemented": False,
        "state": "ENGINE_NOT_IMPLEMENTED",
        "reason": "No installed computation adapter is declared for this resource type. "
        "Its ontology identity and dependencies remain inspectable.",
    }


def diagnose(principal: Principal, request: DiagnosticRequest) -> dict:
    require_permission(principal, "ontology_read")
    now = datetime.now(UTC)
    known = request.known_at or now
    if known > now:
        raise WorkspaceError(422, "Diagnostic knowledge time cannot be in the future")
    period = request.period or principal.scope.period
    # Canonical period selection does not broaden the original source-document access scope.
    company = str(request.company_id or principal.scope.legal_entity_id)
    try:
        company_uuid = UUID(company)
    except ValueError as exc:
        raise WorkspaceError(
            422, "Select an authorized canonical company before diagnosis"
        ) from exc
    request = request.model_copy(
        update={
            "company_id": company_uuid,
            "period": period,
            "valid_at": request.valid_at or known,
            "known_at": known,
        }
    )
    targets, requirements = _contracts()
    target = resolve_target(request.target_id, targets)
    kinds = {"LegalEntity", "SourceAccountingScope", "SourceAccountingBinding", "FiscalPeriod"}
    if target:
        pending_requirements = list(target.get("requirements", []))
        reached = set()
        while pending_requirements:
            identity = pending_requirements.pop()
            if identity in reached:
                continue
            reached.add(identity)
            requirement = requirements.get(identity, {})
            kinds.update(requirement.get("resource_types", []))
            pending_requirements.extend(requirement.get("dependencies", []))
    try:
        root_id = UUID(request.target_id)
    except ValueError:
        root_id = None
    complete = True
    with (
        resource_connection(principal, repeatable_read=True) as conn,
        conn.cursor(row_factory=dict_row) as cur,
    ):
        cur.execute("SELECT set_config('statement_timeout','10000',true)")
        params = {
            "tenant": principal.scope.tenant_id,
            "known": known,
            "valid": request.valid_at,
            "access": principal.scope.legal_entity_id,
            "company": company,
            "kinds": sorted(kinds),
            "root": root_id,
        }
        # Explicit company predicates prevent ontology_admin from silently widening diagnosis.
        rows = cur.execute(
            "SELECT * FROM (SELECT DISTINCT ON(v.resource_id) v.* FROM resource_versions v "
            "WHERE v.tenant_id=%(tenant)s "
            "AND v.access_entity IN (%(access)s,'__TENANT__','__PLATFORM__') "
            "AND v.system_from<=%(known)s AND v.valid_from<=%(valid)s "
            "AND (v.valid_to IS NULL OR v.valid_to>%(valid)s) "
            "AND (v.object_type=ANY(%(kinds)s) OR v.resource_id=%(root)s) "
            "ORDER BY v.resource_id,v.system_from DESC,v.version_id) snapshot "
            "ORDER BY resource_id LIMIT 2001",
            params,
        ).fetchall()
        complete = len(rows) <= MAX_CANDIDATES
        rows = rows[:MAX_CANDIDATES]
        company_row = next(
            (
                r
                for r in rows
                if str(r["resource_id"]) == company and r["object_type"] == "LegalEntity"
            ),
            None,
        )
        if (
            company_row is None
            or company_row["authority_state"] != "APPROVED"
            or company_row["evidence_class"] == "REFERENCE_TEMPLATE"
        ):
            raise WorkspaceError(404, "Company unavailable in the authorized diagnostic context")
        versions = {str(r["version_id"]): r for r in rows}
        if root_id and request.root_version_id:
            root = cur.execute(
                "SELECT v.* FROM resource_versions v WHERE tenant_id=%s "
                "AND resource_id=%s AND version_id=%s "
                "AND system_from<=%s AND access_entity IN (%s,'__TENANT__','__PLATFORM__')",
                (
                    principal.scope.tenant_id,
                    root_id,
                    request.root_version_id,
                    known,
                    principal.scope.legal_entity_id,
                ),
            ).fetchone()
            if root:
                versions[str(root["version_id"])] = root
        # Traverse all selected candidate inputs, with one batched SQL read per graph level.
        pending = set(versions)
        traversed: set[str] = set()
        dependencies = []
        for _depth in range(MAX_DEPTH + 1):
            if not pending:
                break
            batch = sorted(pending - traversed)
            if not batch:
                break
            traversed.update(batch)
            deps = cur.execute(
                "SELECT version_id,relation,target_resource_id,target_version_id "
                "FROM resource_dependencies WHERE tenant_id=%s AND version_id=ANY(%s::uuid[]) "
                "ORDER BY version_id,relation,target_version_id LIMIT 5001",
                (principal.scope.tenant_id, batch),
            ).fetchall()
            if len(dependencies) + len(deps) > MAX_EDGES:
                complete = False
                break
            dependencies.extend(deps)
            wanted = {str(d["target_version_id"]) for d in deps} - set(versions)
            if len(wanted) + len(versions) > MAX_CANDIDATES + MAX_NODES:
                complete = False
                break
            if wanted:
                loaded = cur.execute(
                    "SELECT v.* FROM resource_versions v WHERE tenant_id=%s "
                    "AND version_id=ANY(%s::uuid[]) "
                    "AND system_from<=%s AND access_entity IN (%s,'__TENANT__','__PLATFORM__')",
                    (
                        principal.scope.tenant_id,
                        sorted(wanted),
                        known,
                        principal.scope.legal_entity_id,
                    ),
                ).fetchall()
                versions.update({str(r["version_id"]): r for r in loaded})
            pending = {str(d["target_version_id"]) for d in deps} - traversed
        else:
            complete = False
        # Exact pins can reference old versions of types outside the initial target query.
        # Load their temporal winners separately so an old approved pin cannot look current.
        winners = cur.execute(
            "SELECT DISTINCT ON(v.resource_id) v.* FROM resource_versions v WHERE tenant_id=%s "
            "AND resource_id=ANY(%s::uuid[]) AND system_from<=%s AND valid_from<=%s "
            "AND (valid_to IS NULL OR valid_to>%s) "
            "AND access_entity IN (%s,'__TENANT__','__PLATFORM__') "
            "ORDER BY resource_id,system_from DESC,version_id",
            (
                principal.scope.tenant_id,
                sorted({str(r["resource_id"]) for r in versions.values()}),
                known,
                request.valid_at,
                request.valid_at,
                principal.scope.legal_entity_id,
            ),
        ).fetchall()
        versions.update({str(r["version_id"]): r for r in winners})
        events = cur.execute(
            "SELECT DISTINCT ON(version_id) version_id,payload FROM resource_lifecycle_events "
            "WHERE tenant_id=%s AND version_id=ANY(%s::uuid[]) AND recorded_at<=%s "
            "ORDER BY version_id,recorded_at DESC,event_id DESC",
            (principal.scope.tenant_id, sorted(versions), known),
        ).fetchall()
        for event in events:
            versions[str(event["version_id"])]["lifecycle"] = event["payload"]
        context = {
            "company_id": company,
            "company_label": company_row["display_name"],
            "period": period,
            "currency": principal.scope.currency,
            "valid_at": request.valid_at.isoformat(),
            "known_at": known.isoformat(),
            "access_entity": principal.scope.legal_entity_id,
        }
    from finai_api.services.enterprise_diagnostics_sources import load_pending, load_unassigned

    assigned = {
        r.get("attributes", {}).get("document_id")
        for r in versions.values()
        if r["object_type"] == "SourceAccountingScope"
        and str(r.get("attributes", {}).get("legal_entity_id")) == company
    }
    retained = load_unassigned(principal, known, {str(d) for d in assigned if d})
    proposals = load_pending(principal, company, known, kinds if target else set())
    complete = complete and retained["complete"] and proposals["complete"]
    for row in versions.values():
        row["_pins"] = {}
    for dep in dependencies:
        source = versions.get(str(dep["version_id"]))
        if source:
            source["_pins"][dep["relation"]] = str(dep["target_version_id"])
    checks = {}
    # Run existing read-only Function preflight, never invoke or publish its result.
    relevant = [
        r
        for r in versions.values()
        if r["object_type"] in ENGINE_TYPES | {"SourceAccountingBinding"}
        and _in_scope(r, company, versions, principal.scope.legal_entity_id)
    ]
    for row in relevant[:32]:
        checks[str(row["version_id"])] = _runtime_check(principal, row, request)
    if len(relevant) > 32:
        complete = False
    return evaluate(
        request,
        context,
        list(versions.values()),
        dependencies,
        targets=targets,
        requirements=requirements,
        runtime_checks=checks,
        retained_sources=retained["items"],
        pending_candidates=proposals["items"],
        complete=complete,
    )
