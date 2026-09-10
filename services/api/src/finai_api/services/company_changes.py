"""Read-only context membership/version comparison; no financial significance inference."""

import json
import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import ValidationError

from finai_api.domain.company_changes import (
    CompanyChangesDescriptor,
    CompanyChangesRequest,
    CompanyContextChange,
)
from finai_api.domain.resources import CanonicalResource
from finai_api.domain.review import Principal
from finai_api.security import require_permission
from finai_api.services import company_condition, company_context
from finai_api.services.workspace import WorkspaceError

RESOURCE_LIMIT = 5000
RESPONSE_BYTES = 8 * 1024 * 1024
_HASH = re.compile(r"[a-f0-9]{64}")
_FIELDS = (
    "display_name",
    "schema_version_id",
    "valid_from",
    "valid_to",
    "authority_state",
    "evidence_class",
    "access_entity",
)
_LIMITATIONS = [
    "Both snapshots use the same effective time; only the retained knowledge cutoff changes.",
    "Coverage includes explicit company context, matching workspaces and accepted pinned "
    "connections; it is not a complete company activity or financial change history.",
    "Added and removed mean context membership, not creation or deletion. Changed fields "
    "are JSON Pointer paths to retained metadata or top-level attributes; they do not "
    "establish financial materiality, operating risk or compliance.",
    "Current work queues, binding eligibility advice and current-use authority are excluded. "
    "A version may change without changing the displayed fields.",
]


def _accepted(
    value: Any,
    principal: Principal,
    valid: datetime,
    known: datetime,
) -> CanonicalResource | None:
    try:
        node = CanonicalResource.model_validate(value)
    except ValidationError as exc:
        raise WorkspaceError(409, "Company comparison contains malformed canonical data") from exc
    if node.authority_state != "APPROVED" or node.evidence_class == "REFERENCE_TEMPLATE":
        return None
    if "ontology_admin" not in principal.permissions and node.access_entity not in (
        principal.scope.legal_entity_id,
        "__PLATFORM__",
    ):
        raise WorkspaceError(409, "Company comparison contains context outside the reader scope")
    dates = (node.valid_from, node.system_from, node.valid_to)
    if (
        any(value is not None and value.utcoffset() is None for value in dates)
        or node.system_from > known
        or node.valid_from > valid
        or (node.valid_to is not None and node.valid_to <= valid)
        or not _HASH.fullmatch(node.content_hash)
    ):
        raise WorkspaceError(409, "Company comparison contains an invalid exact snapshot")
    return node


def _same_resource(left: CanonicalResource, right: CanonicalResource) -> bool:
    # Python container equality conflates JSON true/1; exact retained values must not.
    return json.dumps(left.model_dump(mode="json"), sort_keys=True, allow_nan=False) == json.dumps(
        right.model_dump(mode="json"),
        sort_keys=True,
        allow_nan=False,
    )


def _add(nodes: dict[UUID, CanonicalResource], node: CanonicalResource) -> None:
    previous = nodes.get(node.resource_id)
    if previous is not None and not _same_resource(previous, node):
        raise WorkspaceError(409, "Company comparison has conflicting versions of one identity")
    nodes[node.resource_id] = node
    if len(nodes) > RESOURCE_LIMIT:
        raise WorkspaceError(409, "Company comparison exceeds its resource bound")


def _collect(
    value: Any,
    nodes: dict[UUID, CanonicalResource],
    principal: Principal,
    valid: datetime,
    known: datetime,
) -> None:
    pending = [(value, 0)]
    visited = set()
    while pending:
        current, depth = pending.pop()
        if not isinstance(current, (dict, list, tuple, CanonicalResource)):
            continue
        if id(current) in visited:
            continue
        visited.add(id(current))
        if depth > 32 or len(visited) > 50_000:
            raise WorkspaceError(409, "Company comparison exceeds its context traversal bound")
        if isinstance(current, CanonicalResource) or (
            isinstance(current, dict) and {"resource_id", "version_id"}.intersection(current)
        ):
            node = _accepted(current, principal, valid, known)
            if node is not None:
                _add(nodes, node)
            # Attributes are retained values, never another universe of canonical objects.
            continue
        if isinstance(current, dict):
            pending.extend(
                (nested, depth + 1)
                for key, nested in current.items()
                if key != "binding_eligibility"
            )
        else:
            pending.extend((nested, depth + 1) for nested in current)


def _snapshot(
    principal: Principal,
    company_id: UUID,
    valid: datetime,
    known: datetime,
) -> tuple[CanonicalResource, dict[UUID, CanonicalResource]]:
    snapshot = company_context.resolve(principal, company_id, valid, known)
    try:
        context = snapshot["context"]
        if not context:
            raise WorkspaceError(404, "Company must exist at both knowledge cutoffs")
        if (
            datetime.fromisoformat(snapshot["valid_at"]) != valid
            or datetime.fromisoformat(snapshot["known_at"]) != known
        ):
            raise WorkspaceError(409, "Company comparison context changed its requested cutoffs")
        company = _accepted(context["company"], principal, valid, known)
        if (
            company is None
            or company.resource_id != company_id
            or company.object_type != "LegalEntity"
        ):
            raise WorkspaceError(404, "Company must exist at both knowledge cutoffs")
        nodes: dict[UUID, CanonicalResource] = {}
        _collect(context, nodes, principal, valid, known)
        for workspace in snapshot.get("workspaces", []):
            if str(workspace["company"]["resource_id"]) == str(company_id):
                _collect(workspace, nodes, principal, valid, known)
        connected_nodes, pins = company_condition.connection_snapshot(principal, valid, known)
        exact_connections: dict[UUID, CanonicalResource] = {}
        for value in connected_nodes:
            node = _accepted(value, principal, valid, known)
            if node is not None:
                _add(exact_connections, node)
        connections = company_condition.connected(company, list(exact_connections.values()), pins)
        for edge in connections:
            for node in (edge.record, edge.relation, edge.source, edge.target):
                _add(nodes, node)
        if (
            sum(len(node.model_dump_json().encode("utf-8")) for node in nodes.values())
            > RESPONSE_BYTES
        ):
            raise WorkspaceError(409, "Company comparison exceeds its snapshot byte bound")
        return company, nodes
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkspaceError(409, "Company comparison contains malformed snapshot context") from exc


def _changed_fields(before: CanonicalResource, after: CanonicalResource) -> list[str]:
    changes = ["/" + name for name in _FIELDS if getattr(before, name) != getattr(after, name)]
    for key in before.attributes.keys() | after.attributes.keys():
        try:
            different = (
                key not in before.attributes
                or key not in after.attributes
                or json.dumps(before.attributes[key], sort_keys=True, allow_nan=False)
                != json.dumps(after.attributes[key], sort_keys=True, allow_nan=False)
            )
        except (TypeError, ValueError) as exc:
            raise WorkspaceError(
                409, "Company comparison attributes are not retained JSON"
            ) from exc
        if different:
            changes.append("/attributes/" + key.replace("~", "~0").replace("/", "~1"))
    return sorted(changes)


def compare(principal: Principal, request: CompanyChangesRequest) -> CompanyChangesDescriptor:
    require_permission(principal, "ontology_read")
    require_permission(principal, "read")
    # Revalidate even for internal callers constructing model_copy updates without validation.
    request = CompanyChangesRequest.model_validate(request.model_dump())
    _, before = _snapshot(principal, request.company_id, request.valid_at, request.compare_known_at)
    company, after = _snapshot(principal, request.company_id, request.valid_at, request.known_at)
    changes = []
    for identity in sorted(before.keys() | after.keys(), key=str):
        old, new = before.get(identity), after.get(identity)
        kind: Literal["ADDED_TO_CONTEXT", "REMOVED_FROM_CONTEXT", "CHANGED_VERSION"]
        fields = []
        if old is None:
            kind = "ADDED_TO_CONTEXT"
        elif new is None:
            kind = "REMOVED_FROM_CONTEXT"
        else:
            if (old.object_type, old.identity_key) != (new.object_type, new.identity_key):
                raise WorkspaceError(409, "Company comparison has conflicting canonical identity")
            if old.version_id == new.version_id:
                if not _same_resource(old, new):
                    raise WorkspaceError(409, "One retained version has inconsistent content")
                continue
            kind = "CHANGED_VERSION"
            fields = _changed_fields(old, new)
        changes.append(
            CompanyContextChange(
                resource_id=identity,
                kind=kind,
                before=old,
                after=new,
                changed_fields=fields,
            )
        )
        if len(changes) > RESOURCE_LIMIT:
            raise WorkspaceError(409, "Company comparison exceeds its change bound")
    result = CompanyChangesDescriptor(
        company=company,
        valid_at=request.valid_at,
        known_at=request.known_at,
        compare_known_at=request.compare_known_at,
        changes=changes,
        limitations=_LIMITATIONS,
    )
    if len(result.model_dump_json().encode("utf-8")) > RESPONSE_BYTES:
        raise WorkspaceError(409, "Company comparison exceeds its response byte bound")
    return result
